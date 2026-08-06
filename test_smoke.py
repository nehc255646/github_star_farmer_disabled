"""基础冒烟测试（无网络依赖，仅验证核心逻辑）。

用法：
    python test_smoke.py
"""

import logging
import sys

logging.basicConfig(level=logging.ERROR)

FAIL = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    if not cond:
        FAIL.append(name)


def test_account():
    from account import AccountGenerator
    gen = AccountGenerator()
    u = gen.username()
    check("用户名格式", 3 <= len(u) <= 39 and u[0].isalpha())
    p = gen.password()
    check("密码长度>=16", len(p) >= 16)
    check("密码不含固定共享后缀", "GitHub#2026" not in p or len(p) > len("GitHub#2026"))
    prof = gen.profile()
    check("Profile 有 name/bio", all(prof.get(k) for k in ("name", "bio", "location")))


def test_proxy_pool():
    from proxy_pool import ProxyPool
    pool = ProxyPool(["http://127.0.0.1:1", "socks5://127.0.0.1:9050"])
    p1 = pool.get(sticky_key="userA")
    p2 = pool.get(sticky_key="userA")
    check("粘滞同 key 同代理", p1 == p2)
    check("统计接口", pool.stats()["total"] == 2)


def test_session_path():
    from session_store import SessionStore
    s = SessionStore("sessions_test")
    path1 = s._path("../evil")
    check("路径穿越防护", "sessions_test" in path1 and ".." not in path1)
    path2 = s._path("normal_user")
    check("正常用户路径", path2.endswith("normal_user.json"))
    import shutil
    shutil.rmtree("sessions_test", ignore_errors=True)


def test_slider_offset():
    from slider import _iframe_offset
    # 无浏览器时返回 0,0（不崩溃）
    class _FakePage:
        def locator(self, sel):
            class _L:
                def all(self):
                    return []
            return _L()
    class _FakeFrame:
        url = "https://geo.captcha-delivery.com/captcha/"
    x, y = _iframe_offset(_FakePage(), _FakeFrame())
    check("iframe 偏移兜底", x == 0 and y == 0)


def test_browser_api():
    from browser_api import sync_playwright, engine
    check("浏览器引擎已加载", engine() in ("patchright", "playwright"))


def test_humanize():
    from humanize import lognormal_delay, bezier_curve
    d = lognormal_delay()
    check("延迟范围", 0.15 <= d <= 6.0)
    pts = bezier_curve((0, 0), (50, 80), (100, -20), (200, 0), 10)
    check("贝塞尔点数", len(pts) == 11)


def test_challenge():
    from challenge import ChallengeInfo
    c = ChallengeInfo(provider="datadome", kind="slider")
    check("挑战类型", c.kind == "slider")


def test_stealth():
    from stealth import make_fingerprint
    fp = make_fingerprint()
    check("指纹有 UA", "Chrome/" in fp["user_agent"])
    check("指纹有 WebGL", fp["webgl_renderer"])


def test_network_module():
    import network
    check("网络模块可导入", callable(network.enable_direct))


def main():
    print("=== GitHub Star 工具冒烟测试 ===")
    for fn in [test_account, test_proxy_pool, test_session_path, test_slider_offset,
               test_browser_api, test_humanize, test_challenge, test_stealth, test_network_module]:
        try:
            fn()
        except Exception as e:
            check(f"{fn.__name__} 异常", False)
            print(f"      异常: {type(e).__name__}: {e}")
    print()
    if FAIL:
        print(f"结果: {len(FAIL)} 项失败 -> {FAIL}")
        sys.exit(1)
    print("结果: 全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
