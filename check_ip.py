"""出口 IP 与 GitHub 注册页连通性检测。

用法（切换网络后运行）：
    python check_ip.py
    python check_ip.py --probe   # 额外探测 GitHub 注册页是否被 DataDome 拦截
"""

import argparse
import logging
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("check_ip")


def get_ip(timeout=20):
    try:
        r = requests.get("https://check.torproject.org/api/ip", timeout=timeout)
        d = r.json()
        return {"ip": d.get("IP"), "is_tor": bool(d.get("IsTor"))}
    except Exception as e:
        logger.error("IP 检测失败: %s", e)
        return {"ip": None, "is_tor": None}


def get_ipinfo(ip, timeout=20):
    try:
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=timeout)
        d = r.json()
        return f"{d.get('city', '?')}, {d.get('country', '?')} | {d.get('org', '?')}"
    except Exception as e:
        return f"(ipinfo 失败: {str(e)[:60]})"


def probe_signup(timeout=45):
    """探测 GitHub 注册页是否被 DataDome 拦截。

    返回字符串描述。需要本机可用的浏览器引擎（chromium）。
    """
    try:
        from patchright.sync_api import sync_playwright
        from stealth import install_stealth, make_fingerprint
    except ImportError:
        return "未安装 patchright/stealth，跳过浏览器探测"

    fp = make_fingerprint()
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=args)
        ctx = b.new_context(locale="en-US", user_agent=fp["user_agent"])
        install_stealth(ctx, fp)
        pg = ctx.new_page()
        try:
            pg.goto("https://github.com/signup", timeout=timeout * 1000)
        except Exception as e:
            b.close()
            return f"页面打不开: {str(e)[:80]}"
        pg.wait_for_timeout(6000)
        try:
            html = pg.evaluate("document.documentElement.outerHTML")
        except Exception as e:
            b.close()
            return f"页面状态异常（可能在挑战页）: {str(e)[:60]}"
        has_dd = "captcha-delivery" in html
        n_inputs = pg.locator("input:visible").count()
        # 读取 iframe 提示
        msg = ""
        for fr in pg.frames:
            if "captcha-delivery" in fr.url:
                try:
                    msg = fr.locator("body").inner_text(timeout=3000)[:150].replace("\n", " | ")
                except Exception:
                    pass
        b.close()
        if n_inputs > 0:
            return f"✅ 注册页正常渲染! inputs={n_inputs}"
        if has_dd:
            return f"❌ DataDome 拦截: {msg or '静默挑战'}"
        return f"⚠️ 未知状态 (captcha={has_dd}, inputs={n_inputs})"


def main():
    parser = argparse.ArgumentParser(description="出口 IP 与注册页连通性检测")
    parser.add_argument("--probe", action="store_true", help="探测 GitHub 注册页是否被拦截")
    args = parser.parse_args()

    logger.info("检测当前出口 IP…")
    info = get_ip()
    if not info["ip"]:
        logger.error("无法获取出口 IP，请检查网络")
        sys.exit(1)
    ipinfo = get_ipinfo(info["ip"])
    logger.info("出口 IP: %s  (%s)", info["ip"], ipinfo)
    logger.info("是否 Tor: %s", "是" if info["is_tor"] else "否")

    if args.probe:
        logger.info("探测 GitHub 注册页…")
        time.sleep(1)
        result = probe_signup()
        logger.info("结果: %s", result)


if __name__ == "__main__":
    main()
