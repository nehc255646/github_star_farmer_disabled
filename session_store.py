"""会话持久化：Cookie / 指纹 / 代理粘滞绑定。

针对 DEFECTS_ANALYSIS.md 第 4 节：
- Cookie 持久化（登录态复用，避免每次新 Context 重新登录）
- 设备指纹一致性（同一账号始终使用同一指纹）
- 代理粘滞（同一账号全流程固定 IP）
"""

import json
import logging
import os
import time

logger = logging.getLogger("star_farmer.session")


class SessionStore:
    """按账号保存会话信息到 JSON 文件。"""

    def __init__(self, dir_path="sessions"):
        self.dir_path = dir_path
        os.makedirs(dir_path, exist_ok=True)

    def _path(self, username):
        safe = username.replace("/", "_").replace("\\", "_")
        return os.path.join(self.dir_path, f"{safe}.json")

    def load(self, username):
        """加载账号会话。返回 dict 或 None。"""
        path = self._path(username)
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("会话读取失败 %s: %s", username, e)
            return None

    def save(self, username, data):
        """保存账号会话（cookie 数组、指纹、代理、时间戳）。"""
        data = dict(data or {})
        data["username"] = username
        data["updated_at"] = time.time()
        path = self._path(username)
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info("会话已保存: %s", username)
            return True
        except Exception as e:
            logger.error("会话保存失败 %s: %s", username, e)
            return False

    def delete(self, username):
        try:
            os.remove(self._path(username))
        except OSError:
            pass

    def list_all(self):
        """列出所有已保存会话的账号名。"""
        names = []
        for fn in os.listdir(self.dir_path):
            if fn.endswith(".json"):
                names.append(fn[:-5])
        return names


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    s = SessionStore()
    s.save("test_user", {"cookie": [], "fingerprint": {"ua": "test"}})
    print("loaded:", s.load("test_user"))
    s.delete("test_user")
