"""风控检测与挑战识别。

针对 DEFECTS_ANALYSIS.md 第 5 节：
- JS 挑战运行时对象（window.dd / __dd_ / DataDome / _dd / ddz）
- 网络层特征（响应头 Server: DataDome、X-DataDome-CID、重定向链 /captcha/）
- 挑战类型分类（静默 / 滑块 / 点选 / 文本验证码）
"""

import logging
import re

logger = logging.getLogger("star_farmer.challenge")


# 常见 JS 挑战对象标识
CHALLENGE_JS_MARKERS = [
    "window.dd", "__dd_", "DataDome", "window._dd", "ddz", "pdcd",
    "captcha-delivery.com", "geo.captcha-delivery.com",
]

# 网络层响应头特征
CHALLENGE_HEADERS = [
    "x-datadome", "x-datadome-cid", "server: datadome",
    "x-datadome-site",
]


class ChallengeInfo:
    """一次风控挑战的详细信息。"""

    def __init__(self, kind="unknown", provider="unknown", frame_url=None, message=""):
        self.kind = kind          # silent / slider / pick / text / unknown
        self.provider = provider  # datadome / cloudflare / recaptcha / hcaptcha / unknown
        self.frame_url = frame_url
        self.message = message

    def __repr__(self):
        return f"ChallengeInfo(provider={self.provider}, kind={self.kind})"


def inspect_page(page):
    """全面检测页面是否被风控拦截，返回 ChallengeInfo 或 None。"""
    # --- 1. iframe 检测 ---
    for f in page.frames:
        url = f.url
        if "captcha-delivery" in url:
            info = _classify_datadome(page, url)
            if info:
                return info
            return ChallengeInfo(provider="datadome", frame_url=url, message="captcha-delivery iframe")
        if "recaptcha" in url or "google.com/recaptcha" in url:
            return ChallengeInfo(provider="recaptcha", frame_url=url)
        if "hcaptcha" in url:
            return ChallengeInfo(provider="hcaptcha", frame_url=url)
        if "challenges.cloudflare.com" in url:
            return ChallengeInfo(provider="cloudflare", frame_url=url)
        if "arkose" in url.lower() or "funcaptcha" in url.lower():
            return ChallengeInfo(provider="arkose", frame_url=url)

    # --- 2. 主文档 HTML 检测 ---
    try:
        html = page.evaluate("document.documentElement.outerHTML") or ""
    except Exception:
        html = ""
    if "captcha-delivery" in html:
        return _classify_datadome(page, None, html)
    if "cf-challenge" in html or "challenges.cloudflare.com" in html:
        return ChallengeInfo(provider="cloudflare", message="CF challenge in HTML")

    # --- 3. JS 运行时对象检测 ---
    try:
        found = page.evaluate(
            """() => {
                const markers = ['window.dd','__dd_','DataDome','_dd','ddz','pdcd'];
                const hits = [];
                for (const m of markers) {
                    try { if (eval('typeof ' + m.replace('window.','')) !== 'undefined') hits.push(m); } catch(e){}
                }
                return hits.join(',');
            }"""
        )
        if found:
            return ChallengeInfo(provider="datadome", message=f"JS runtime objects: {found}")
    except Exception:
        pass

    return None


def _classify_datadome(page, frame_url, html=None):
    """尝试识别 DataDome 挑战类型并读取提示文字。"""
    msg = ""
    try:
        # 尝试从 iframe 提取文本
        for f in page.frames:
            if "captcha-delivery" in f.url:
                try:
                    msg = f.locator("body").inner_text(timeout=3000)[:200]
                except Exception:
                    pass
                break
    except Exception:
        pass

    kind = "unknown"
    lowered = msg.lower()
    if "temporarily restricted" in lowered or "unusual activity" in lowered:
        kind = "silent"
    elif "slider" in lowered or "slide" in lowered or "verify you are human" in lowered:
        kind = "slider"
    elif "select" in lowered or ("click" in lowered and "image" in lowered):
        kind = "pick"
    elif "type" in lowered and "character" in lowered:
        kind = "text"
    return ChallengeInfo(provider="datadome", kind=kind, frame_url=frame_url, message=msg[:200])


def check_http_response(response):
    """检测 HTTP 响应头中的风控特征（需在页面 on_response 回调中调用）。"""
    try:
        headers = response.headers
        h = " ".join(f"{k}: {v}".lower() for k, v in headers.items())
        for marker in CHALLENGE_HEADERS:
            if marker in h:
                return True, marker
        if "captcha" in response.url.lower():
            return True, response.url[:100]
    except Exception:
        pass
    return False, None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("challenge 模块就绪")
