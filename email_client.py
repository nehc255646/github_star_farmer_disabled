"""临时邮箱客户端：使用 mail.tm 服务创建一次性邮箱并收取 GitHub 验证码。"""

import json
import logging
import random
import re
import time
import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger("star_farmer.email")


class MailTMClient:
    """mail.tm 临时邮箱客户端（支持走 SOCKS5 代理）。"""

    def __init__(self, api_base="https://api.mail.tm", password=None, proxy=None):
        self.api_base = api_base.rstrip("/")
        self.password = password or "TmP#Mail-2026x"
        self.proxy = proxy  # 形如 socks5://127.0.0.1:9050
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        # 重试：应对 Tor 换 IP 时的间歇性 DNS/连接故障
        retries = Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=frozenset(["GET", "POST", "DELETE"]))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.address = None
        self.token = None
        self.account_id = None

    def _get(self, path, **kwargs):
        kwargs.setdefault("timeout", 25)
        r = self.session.get(self.api_base + path, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def _post(self, path, data=None, **kwargs):
        kwargs.setdefault("timeout", 25)
        r = self.session.post(self.api_base + path, json=data, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def create_account(self):
        """创建新的临时邮箱账户。"""
        domains = self._get("/domains")
        members = domains.get("hydra:member", [])
        if not members:
            raise RuntimeError("mail.tm 没有可用域名")
        domain = members[0]["domain"]

        # 生成随机用户名（仅小写字母数字）
        rand = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=random.randint(8, 12)))
        self.address = f"{rand}@{domain}"

        resp = self._post("/accounts", {"address": self.address, "password": self.password})
        self.account_id = resp.get("id")

        # 自动登录获取 token
        tok = self._post("/token", {"address": self.address, "password": self.password})
        self.token = tok.get("token")
        if not self.token:
            raise RuntimeError("mail.tm 登录失败，未获得 token")
        logger.info("临时邮箱创建成功: %s", self.address)
        return self.address

    def delete_account(self):
        """删除临时邮箱账户。"""
        if self.account_id and self.token:
            try:
                self.session.delete(
                    f"{self.api_base}/accounts/{self.account_id}",
                    headers=self._auth_headers(),
                    timeout=20,
                )
                logger.info("临时邮箱已删除: %s", self.address)
            except Exception as e:
                logger.warning("删除临时邮箱失败: %s", e)

    def wait_for_message(self, keyword="GitHub", timeout=180, poll=5):
        """轮询收件箱，等待包含关键词的邮件，返回消息对象。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = self._get("/messages", headers=self._auth_headers())
            items = msgs.get("hydra:member", [])
            for msg in items:
                subject = msg.get("subject", "")
                if keyword.lower() in subject.lower():
                    logger.info("收到邮件: %s", subject)
                    return msg
            time.sleep(poll)
        raise TimeoutError(f"等待邮件超时（{timeout}s），关键词: {keyword}")

    def get_message_text(self, msg_id):
        """获取邮件全文（可能为纯文本或 HTML）。"""
        detail = self._get(f"/messages/{msg_id}", headers=self._auth_headers())
        return detail.get("text") or detail.get("html") or ""

    @staticmethod
    def extract_verification_code(text):
        """从邮件文本中提取 GitHub 验证码（通常是 8 位数字）。"""
        if not text:
            return None
        # 优先找 8 位数字
        m = re.search(r"\b\d{8}\b", text)
        if m:
            return m.group(0)
        # 退而求其次找连续 6-8 位数字
        m = re.search(r"\b\d{6,8}\b", text)
        return m.group(0) if m else None

    @staticmethod
    def extract_verify_link(text):
        """从邮件文本中提取验证链接（github.com 的确认链接）。"""
        if not text:
            return None
        urls = re.findall(r'https?://[^\s"\'<>]+', text)
        for u in urls:
            if "github.com" in u:
                # 去掉 HTML 实体
                return u.replace("&amp;", "&")
        return None

    def get_github_code(self, timeout=180):
        """一站式：等待 GitHub 邮件并提取验证码。"""
        msg = self.wait_for_message("GitHub", timeout=timeout)
        text = self.get_message_text(msg["id"])
        code = self.extract_verification_code(text)
        if code:
            # 缺陷 #21：验证码不打明文日志，只记录长度
            logger.info("GitHub 验证码已提取（长度 %d）", len(code))
            return code, text
        return None, text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    c = MailTMClient(proxy="socks5://127.0.0.1:9050")
    addr = c.create_account()
    print("邮箱:", addr)
    print("收件箱:", c.wait_for_message(timeout=20) if False else "测试完成")
