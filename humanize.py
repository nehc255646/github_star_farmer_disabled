"""人类化行为模拟。

针对 DEFECTS_ANALYSIS.md 第 2 节：
- 贝塞尔曲线鼠标轨迹（含加速/减速/抖动）
- 人类化键盘输入（逐字符、随机间隔、偶尔回删）
- 悬停后点击
- 页面探索（滚动、停留、焦点切换）
- 对数正态分布延迟（符合韦伯-费希纳定律）
"""

import logging
import math
import random
import time

logger = logging.getLogger("star_farmer.humanize")


def lognormal_delay(mean=1.2, sigma=0.6, min_d=0.15, max_d=6.0):
    """对数正态分布延迟（秒），模拟人类反应时间。"""
    d = random.lognormvariate(math.log(mean), sigma)
    return min(max(d, min_d), max_d)


def bezier_curve(p0, p1, p2, p3, steps):
    """三次贝塞尔曲线插值点。"""
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t**2*p2[0] + t**3*p3[0]
        y = (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t**2*p2[1] + t**3*p3[1]
        points.append((x, y))
    return points


def human_mouse_move(page, x, y, rng=None):
    """模拟人类鼠标轨迹移动到 (x, y)。"""
    rng = rng or random
    try:
        start = page.mouse.position or (rng.randint(200, 800), rng.randint(200, 500))
    except Exception:
        start = (rng.randint(200, 800), rng.randint(200, 500))

    # 控制点随机偏移，制造曲线
    dx = x - start[0]
    dy = y - start[1]
    dist = math.hypot(dx, dy)
    c1 = (start[0] + dx*rng.uniform(0.2, 0.4) + rng.uniform(-40, 40),
          start[1] + dy*rng.uniform(0.2, 0.4) + rng.uniform(-40, 40))
    c2 = (start[0] + dx*rng.uniform(0.6, 0.8) + rng.uniform(-40, 40),
          start[1] + dy*rng.uniform(0.6, 0.8) + rng.uniform(-40, 40))
    end = (x + rng.uniform(-2, 2), y + rng.uniform(-2, 2))

    steps = max(8, min(int(dist / 6), 60))
    points = bezier_curve(start, c1, c2, end, steps)

    # 模拟人类速度：先快后慢（接近目标减速）
    for i, (px, py) in enumerate(points):
        page.mouse.move(px, py)
        progress = i / steps
        # 接近目标时降速
        if progress > 0.8:
            delay = rng.uniform(0.006, 0.015)
        elif progress > 0.4:
            delay = rng.uniform(0.003, 0.008)
        else:
            delay = rng.uniform(0.001, 0.004)
        time.sleep(delay)
    # 微震
    for _ in range(rng.randint(1, 3)):
        page.mouse.move(x + rng.uniform(-2, 2), y + rng.uniform(-2, 2))
        time.sleep(rng.uniform(0.01, 0.03))


def human_hover_click(page, locator, rng=None):
    """悬停 200-800ms 后点击。"""
    rng = rng or random
    box = locator.bounding_box()
    if not box:
        locator.click()
        return
    tx = box["x"] + box["width"] / 2 + rng.uniform(-3, 3)
    ty = box["y"] + box["height"] / 2 + rng.uniform(-3, 3)
    human_mouse_move(page, tx, ty, rng)
    time.sleep(rng.uniform(0.2, 0.8))
    page.mouse.down()
    time.sleep(rng.uniform(0.04, 0.12))
    page.mouse.up()


def human_type(page, selector, text, rng=None):
    """人类化输入：逐字符、随机间隔、偶尔回删。"""
    rng = rng or random
    # 兼容字符串 selector 与 Locator
    if hasattr(selector, "click"):
        loc = selector
        loc.click()
        target = loc
    else:
        page.click(selector)
        target = page.locator(selector)
    time.sleep(rng.uniform(0.1, 0.3))
    for ch in text:
        page.keyboard.type(ch)
        # 80-180ms 按键间隔
        time.sleep(rng.uniform(0.08, 0.18))
        # 小概率（2%）停顿更久（思考）
        if rng.random() < 0.02:
            time.sleep(rng.uniform(0.4, 1.0))
    # 5% 概率回删重打（模拟纠错）
    if rng.random() < 0.05 and len(text) > 4:
        del_n = rng.randint(1, 3)
        for _ in range(del_n):
            page.keyboard.press("Backspace")
            time.sleep(rng.uniform(0.06, 0.12))
        time.sleep(rng.uniform(0.2, 0.5))
        for ch in text[-del_n:]:
            page.keyboard.type(ch)
            time.sleep(rng.uniform(0.08, 0.15))


def human_scroll(page, rng=None, max_scroll=1200):
    """随机滚动页面（模拟阅读）。"""
    rng = rng or random
    for _ in range(rng.randint(1, 3)):
        delta = rng.randint(100, max_scroll) * rng.choice([-1, 1])
        page.mouse.wheel(0, delta)
        time.sleep(rng.uniform(0.2, 0.8))


def human_pause(rng=None):
    """随机停留时间。"""
    rng = rng or random
    time.sleep(lognormal_delay(mean=1.5, sigma=0.8))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("humanize 模块就绪")
