"""GitHub 账号注册器：使用 Playwright 自动化注册，支持代理池与风控检测。

集成：
- stealth 指纹对抗（Canvas/WebGL/Audio/Fonts/UA 等）
- humanize 人类化行为（贝塞尔鼠标、打字、悬停）
- challenge 增强风控检测（JS 对象、响应头、挑战分类）
- session_store 会话持久化（Cookie 复用）
"""

import logging
import random
import time

from playwright.sync_api import TimeoutError as PWTimeout

from challenge import ChallengeInfo, inspect_page
from humanize import human_hover_click, human_mouse_move, human_type, human_pause, lognormal_delay
from stealth import install_stealth, make_fingerprint
from slider import solve_datadome_slider, is_slider_present

logger = logging.getLogger("star_farmer.registrar")


class ChallengeDetected(Exception):
    """DataDome 等风控验证被触发。"""

    def __init__(self, info: ChallengeInfo = None, message="风控挑战被触发"):
        super().__init__(message)
        self.info = info


class Registrar:
    def __init__(self, browser, email_factory, proxy=None, humanize=(0.8, 2.5), fingerprint=None):
        self.browser = browser
        self.email_factory = email_factory  # 返回 MailTMClient 的可调用对象
        self.proxy = proxy
        self.min_delay, self.max_delay = humanize
        self.fingerprint = fingerprint

    def _delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _new_context(self):
        # 指纹（若未指定则生成一套，保持一致性）
        if not self.fingerprint:
            self.fingerprint = make_fingerprint()
        ua = self.fingerprint.get("user_agent")
        ctx_opts = {
            "locale": "en-US",
            "viewport": {"width": self.fingerprint.get("screen_size", (1366, 900))[0],
                         "height": self.fingerprint.get("screen_size", (1366, 900))[1]},
            "user_agent": ua,
        }
        if self.proxy:
            ctx_opts["proxy"] = {"server": self.proxy}
        ctx = self.browser.new_context(**ctx_opts)
        # 完整指纹注入
        install_stealth(ctx, self.fingerprint)
        return ctx

    def _check_challenge(self, page):
        """增强风控检测。返回 ChallengeInfo 或 None。"""
        info = inspect_page(page)
        if info:
            logger.warning("风控挑战: %s", info)
        return info

    def _handle_challenge(self, page, info):
        """处理风控挑战：滑块自动解，其他类型抛异常。返回 True=已解决可继续。"""
        # 若页面存在滑块，尝试自动解决
        try:
            has_slider = any(
                "captcha-delivery" in fr.url and is_slider_present(fr)
                for fr in page.frames
            )
            if has_slider:
                logger.info("检测到 DataDome 滑块，尝试自动解决…")
                ok = solve_datadome_slider(page, wait_after=8)
                if ok:
                    # 解决后重新检查是否还有风控
                    after = self._check_challenge(page)
                    if not after:
                        logger.info("滑块解决成功，继续注册")
                        return True
                    logger.warning("滑块已解决但仍存在风控: %s", after)
        except Exception as e:
            logger.warning("滑块解决异常: %s", e)
        raise ChallengeDetected(info=info, message="风控挑战无法自动解决")

    def register(self, username, password, email_addr, email_password):
        """注册一个 GitHub 账号。

        email_addr / email_password 是 mail.tm 临时邮箱的凭证。
        返回注册成功后的登录页状态；若触发风控则抛 ChallengeDetected。
        """
        ctx = self._new_context()
        page = ctx.new_page()
        # 网络层风控检测
        challenge_header = {"hit": False}

        def _on_response(resp):
            try:
                if "captcha" in resp.url.lower() or "datadome" in str(resp.headers).lower():
                    challenge_header["hit"] = True
            except Exception:
                pass

        page.on("response", _on_response)
        try:
            page.goto("https://github.com/signup", timeout=60000)
            page.wait_for_timeout(5000)

            info = self._check_challenge(page)
            if info or challenge_header["hit"]:
                self._handle_challenge(page, info)

            # --- 第一步：邮箱 ---
            email_input = page.locator("#email")
            email_input.wait_for(state="visible", timeout=30000)
            human_type(page, "#email", email_addr)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)

            after_email = self._check_challenge(page)
            if after_email:
                self._handle_challenge(page, after_email)

            # --- 第二步：密码 ---
            pw = page.locator("#password")
            pw.wait_for(state="visible", timeout=20000)
            human_type(page, "#password", password)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)

            # --- 第三步：用户名 ---
            user = page.locator("#login")
            user.wait_for(state="visible", timeout=20000)
            human_type(page, "#login", username)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)

            # --- 第四步：邮箱验证码 ---
            # 从临时邮箱获取 GitHub 验证码
            code, _ = self.email_factory(email_addr, email_password).get_github_code(timeout=180)
            if not code:
                raise RuntimeError("未从邮件中提取到验证码")

            code_input = page.locator(
                "input[inputmode='numeric'], #verification-code, input[name='verification_code'], input[autocomplete='one-time-code']"
            ).first
            code_input.wait_for(state="visible", timeout=20000)
            human_type(page, code_input, code)
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
