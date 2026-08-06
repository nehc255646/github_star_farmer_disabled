"""GitHub Star 刷取工具 - 主入口。

用法:
    python main.py --config config.yaml
    python main.py --accounts accounts.txt --repo owner/repo   # 已有账号直接刷星
    python main.py --accounts accounts.txt --resume             # 续跑未完成账号
"""

import argparse
import concurrent.futures as cf
import json
import logging
import os
import random
import signal
import sys
import time

import yaml
from browser_api import sync_playwright, engine as browser_engine

from account import AccountGenerator, AccountStore
from email_client import MailTMClient
from registrar import ChallengeDetected, Registrar
from star_booster import StarBooster
from tor_control import TorControl, get_public_ip
import network as net_switch
from proxy_pool import ProxyPool, load_proxies_from_file
from session_store import SessionStore
from stealth import make_fingerprint
from challenge import inspect_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("star_farmer.main")
logger.info("浏览器驱动: %s", browser_engine())

# 全局停止标志（优雅停机）
STOP = {"flag": False}


def _handle_sigterm(signum, frame):
    logger.warning("收到信号 %s，正在优雅停机…", signum)
    STOP["flag"] = True


signal.signal(signal.SIGINT, _handle_sigterm)
signal.signal(signal.SIGTERM, _handle_sigterm)


_NET_CFG = {}


def _guard_network(cfg):
    """注册网络恢复兜底：崩溃/退出时自动恢复 Tor 透明代理，避免 iptables 残留断网。"""
    _NET_CFG.update({
        "restore": cfg.get("restore_tor_after", False) and cfg.get("network_mode") == "direct",
        "torify_script": cfg.get("torify_script"),
        "untorify_script": cfg.get("untorify_script"),
    })
    if _NET_CFG["restore"]:
        try:
            import atexit
            atexit.register(_restore_network_on_exit)
            logger.info("已注册网络恢复兜底（异常退出时自动恢复 Tor）")
        except Exception as e:
            logger.warning("注册网络兜底失败: %s", e)


def _restore_network_on_exit():
    """进程退出（含崩溃/信号）时恢复 Tor，避免 iptables 残留。"""
    if _NET_CFG.get("restore"):
        try:
            logger.warning("进程退出，恢复 Tor 透明代理…")
            net_switch.enable_tor(
                torify_script=_NET_CFG.get("torify_script"),
                untorify_script=_NET_CFG.get("untorify_script"),
            )
        except Exception as e:
            logger.error("网络恢复失败: %s", e)


def load_config(path):
    """加载配置，带容错与默认值（缺陷：缺失配置直接 traceback）。"""
    if not os.path.exists(path):
        logger.error("配置文件不存在: %s（请检查路径或复制 config.example.yaml）", path)
        sys.exit(1)
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.error("配置文件解析失败: %s", e)
        sys.exit(1)
    # 默认值兜底，避免 KeyError
    cfg.setdefault("target_repo", "octocat/Hello-World")
    cfg.setdefault("star_count", 10)
    cfg.setdefault("concurrency", 1)
    cfg.setdefault("max_retries", 2)
    cfg.setdefault("max_consecutive_fail", 10)
    cfg.setdefault("rotate_ip", True)
    cfg.setdefault("db_path", "creds.db")
    cfg.setdefault("output_file", "accounts.txt")
    cfg.setdefault("browser", {"executable_path": "/usr/bin/chromium", "headless": True})
    cfg.setdefault("humanize", {"min_delay": 0.8, "max_delay": 2.5})
    cfg.setdefault("mail_tm", {"api_base": "https://api.mail.tm", "password": "TmP#Mail-2026x"})
    cfg.setdefault("tor", {"socks_port": 9050, "control_port": 9051,
                           "cookie_file": "/run/tor/control.authcookie"})
    return cfg


def read_account_file(path):
    """从账号文件读取 (username, password, email) 三元组。"""
    accounts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                accounts.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return accounts


def make_email_factory(proxy, mail_password):
    def factory(addr, pw):
        return MailTMClient(password=pw or mail_password, proxy=proxy)
    return factory


def resolve_network(cfg):
    """根据配置决定网络模式并执行切换。

    返回 (proxy, use_rotate_ip)：
      proxy          - 用于 Playwright/requests 的代理，None 表示直连
      use_rotate_ip  - 是否在每次注册前换 Tor IP
    """
    mode = cfg.get("network_mode", "tor")
    custom_proxy = cfg.get("proxy")  # 用户显式配置的外部代理（最高优先级）
    if custom_proxy:
        logger.info("使用外部代理: %s", custom_proxy)
        return custom_proxy, False

    if mode == "direct":
        logger.info("网络模式: DIRECT（关闭 iptables 透明代理，走本机 VPN/真实出口）")
        net_switch.enable_direct(
            torify_script=cfg.get("torify_script"),
            untorify_script=cfg.get("untorify_script"),
        )
        return None, False

    logger.info("网络模式: TOR（透明代理，匿名；注册页可能被 DataDome 拦截）")
    net_switch.enable_tor(
        torify_script=cfg.get("torify_script"),
        untorify_script=cfg.get("untorify_script"),
    )
    return "socks5://127.0.0.1:9050", True


def restore_network(cfg):
    """任务结束后按配置恢复网络。"""
    if cfg.get("restore_tor_after") and cfg.get("network_mode") == "direct" and not cfg.get("proxy"):
        logger.info("任务结束，恢复 Tor 透明代理…")
        net_switch.enable_tor(
            torify_script=cfg.get("torify_script"),
            untorify_script=cfg.get("untorify_script"),
        )


def register_account(cfg, registrar, gen, store, local_proxy=None):
    """注册一个账号并存入数据库。返回 (username, email, success)。

    local_proxy: 本账号粘滞的代理（邮箱链路与浏览器链路共用同一 IP）。
    """
    username = gen.username()
    password = gen.password()

    # 创建临时邮箱
    mail = MailTMClient(password=cfg["mail_tm"]["password"], proxy=local_proxy or cfg.get("proxy"))
    try:
        addr = mail.create_account()
        store.add_pending(username, password, addr)
        registrar.register(username, password, addr, mail.password)
        store.update_status(username, "registered")
        return (username, password, addr, True)
    except ChallengeDetected as e:
        store.update_status(username, "failed", note=str(e))
        logger.warning("风控拦截，放弃账号 %s", username)
        try:
            mail.delete_account()
        except Exception:
            pass
        return (username, password, addr, False)
    except Exception as e:
        store.update_status(username, "failed", note=str(e))
        logger.error("注册失败 %s: %s", username, e)
        try:
            mail.delete_account()
        except Exception:
            pass
        return (username, password, addr, False)


def star_with_account(cfg, booster, username, password, session_store=None, profile=None):
    """单个账号刷星。"""
    try:
        done = booster.run(username, password, cfg["target_repo"], session_store=session_store)
        return (username, True, "done" if done else "already_starred")
    except Exception as e:
        logger.error("刷星失败 %s: %s", username, e)
        return (username, False, str(e))


def mode_register_and_star(cfg):
    """模式 A：注册账号 → 刷星（每个 worker 线程自建浏览器，避免共享 Playwright 实例）。"""
    gen = AccountGenerator(cfg["password_suffix"])
    store = AccountStore(cfg["db_path"])
    proxy, use_rotate = resolve_network(cfg)
    tor = TorControl(port=cfg["tor"]["control_port"], cookie_file=cfg["tor"]["cookie_file"])
    session_store = SessionStore(cfg.get("session_dir", "sessions")) if cfg.get("session_dir") else None
    pool_manager = _build_proxy_pool(cfg)
    need = cfg["star_count"]
    done_count = 0
    workers = max(1, cfg.get("concurrency", 1))
    consecutive_fail = 0
    max_consecutive_fail = cfg.get("max_consecutive_fail", 10)

    def worker(_):
        """单个 worker：自建浏览器，注册一个号并刷星。返回 (ok, note)。"""
        if STOP["flag"]:
            return False, "stopped"
        local_proxy = _assign_proxy(cfg, pool_manager, proxy)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=cfg["browser"]["headless"],
                executable_path=cfg["browser"]["executable_path"],
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            email_factory = make_email_factory(local_proxy, cfg["mail_tm"]["password"])
            fp = make_fingerprint()
            registrar = Registrar(browser, email_factory, proxy=local_proxy,
                                  humanize=tuple(cfg["humanize"].values()), fingerprint=fp,
                                  max_retries=cfg.get("max_retries", 2))
            booster = StarBooster(browser, proxy=local_proxy,
                                  humanize=tuple(cfg["humanize"].values()), fingerprint=fp)
            try:
                uname, pw, addr, ok = register_account(cfg, registrar, gen, store, local_proxy=local_proxy)
                if not ok:
                    _mark_proxy_failed(pool_manager, local_proxy)
                    return False, "register_failed"
                # 注册后冷却（养号第一步）
                if cfg.get("cooldown_after_register"):
                    cmin, cmax = cfg.get("cooldown_seconds", [10, 30])
                    time.sleep(random.uniform(cmin, cmax))
                st_ok, note = star_with_account(cfg, booster, uname, pw, session_store=session_store)[1:3]
                if st_ok:
                    store.mark_starred(uname)
                    return True, "starred"
                store.update_status(uname, "star_failed", note=note)
                _mark_proxy_failed(pool_manager, local_proxy)
                return False, note
            finally:
                browser.close()

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        while done_count < need:
            if STOP["flag"]:
                logger.warning("检测到停止信号，结束循环")
                break
            if use_rotate and cfg.get("rotate_ip", True):
                tor.new_identity(wait=2)
            batch = list(pool.map(worker, range(min(workers, need - done_count))))
            results = [r for r in batch if r is not None]
            for ok, note in results:
                if note == "stopped":
                    continue
                if ok:
                    done_count += 1
                    logger.info("进度: %d/%d star 完成", done_count, need)
                else:
                    consecutive_fail += 1
                    if consecutive_fail >= max_consecutive_fail:
                        logger.error("连续 %d 次失败（很可能被风控全量拦截），终止任务", max_consecutive_fail)
                        pool.shutdown(wait=False, cancel_futures=True)
                        store.export_txt(cfg["output_file"])
                        logger.info("任务结束。状态统计: %s", store.count_by_status())
                        restore_network(cfg)
                        return
                    logger.warning("注册/刷星失败: %s", note)

    store.export_txt(cfg["output_file"])
    logger.info("任务结束。状态统计: %s", store.count_by_status())
    restore_network(cfg)


def mode_existing_accounts(cfg, accounts):
    """模式 B：使用已有账号直接刷星（每个 worker 线程自建浏览器）。"""
    store = AccountStore(cfg["db_path"])
    proxy, use_rotate = resolve_network(cfg)
    proxy = cfg.get("proxy") or (proxy if use_rotate else None)
    if not proxy and use_rotate:
        proxy = "socks5://127.0.0.1:9050"
    pool_manager = _build_proxy_pool(cfg)
    session_store = SessionStore(cfg.get("session_dir", "sessions")) if cfg.get("session_dir") else None

    # 检查点续跑：跳过已 starred 的账号
    pending = []
    for uname, pw, email in accounts:
        existing = store.get(uname)
        if existing and existing["status"] == "starred":
            logger.info("跳过已完成账号: %s", uname)
            continue
        if existing and existing["status"] == "pending":
            # 数据库中已有记录，续跑
            store.add_pending(existing["username"], existing["password"], existing["email"])
        else:
            store.add_pending(uname, pw, email)
        pending.append((uname, pw, email))

    if not pending:
        logger.info("所有账号均已完成，无需续跑")
        store.export_txt(cfg["output_file"])
        return

    workers = max(1, cfg.get("concurrency", 1))

    def worker(acc):
        if STOP["flag"]:
            return (acc[0], False, "stopped")
        uname, pw = acc[0], acc[1]
        local_proxy = _assign_proxy(cfg, pool_manager, proxy, sticky_key=uname)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=cfg["browser"]["headless"],
                executable_path=cfg["browser"]["executable_path"],
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            try:
                fp = make_fingerprint()
                booster = StarBooster(browser, proxy=local_proxy,
                                      humanize=tuple(cfg["humanize"].values()), fingerprint=fp)
                return star_with_account(cfg, booster, uname, pw, session_store=session_store)
            finally:
                browser.close()

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(worker, pending))

    for uname, ok, note in results:
        if note == "stopped":
            continue
        if ok:
            store.mark_starred(uname)
        else:
            store.update_status(uname, "star_failed", note=note)
    store.export_txt(cfg["output_file"])
    logger.info("任务结束。状态统计: %s", store.count_by_status())
    restore_network(cfg)


def _build_proxy_pool(cfg):
    """根据配置构建代理池（若有代理文件）。"""
    pool_file = cfg.get("proxy_pool_file")
    if not pool_file or not os.path.exists(pool_file):
        return None
    proxies = load_proxies_from_file(pool_file)
    if not proxies:
        logger.warning("代理文件为空: %s", pool_file)
        return None
    logger.info("加载代理池: %d 个代理", len(proxies))
    return ProxyPool(proxies, check_url=cfg.get("proxy_pool_check_url", "https://api.ipify.org?format=json"))


def _assign_proxy(cfg, pool_manager, default_proxy, sticky_key=None):
    """从代理池分配代理；无池则用默认代理。"""
    if pool_manager:
        p = pool_manager.get(sticky_key=sticky_key)
        if p:
            return p
    return default_proxy


def _mark_proxy_failed(pool_manager, proxy_url):
    """标记代理失败（缺陷 #6：让 mark_failed 真正生效）。"""
    if pool_manager and proxy_url:
        pool_manager.mark_failed(proxy_url)


def main():
    parser = argparse.ArgumentParser(description="GitHub Star 刷取工具")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--accounts", help="已有账号文件（tsv: username\\tpassword\\temail），启用模式B")
    parser.add_argument("--repo", help="覆盖目标仓库 owner/repo")
    parser.add_argument("--count", type=int, help="覆盖刷星数量")
    parser.add_argument("--no-rotate", action="store_true", help="不换 Tor IP")
    parser.add_argument("--network", choices=["tor", "direct"], help="覆盖网络模式: tor 或 direct")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.repo:
        cfg["target_repo"] = args.repo
    if args.count:
        cfg["star_count"] = args.count
    if args.no_rotate:
        cfg["rotate_ip"] = False
    if args.network:
        cfg["network_mode"] = args.network
    _guard_network(cfg)

    if args.accounts:
        accounts = read_account_file(args.accounts)
        if not accounts:
            logger.error("账号文件为空或格式错误")
            sys.exit(1)
        logger.info("模式 B：使用 %d 个已有账号刷星 %s", len(accounts), cfg["target_repo"])
        mode_existing_accounts(cfg, accounts)
    else:
        logger.info("模式 A：注册新账号刷星 %s（注意：注册页受 DataDome 风控，Tor 出口很可能被拦）", cfg["target_repo"])
        mode_register_and_star(cfg)


if __name__ == "__main__":
    main()
