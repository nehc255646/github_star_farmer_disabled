"""网络模式切换：Tor 透明代理 <-> 直连（VPN/本机出口）。

本机默认用 iptables 把全部 TCP 重定向到 Tor（透明代理），所以普通程序
“直连”实际也会走 Tor。直连模式 = 临时关闭这些 iptables 规则，让流量走
本机真实出口（VPN），刷 GitHub 时 DataDome 风控概率会大幅降低。
"""

import logging
import subprocess

logger = logging.getLogger("star_farmer.network")

TORIFY_SCRIPT = "/home/kali/Desktop/torify-all.sh"
UNTORIFY_SCRIPT = "/home/kali/Desktop/untorify.sh"


def _run(script):
    """以 sudo 运行脚本。"""
    logger.info("执行网络切换脚本: %s", script)
    try:
        r = subprocess.run(
            ["sudo", "bash", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            logger.warning("脚本返回码 %d: %s", r.returncode, r.stderr.strip()[-500:])
            return False
        # 打印脚本输出（最后几行）
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        for ln in lines[-3:]:
            logger.info("  | %s", ln.strip())
        return True
    except Exception as e:
        logger.error("网络切换失败: %s", e)
        return False


def is_tor_transparent_active():
    """检测 iptables 是否启用了 Tor 透明代理（OUTPUT 链存在 TOR 跳转）。"""
    try:
        r = subprocess.run(
            ["sudo", "-n", "iptables", "-t", "nat", "-L", "OUTPUT", "-n"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return "TOR" in r.stdout
    except Exception:
        return False


def enable_direct():
    """关闭 Tor 透明代理，恢复直连（走本机 VPN/出口）。"""
    if not is_tor_transparent_active():
        logger.info("当前已是直连模式，无需切换")
        return True
    ok = _run(UNTORIFY_SCRIPT)
    # 验证
    if ok and not is_tor_transparent_active():
        logger.info("已切换到直连模式（VPN/本机出口）")
        return True
    logger.warning("直连切换可能未完全生效")
    return ok


def enable_tor():
    """恢复 Tor 透明代理（所有流量走 Tor）。"""
    if is_tor_transparent_active():
        logger.info("当前已是 Tor 模式，无需切换")
        return True
    ok = _run(TORIFY_SCRIPT)
    if ok and is_tor_transparent_active():
        logger.info("已恢复 Tor 透明代理")
        return True
    logger.warning("Tor 恢复可能未完全生效")
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print("当前 Tor 透明代理状态:", is_tor_transparent_active())
