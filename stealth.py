"""浏览器指纹对抗层。

针对 DataDome / Cloudflare / Akamai 等风控的指纹向量逐项注入伪装。
参考 DEFECTS_ANALYSIS.md 第 1 节：Canvas / WebGL / AudioContext / Fonts /
Screen / MediaDevices / Battery / navigator 属性 等。

用法：
    from stealth import install_stealth
    install_stealth(context, fingerprint)
"""

import json
import logging

logger = logging.getLogger("star_farmer.stealth")


def install_stealth(context, fp=None):
    """向 Playwright/Patchright 的 BrowserContext 注入全部反检测脚本。

    fp: 指纹对象（dict），可传 None 使用默认值。字段参见 make_fingerprint()。
    """
    fp = fp or {}
    ua = fp.get("user_agent") or _default_ua()
    vendor = fp.get("vendor", "Google Inc.")
    renderer = fp.get("webgl_renderer")
    vendor_gl = fp.get("webgl_vendor", "Google Inc. (NVIDIA)")
    platform = fp.get("platform", "Win32")
    hardware_concurrency = fp.get("hardware_concurrency", 8)
    device_memory = fp.get("device_memory", 8)
    languages = json.dumps(fp.get("languages", ["en-US", "en"]))
    color_depth = fp.get("color_depth", 24)
    screen_w, screen_h = fp.get("screen_size", (1920, 1080))
    fonts = json.dumps(fp.get("fonts", []))

    init_script = f"""
    // ============ navigator 基础属性伪装 ============
    const _setProp = (obj, prop, val) => {{
        try {{
            Object.defineProperty(obj, prop, {{ get: () => val, configurable: true }});
        }} catch (e) {{}}
    }};

    _setProp(navigator, 'webdriver', undefined);
    _setProp(navigator, 'languages', {languages});
    _setProp(navigator, 'language', 'en-US');
    _setProp(navigator, 'platform', '{platform}');
    _setProp(navigator, 'hardwareConcurrency', {hardware_concurrency});
    _setProp(navigator, 'deviceMemory', {device_memory});
    _setProp(navigator, 'maxTouchPoints', 0);
    _setProp(navigator, 'pdfViewerEnabled', true);
    _setProp(navigator, 'doNotTrack', null);
    _setProp(navigator, 'vendor', '{vendor}');
    _setProp(navigator, 'appVersion', '{_default_ua().split("Chrome/")[0]}Chrome/{_chrome_version(ua)} Safari/537.36');

    // plugins（非空以过基本检测）
    try {{
        _setProp(navigator, 'plugins', (() => {{
            const p = new Array(5);
            for (let i=0;i<p.length;i++) {{
                p[i] = {{ name: ['Chrome PDF Plugin','Chrome PDF Viewer','Native Client','Widevine Content Decryption Module','Chromium PDF Plugin'][i], filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 }};
            }}
            return p;
        }})());
    }} catch (e) {{}}

    // userAgentData（Client Hints）
    try {{
        if (navigator.userAgentData) {{
            const brands = [
                {{ brand: 'Chromium', version: '{_chrome_version(ua)}' }},
                {{ brand: 'Google Chrome', version: '{_chrome_version(ua)}' }},
                {{ brand: 'Not=A?Brand', version: '24' }},
            ];
            _setProp(navigator.userAgentData, 'brands', brands);
            _setProp(navigator.userAgentData, 'mobile', false);
            _setProp(navigator.userAgentData, 'platform', '{platform}');
            const origHigh = navigator.userAgentData.getHighEntropyValues.bind(navigator.userAgentData);
            navigator.userAgentData.getHighEntropyValues = (hints) => {{
                return origHigh(hints).then((res) => {{
                    res.platform = '{platform}';
                    res.brands = brands;
                    res.mobile = false;
                    return res;
                }});
            }};
        }}
    }} catch (e) {{}}

    // ============ 浏览器窗口特征 ============
    try {{
        window.chrome = window.chrome || {{ runtime: {{}}, loadTimes: () => ({{}}), csi: () => ({{}}) }};
    }} catch (e) {{}}

    // ============ Canvas 指纹混淆 ============
    try {{
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function (...args) {{
            const result = origToDataURL.apply(this, args);
            // 只对非空 canvas 做像素级扰动
            try {{
                const ctx = this.getContext('2d');
                if (ctx && this.width > 0 && this.height > 0) {{
                    const img = ctx.getImageData(0, 0, this.width, this.height);
                    const noise = 0.5 + (Math.random() * 1.0);
                    for (let i = 0; i < img.data.length; i += 16) {{
                        img.data[i] = Math.min(255, Math.max(0, img.data[i] + noise));
                    }}
                    // 无需真正重绘，仅干扰哈希来源即可
                }}
            }} catch (e) {{}}
            return result;
        }};
        const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function (...args) {{
            const img = origGetImageData.apply(this, args);
            const noise = Math.floor(Math.random() * 2);
            if (noise > 0 && img.data.length > 100) {{
                for (let i = 0; i < img.data.length; i += 7) {{
                    img.data[i] = Math.min(255, Math.max(0, img.data[i] + noise));
                }}
            }}
            return img;
        }};
    }} catch (e) {{}}

    // ============ WebGL 指纹伪装 ============
    try {{
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function (parameter) {{
            if (parameter === 37445) {{ return '{vendor_gl}'; }}   // UNMASKED_VENDOR_WEBGL
            if (parameter === 37446) {{ return '{renderer}'; }}    // UNMASKED_RENDERER_WEBGL
            if (parameter === 7936) {{ return '{vendor}'; }}       // VENDOR
            return getParameter.call(this, parameter);
        }};
        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function (parameter) {{
            if (parameter === 37445) {{ return '{vendor_gl}'; }}
            if (parameter === 37446) {{ return '{renderer}'; }}
            if (parameter === 7936) {{ return '{vendor}'; }}
            return getParameter2.call(this, parameter);
        }};
    }} catch (e) {{}}

    // ============ AudioContext 指纹混淆 ============
    try {{
        const origGetChannelData = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function (channel) {{
            const data = origGetChannelData.call(this, channel);
            const noise = 0.000001 + (Math.random() * 0.000002);
            for (let i = 0; i < data.length; i += 8) {{
                data[i] += noise;
            }}
            return data;
        }};
    }} catch (e) {{}}

    // ============ Fonts 枚举伪装 ============
    try {{
        if (document.fonts && document.fonts.check) {{
            const origCheck = document.fonts.check.bind(document.fonts);
            document.fonts.check = function (...args) {{
                return true;
            }};
        }}
    }} catch (e) {{}}

    // ============ Screen 伪装 ============
    try {{
        _setProp(screen, 'width', {screen_w});
        _setProp(screen, 'height', {screen_h});
        _setProp(screen, 'availWidth', {screen_w});
        _setProp(screen, 'availHeight', {screen_h - 40});
        _setProp(screen, 'colorDepth', {color_depth});
        _setProp(screen, 'pixelDepth', {color_depth});
    }} catch (e) {{}}

    // ============ MediaDevices 伪装 ============
    try {{
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            const origEnum = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
            navigator.mediaDevices.enumerateDevices = async () => {{
                const devices = await origEnum();
                const filtered = devices.filter(d => d.kind !== 'audiooutput');
                return filtered;
            }};
        }}
    }} catch (e) {{}}

    // ============ Battery API ============
    try {{
        if (navigator.getBattery) {{
            navigator.getBattery = () => Promise.resolve({{
                charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1
            }});
        }}
    }} catch (e) {{}}
    """

    context.add_init_script(init_script)
    logger.info("stealth 指纹注入完成: screen=%dx%d webgl=%s hw=%d mem=%d",
                screen_w, screen_h, renderer, hardware_concurrency, device_memory)
    return True


def _default_ua():
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _chrome_version(ua):
    try:
        return ua.split("Chrome/")[1].split(" ")[0]
    except Exception:
        return "126.0.0.0"


def make_fingerprint(rng=None):
    """生成一套一致性指纹（同账号需复用，勿每次随机）。"""
    import random
    rng = rng or random
    # 常见真实 GPU 渲染器（避免暴露虚拟机/无 GPU）
    renderers = [
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 2070 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (AMD, AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)",
    ]
    vendors_gl = [
        "Google Inc. (NVIDIA)",
        "Google Inc. (AMD)",
        "Google Inc. (Intel)",
    ]
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    ]
    screen_sizes = [(1920, 1080), (2560, 1440), (1536, 864), (1440, 900), (1366, 768)]
    return {
        "user_agent": rng.choice(ua_list),
        "vendor": "Google Inc.",
        "webgl_renderer": rng.choice(renderers),
        "webgl_vendor": rng.choice(vendors_gl),
        "platform": "Win32",
        "hardware_concurrency": rng.choice([4, 8, 8, 8, 16]),
        "device_memory": rng.choice([4, 8, 8, 16]),
        "languages": ["en-US", "en"],
        "color_depth": 24,
        "screen_size": rng.choice(screen_sizes),
        "fonts": [],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    fp = make_fingerprint()
    print(json.dumps(fp, indent=2))
