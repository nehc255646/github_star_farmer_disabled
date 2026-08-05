"""Star 刷取模块：登录 GitHub 账号后，为目标仓库点击 Star。"""

import logging
import random
import time

from playwright.sync_api import TimeoutError as PWTimeout

logger = logging.getLogger("star_farmer.star")


class StarBooster:
    """使用 Playwright 登录并刷 Star。"""

    def __init__(self, browser, proxy=None, humanize=(0.8, 2.5)):
        self.browser = browser
        self.proxy = proxy
        self.min_delay, self.max_delay = humanize

    def _delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _new_context(self, username):
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        ctx_opts = {
            "locale": "en-US",
            "viewport": {"width": 1366, "height": 900},
            "user_agent": ua,
        }
        if self.proxy:
            ctx_opts["proxy"] = {"server": self.proxy}
        ctx = self.browser.new_context(**ctx_opts)
        ctx.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            """
        )
        return ctx

    def login(self, page, username, password):
        """登录 GitHub。"""
        page.goto("https://github.com/login", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        page.fill("#login_field", username)
        self._delay()
        page.fill("#password", password)
        self._delay()
        page.click("input[type='submit'][name='commit']")
        # 等待登录跳转
        try:
            page.wait_for_url("https://github.com/**", timeout=45000)
        except PWTimeout:
            pass
        page.wait_for_timeout(3000)
        if "/login" in page.url or "Incorrect username or password" in page.content():
            raise RuntimeError(f"登录失败: {username}")
        logger.info("登录成功: %s", username)

    def star_repo(self, page, owner_repo):
        """打开目标仓库并点击 Star。返回 True=已成功 star，False=已经 star 过。"""
        page.goto(f"https://github.com/{owner_repo}", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        # 定位 Star 按钮（多种形式）
        star_btn = None
        selectors = [
            f'a[href="/{owner_repo}/stargazers"]',
            'a[aria-label*="star" i]',
            'button[aria-label*="star" i]',
            '[data-hotkey="g s"]',
            'a:has-text("Star")',
            'button:has-text("Star")',
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if loc.is_visible(timeout=2000):
                    star_btn = loc
                    break
            except PWTimeout:
                continue

        if star_btn is None:
            raise RuntimeError(f"未找到 Star 按钮: {owner_repo}")

        label = (star_btn.get_attribute("aria-label") or "") + " " + (star_btn.inner_text() or "")
        if "unstar" in label.lower() or "Starred" in label or "starred" in label.lower():
            logger.info("该账号已经 star 过: %s", owner_repo)
            return False

        # 点击 Star
        star_btn.click()
        self._delay()
        page.wait_for_timeout(2500)

        # 校验：按钮 aria/文本应变为 Unstar / Starred
        try:
            new_label = (star_btn.get_attribute("aria-label") or "") + " " + (star_btn.inner_text() or "")
            if "unstar" in new_label.lower() or "starred" in new_label.lower():
                logger.info("Star 成功 ✓")
                return True
        except Exception:
            pass
        logger.info("Star 已点击（状态待确认）")
        return True

    def run(self, username, password, owner_repo):
        """完整流程：登录 → star → 返回结果。"""
        ctx = self._new_context(username)
        page = ctx.new_page()
        try:
            self.login(page, username, password)
            return self.star_repo(page, owner_repo)
        finally:
            ctx.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print("StarBooster 模块就绪")
