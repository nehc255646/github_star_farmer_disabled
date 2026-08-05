"""Tor 控制模块：通过 ControlPort 发出 NEWNYM 信号，强制 Tor 更换出口 IP。"""

import os
import socket
import time
import logging

logger = logging.getLogger("star_farmer.tor")


class TorControl:
    """封装与 Tor ControlPort 的交互。"""

    def __init__(self, host="127.0.0.1", port=9051, cookie_file=None):
        self.host = host
        self.port = port
        self.cookie_file = cookie_file or "/run/tor/control.authcookie"

    def _read_cookie(self):
        if not os.path.exists(self.cookie_file):
            raise FileNotFoundError(f"Tor cookie 文件不存在: {self.cookie_file}")
        with open(self.cookie_file, "rb") as f:
            return f.read().hex()

    def _send_command(self, sock, cmd):
        sock.sendall((cmd + "\r\n").encode())
        sock.settimeout(10)
        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                # Tor 单行响应以 CRLF 结束；多行响应以 250+ 开头，遇非 250 行结束
                if data.endswith(b"\r\n"):
                    lines = data.decode(errors="replace").strip().split("\r\n")
                    first = lines[0]
                    if first.startswith("250+"):
                        # 多行响应：继续读直到遇到不以 '250 ' 开头的行
                        if len(lines) > 1 and not lines[-1].startswith("250 "):
                            break
                    else:
                        break
                if len(data) > 65536:
                    break
        except socket.timeout:
            pass
        return data.decode(errors="replace")

    def new_identity(self, wait=3):
        """请求 Tor 更换电路（NEWNYM），可选等待数秒让新电路生效。"""
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            # 认证（cookie 方式）
            cookie_hex = self._read_cookie()
            resp = self._send_command(sock, f"AUTHENTICATE {cookie_hex}")
            if not resp.startswith("250"):
                raise RuntimeError(f"Tor AUTHENTICATE 失败: {resp.strip()}")

            resp = self._send_command(sock, "SIGNAL NEWNYM")
            if not resp.startswith("250"):
                raise RuntimeError(f"Tor NEWNYM 失败: {resp.strip()}")

            # 主动关闭，让 Tor 清理旧电路
            self._send_command(sock, "QUIT")

        if wait > 0:
            time.sleep(wait)
        logger.info("NEWNYM 信号已发送，等待 %.1fs 切换新出口", wait)
        return True


def get_public_ip(socks_proxy="socks5://127.0.0.1:9050"):
    """通过 SOCKS5 代理查询当前出口 IP（用于验证换 IP 是否生效）。"""
    try:
        import requests
        session = requests.Session()
        session.proxies = {"http": socks_proxy, "https": socks_proxy}
        r = session.get("https://check.torproject.org/api/ip", timeout=20)
        if r.ok:
            return r.json().get("IP")
    except Exception as e:
        logger.warning("查询出口 IP 失败: %s", e)
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ctl = TorControl()
    ip1 = get_public_ip()
    print("换 IP 前:", ip1)
    ctl.new_identity(wait=5)
    ip2 = get_public_ip()
    print("换 IP 后:", ip2)
