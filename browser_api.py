"""浏览器 API 统一入口。

优先使用 patchright（对抗 CDP 检测的 Playwright 分支，过 DataDome 关键），
未安装时降级到 playwright 并给出警告。

用法：
    from browser_api import sync_playwright, TimeoutError
"""

import logging

logger = logging.getLogger("star_farmer.browser")

try:
    from patchright.sync_api import sync_playwright
    from patchright.sync_api import TimeoutError
    _ENGINE = "patchright"
except ImportError:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError
    _ENGINE = "playwright"
    logger.warning("未安装 patchright，降级使用 playwright（CDP 反检测缺失，可能被风控识别）")


def engine():
    """返回当前使用的浏览器驱动名。"""
    return _ENGINE


__all__ = ["sync_playwright", "TimeoutError", "engine"]
