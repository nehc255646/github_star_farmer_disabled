"""代理池管理。

针对 DEFECTS_ANALYSIS.md 第 3 节：
- 支持住宅/ISP/数据中心代理（HTTP/SOCKS5）
- 代理存活/延迟/信誉评分
- 会话粘滞（同一账号全流程固定 IP）
- 透明代理脚本可移植化
"""

import logging
import random
import threading
import time
import requests

logger = logging.getLogger("star_farmer.proxy")


class ProxyPool:
    """代理池：管理多个代理，提供评分与分配。"""

    def __init__(self, proxies=None, check_url="https://api.ipify.org?format=json"):
        """
        proxies: 代理列表，形如 ["http://user:pass@ip:port", "socks5://ip:port", ...]
        """
        self.proxies = []
        self.check_url = check_url
        self._lock = threading.Lock()
        for p in proxies or []:
            self.add_proxy(p)

    def add_proxy(self, proxy):
        with self._lock:
            self.proxies.append({
                "url": proxy,
                "alive": None,       # True/False
                "latency": None,     # ms
                "ip": None,          # 出口 IP
                "fail_count": 0,
                "last_check": 0,
            })

    def check_proxy(self, entry, timeout=15):
        """检测代理存活与延迟，返回 (ok, latency_ms, ip)。"""
        try:
            start = time.time()
            proxies = {"http": entry["url"], "https": entry["url"]}
            r = requests.get(self.check_url, proxies=proxies, timeout=timeout,
                             headers={"User-Agent": "curl/8.0"})
            latency = (time.time() - start) * 1000
            ip = r.json().get("ip", "") if r.headers.get("content-type", "").startswith("application/json") else r.text.strip()
            return r.ok, latency, ip
        except Exception as e:
            logger.debug("代理检测失败 %s: %s", entry["url"], e)
            return False, None, None

    def refresh_all(self, min_interval=30):
        """刷新所有代理状态。"""
        now = time.time()
        with self._lock:
            entries = list(self.proxies)
        for e in entries:
            if now - e["last_check"] < min_interval:
                continue
            ok, lat, ip = self.check_proxy(e)
            with self._lock:
                e["alive"] = ok
                e["latency"] = lat
                e["ip"] = ip
                e["last_check"] = now
                if not ok:
                    e["fail_count"] += 1
            logger.info("代理 %s -> alive=%s latency=%s ip=%s", e["url"], ok, lat, ip)

    def healthy_proxies(self):
        with self._lock:
            return [e for e in self.proxies if e["alive"]]

    def get(self, sticky_key=None):
        """分配一个代理。

        sticky_key: 粘滞键（如账号用户名）。同一 key 尽量返回同一代理，
        保证同一账号全流程 IP 一致（会话粘滞）。
        """
        self.refresh_all()
        healthy = self.healthy_proxies()
        if not healthy:
            # 未检测时默认都算候选
            with self._lock:
                healthy = [e for e in self.proxies if e["alive"] is not False]
        if not healthy:
            return None

        if sticky_key is not None:
            # 基于 key 的确定性选择：同一 key 优先同一代理
            idx = hash(sticky_key) % len(healthy)
            with self._lock:
                if "sticky_for" in healthy[idx] and healthy[idx]["sticky_for"] == sticky_key:
                    return healthy[idx]["url"]
                # 尝试找到一个已粘滞给该 key 的代理
                for e in healthy:
                    if e.get("sticky_for") == sticky_key:
                        return e["url"]
            # 否则绑定（加权：优先低延迟）
            best = min(healthy, key=lambda e: e["latency"] if e["latency"] else 99999)
            with self._lock:
                best["sticky_for"] = sticky_key
            return best["url"]

        # 随机加权选择
        with self._lock:
            return random.choice(healthy)["url"]

    def mark_failed(self, proxy_url):
        with self._lock:
            for e in self.proxies:
                if e["url"] == proxy_url:
                    e["fail_count"] += 1
                    if e["fail_count"] >= 3:
                        e["alive"] = False
                    break

    def stats(self):
        with self._lock:
            total = len(self.proxies)
            alive = sum(1 for e in self.proxies if e["alive"])
            return {"total": total, "alive": alive}


def load_proxies_from_file(path):
    """从文件加载代理列表（每行一个，支持 # 注释）。"""
    proxies = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "://" not in line:
                    line = "http://" + line
                proxies.append(line)
    except FileNotFoundError:
        logger.warning("代理文件不存在: %s", path)
    return proxies


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("proxy_pool 模块就绪")
