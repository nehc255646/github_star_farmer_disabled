"""Tor 出口批量轮换探测：寻找 DataDome 未拦截的"干净"出口。

思路：Tor 有几千个出口节点，大部分被 DataDome 标记，但少数民用节点
转的出口信誉可能较好。用 NEWNYM 不断换出口，快速检测 signup 页是否
被拦截，撞到干净出口就停止并报告。

用法：
    python tor_sweep.py --max 30          # 最多试 30 个出口
    python tor_sweep.py --max 30 --once   # 每个出口只判断一次
"""

import argparse
import logging
import sys
import time

from patchright.sync_api import sync_playwright
from stealth import install_stealth, make_fingerprint
from tor_control import TorControl, get_public_ip

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tor_sweep")


def check_one_exit(browser, proxy="socks5://127.0.0.1:9050", timeout=15):
    """在当前 Tor 出口下快速检测 signup 页状态。

    返回 (status, detail)：
      status: "ok"(表单渲染) / "slider"(滑块挑战) / "blocked"(静默拦截) / "error"
    """
    fp = make_fingerprint()
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
    ctx = browser.new_context(locale="en-US", user_agent=fp["user_agent"],
                              proxy={"server": proxy})
    install_stealth(ctx, fp)
    pg = ctx.new_page()
    try:
        pg.goto("https://github.com/signup", timeout=timeout * 1000)
        pg.wait_for_timeout(8000)
        html = pg.evaluate("document.documentElement.outerHTML")
        n_inputs = pg.locator("input:visible").count()
        if n_inputs > 0:
            return "ok", f"表单渲染 inputs={n_inputs}"
        # 检查是否有滑块
        for fr in pg.frames:
            if "captcha-delivery" in fr.url:
                try:
                    body = fr.locator("body").inner_text(timeout=2000).lower()
                    if "slide right" in body or "slider" in body:
                        return "slider", "DataDome 滑块挑战（可交互！）"
                except Exception:
                    pass
                return "blocked", "DataDome 静默拦截"
        if "captcha-delivery" in html:
            return "blocked", "DataDome 拦截(HTML)"
        return "unknown", "页面状态未知"
    except Exception as e:
        return "error", str(e)[:80]
    finally:
        ctx.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=30, help="最多探测的出口数")
    parser.add_argument("--wait", type=int, default=6, help="NEWNYM 后等待秒数")
    args = parser.parse_args()

    tor = TorControl()
    results = {"ok": 0, "slider": 0, "blocked": 0, "error": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        for i in range(args.max):
            tor.new_identity(wait=args.wait)
            ip = get_public_ip()
            status, detail = check_one_exit(browser)
            results[status] = results.get(status, 0) + 1
            logger.info("[%d/%d] exit=%s status=%s detail=%s", i + 1, args.max, ip, status, detail)
            if status == "ok":
                logger.info("*** 找到干净出口！exit=%s ***", ip)
                break
            if status == "slider":
                logger.info("*** 找到滑块出口！exit=%s（滑块可尝试自动解）***", ip)
                break
        browser.close()

    logger.info("探测统计: %s", results)
    sys.exit(0)


if __name__ == "__main__":
    main()
