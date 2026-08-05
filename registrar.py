"""GitHub 账号注册器：使用 Playwright 自动化注册，支持代理池与风控检测。

注意：GitHub 的 /signup 页面受 DataDome 保护，对 Tor 出口 IP 几乎全部拦截。
建议使用住宅/数据中心代理池（见 config.yaml 的 proxy_pool 配置）。
"""

import logging
import random
import time

from playwright.sync_api import TimeoutError as PWTimeout

logger = logging.getLogger("star_farmer.registrar")


class ChallengeDetected(Exception):
    """DataDome 等风控验证被触发。"""


class Registrar:
    def __init__(self, browser, email_factory, proxy=None, humanize=(0.8, 2.5)):
        self.browser = browser
        self.email_factory = email_factory  # 返回 MailTMClient 的可调用对象
        self.proxy = proxy
        self.min_delay, self.max_delay = humanize

    def _delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _new_context(self):
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
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
            """
        )
        return ctx

    def _check_challenge(self, page):
        """检测 DataDome 风控。返回 True 表示被拦截。"""
        try:
            html = page.evaluate("document.documentElement.outerHTML")
            if "captcha-delivery" in html:
                return True
            for f in page.frames:
                if "captcha-delivery" in f.url:
                    return True
        except Exception:
            return False
        return False

    def register(self, username, password, email_addr, email_password):
        """注册一个 GitHub 账号。

        email_addr / email_password 是 mail.tm 临时邮箱的凭证。
        返回注册成功后的登录页状态；若触发风控则抛 ChallengeDetected。
        """
        ctx = self._new_context()
        page = ctx.new_page()
        try:
            page.goto("https://github.com/signup", timeout=60000)
            page.wait_for_timeout(4000)

            if self._check_challenge(page):
                raise ChallengeDetected("注册页被 DataDome 拦截")

            # --- 第一步：邮箱 ---
            email_input = page.locator("#email")
            email_input.wait_for(state="visible", timeout=30000)
            email_input.fill(email_addr)
            self._delay()
            page.keyboard.press("Enter")
            page.wait_for_timeout(2500)

            # --- 第二步：密码 ---
            pw = page.locator("#password")
            pw.wait_for(state="visible", timeout=20000)
            pw.fill(password)
            self._delay()
            page.keyboard.press("Enter")
            page.wait_for_timeout(2500)

            # --- 第三步：用户名 ---
            user = page.locator("#login")
            user.wait_for(state="visible", timeout=20000)
            user.fill(username)
            self._delay()
            page.keyboard.press("Enter")
            page.wait_for_timeout(2500)

            # --- 第四步：邮箱验证码 ---
            # 从临时邮箱获取 GitHub 验证码
            code, _ = self.email_factory(email_addr, email_password).get_github_code(timeout=180)
            if not code:
                raise RuntimeError("未从邮件中提取到验证码")

            code_input = page.locator(
                "input[inputmode='numeric'], #verification-code, input[name='verification_code'], input[autocomplete='one-time-code']"
            ).first
            code_input.wait_for(state="visible", timeout=20000)
            code_input.fill(code)
            self._delay()
            page.keyboard.press("Enter")

            # 等待注册完成跳转
            try:
                page.wait_for_url("https://github.com/**", timeout=60000)
            except PWTimeout:
                pass
            page.wait_for_timeout(4000)

            # 若仍停留在注册页且出现错误，抛出异常
            if "/signup" in page.url:
                body = page.inner_text("body")[:300]
                raise RuntimeError(f"注册未完成，页面: {body}")

            logger.info("注册成功: %s (%s)", username, email_addr)
            return True
        finally:
            ctx.close()
