"""GitHub Star 刷取工具 - 主入口。

用法:
    python main.py --config config.yaml
    python main.py --accounts accounts.txt --repo owner/repo   # 已有账号直接刷星
"""

import argparse
import concurrent.futures as cf
import logging
import random
import sys
import time

import yaml
from playwright.sync_api import sync_playwright

from account import AccountGenerator, AccountStore
from email_client import MailTMClient
from registrar import ChallengeDetected, Registrar
from star_booster import StarBooster
from tor_control import TorControl, get_public_ip
import network as net_switch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("star_farmer.main")


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


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
        net_switch.enable_direct()
        return None, False

    logger.info("网络模式: TOR（透明代理，匿名；注册页可能被 DataDome 拦截）")
    net_switch.enable_tor()
    return "socks5://127.0.0.1:9050", True


def restore_network(cfg):
    """任务结束后按配置恢复网络。"""
    if cfg.get("restore_tor_after") and cfg.get("network_mode") == "direct" and not cfg.get("proxy"):
        logger.info("任务结束，恢复 Tor 透明代理…")
        net_switch.enable_tor()


def register_account(cfg, registrar, gen, store):
    """注册一个账号并存入数据库。返回 (username, email, success)。"""
    username = gen.username()
    password = gen.password()

    # 创建临时邮箱
    mail = MailTMClient(password=cfg["mail_tm"]["password"], proxy=cfg.get("proxy"))
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


def star_with_account(cfg, booster, username, password):
    """单个账号刷星。"""
    try:
        done = booster.run(username, password, cfg["target_repo"])
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
    need = cfg["star_count"]
    done_count = 0
    workers = max(1, cfg.get("concurrency", 1))
    consecutive_fail = 0
    max_consecutive_fail = cfg.get("max_consecutive_fail", 10)

    def worker(_):
        """单个 worker：自建浏览器，注册一个号并刷星。返回 (ok, note)。"""
        local_proxy = proxy
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=cfg["browser"]["headless"],
                executable_path=cfg["browser"]["executable_path"],
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            email_factory = make_email_factory(local_proxy, cfg["mail_tm"]["password"])
            registrar = Registrar(browser, email_factory, proxy=local_proxy, humanize=tuple(cfg["humanize"].values()))
            booster = StarBooster(browser, proxy=local_proxy, humanize=tuple(cfg["humanize"].values()))
            try:
                uname, pw, addr, ok = register_account(cfg, registrar, gen, store)
                if not ok:
                    return False, "register_failed"
                st_ok, note = star_with_account(cfg, booster, uname, pw)[1:3]
                if st_ok:
                    store.mark_starred(uname)
                    return True, "starred"
                store.update_status(uname, "star_failed", note=note)
                return False, note
            finally:
                browser.close()

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        while done_count < need:
            if use_rotate and cfg.get("rotate_ip", True):
                tor.new_identity(wait=2)
            results = list(pool.map(worker, range(min(workers, need - done_count))))
            for ok, note in results:
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
    for uname, pw, _ in accounts:
        store.add_pending(uname, pw, "")

    workers = max(1, cfg.get("concurrency", 1))

    def worker(acc):
        uname, pw = acc[0], acc[1]
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=cfg["browser"]["headless"],
                executable_path=cfg["browser"]["executable_path"],
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            try:
                booster = StarBooster(browser, proxy=proxy, humanize=tuple(cfg["humanize"].values()))
                return star_with_account(cfg, booster, uname, pw)
            finally:
                browser.close()

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(worker, accounts))

    for uname, ok, note in results:
        if ok:
            store.mark_starred(uname)
        else:
            store.update_status(uname, "star_failed", note=note)
    store.export_txt(cfg["output_file"])
    logger.info("任务结束。状态统计: %s", store.count_by_status())
    restore_network(cfg)


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
