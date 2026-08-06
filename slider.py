"""DataDome 滑块验证自动通过。

针对 DEFECTS_ANALYSIS.md 第 5 节 "挑战类型识别"：
识别 DataDome 滑块（slide right to secure）并模拟人类拖动。
"""

import logging
import math
import random
import time

logger = logging.getLogger("star_farmer.slider")


class SliderError(Exception):
    """滑块自动通过失败。"""


def find_slider(frame):
    """在 DataDome iframe 中定位滑块元素。

    返回 (container, target, handle) 或 (None, None, None)。
    """
    try:
        container = frame.locator("[class*='sliderContainer']").first
        target = frame.locator("[class*='sliderTarget']").first
        # 手柄通常在容器内左侧（无独立 class 时用容器自身）
        handle = frame.locator("[class*='slider'] [class*='button'], [class*='slider'] [class*='handle']").first
        if container.count() == 0 or target.count() == 0:
            return None, None, None
        return container, target, handle
    except Exception:
        return None, None, None


def is_slider_present(frame):
    """判断该 iframe 是否包含 DataDome 滑块。"""
    try:
        body = frame.locator("body").inner_text(timeout=2000)
        if "slide right" in body.lower() or "slider" in body.lower():
            return True
        if frame.locator("[class*='sliderContainer']").count() > 0:
            return True
    except Exception:
        pass
    return False


def drag_slider(page, frame, rng=None):
    """模拟人类拖动滑块到目标位置。返回 True/False。"""
    rng = rng or random
    # 计算 iframe 在主页面的偏移（缺陷 #3：iframe 内坐标需补偿）
    offset_x, offset_y = _iframe_offset(page, frame)
    # 直接定位可拖动的 .slider 元素（class 恰为 "slider"，区别于 sliderbg/Mask/Target/Text）
    slider = frame.locator("div.slider").first
    sbox = slider.bounding_box()
    target = frame.locator("[class*='sliderTarget']").first
    tbox = target.bounding_box()
    if not sbox or not tbox:
        raise SliderError("滑块/目标无边界框")

    # 起点：滑块中心（iframe 内坐标 + 页面偏移）
    start_x = sbox["x"] + sbox["width"] / 2 + offset_x
    start_y = sbox["y"] + sbox["height"] / 2 + offset_y + rng.uniform(-2, 2)
    # 终点：目标中心（带小随机）
    end_x = tbox["x"] + tbox["width"] / 2 + offset_x + rng.uniform(-4, 4)
    end_y = start_y + rng.uniform(-1.5, 1.5)
    dist = end_x - start_x

    # 人类化移动：先快速接近，再微调，带抖动
    page.mouse.move(start_x, start_y)
    time.sleep(rng.uniform(0.1, 0.25))
    page.mouse.down()
    time.sleep(rng.uniform(0.05, 0.2))

    # 分多段移动：先快后慢 + 抖动
    steps = rng.randint(18, 30)
    for i in range(1, steps + 1):
        t = i / steps
        # 缓动：开始快，中段微慢，结尾慢（真人拖滑块特征）
        if t < 0.3:
            eased = t / 0.3 * 0.7
        elif t < 0.8:
            eased = 0.7 + (t - 0.3) / 0.5 * 0.25
        else:
            eased = 0.95 + (t - 0.8) / 0.2 * 0.05
        x = start_x + dist * eased + rng.uniform(-1.5, 1.5)
        y = start_y + rng.uniform(-1.5, 1.5)
        page.mouse.move(x, y)
        delay = 0.008 + (rng.random() * 0.025)
        if t > 0.85:
            delay *= 1.8  # 接近目标时减速
        time.sleep(delay)

    # 终点微调（轻微左右试探）
    for _ in range(rng.randint(2, 4)):
        page.mouse.move(end_x + rng.uniform(-3, 3), end_y + rng.uniform(-1, 1))
        time.sleep(rng.uniform(0.03, 0.08))

    time.sleep(rng.uniform(0.15, 0.35))
    page.mouse.up()
    logger.info("滑块拖动完成 (%.0fpx)", dist)
    return True


def _iframe_offset(page, frame):
    """计算 iframe 相对于主页面视口/文档的偏移 (x, y)。

    DataDome 的 captcha iframe 是绝对定位铺满页面时偏移为 0，
    但为稳妥起见仍计算 iframe 元素在主页面的 bounding box。
    """
    try:
        # 找到主页面中指向该 frame 的 iframe 元素
        for el in page.locator("iframe").all():
            try:
                content_frame = el.content_frame()
                if content_frame and content_frame.url == frame.url:
                    box = el.bounding_box()
                    if box:
                        return box["x"], box["y"]
            except Exception:
                continue
    except Exception:
        pass
    return 0, 0


def solve_datadome_slider(page, wait_after=6.0):
    """在页面上查找并解决 DataDome 滑块验证。

    若页面上没有滑块则直接返回 True（无需解决）。
    返回 True 表示滑块已解决或不存在；False 表示失败。
    """
    for fr in page.frames:
        if "captcha-delivery" in fr.url:
            if is_slider_present(fr):
                logger.info("检测到 DataDome 滑块，开始自动拖动…")
                try:
                    drag_slider(page, fr)
                    time.sleep(wait_after)
                    # 校验：滑块是否消失/页面是否恢复
                    still = is_slider_present(fr) if "captcha-delivery" in fr.url else False
                    return not still
                except SliderError as e:
                    logger.warning("滑块失败: %s", e)
                    return False
            else:
                # 无滑块（可能是静默/音频验证），返回 False
                return False
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("slider 模块就绪")
