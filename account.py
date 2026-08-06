"""账号信息生成与 SQLite 持久化存储。"""

import json
import logging
import random
import re
import sqlite3
import string
import threading
import time

logger = logging.getLogger("star_farmer.account")


class AccountGenerator:
    """生成随机 GitHub 风格用户名与密码。"""

    # 常见词根，用于生成拟人化用户名（降低被风控概率）
    PREFIX = [
        "neo", "alpha", "omega", "delta", "luna", "nova", "star", "moon", "sky",
        "river", "storm", "cloud", "wolf", "fox", "hawk", "raven", "pine", "oak",
        "frost", "ember", "blaze", "crimson", "azure", "silver", "gold", "iron",
        "koala", "panda", "tiger", "leo", "max", "dev", "code", "git", "web",
        "tech", "byte", "data", "loop", "array", "stack", "rust", "dot", "net",
    ]
    SUFFIX = [
        "dev", "coder", "lab", "hub", "base", "stack", "forge", "x", "io",
        "pro", "geek", "ninja", "guru", "hack", "wave", "byte", "bit", "sys",
    ]

    def __init__(self, password_suffix="GitHub#2026"):
        self.password_suffix = password_suffix

    def username(self, rng=None):
        rng = rng or random
        while True:
            if rng.random() < 0.6:
                u = rng.choice(self.PREFIX) + rng.choice(self.SUFFIX) + str(rng.randint(10, 999))
            else:
                u = rng.choice(self.PREFIX) + str(rng.randint(100, 9999))
            # GitHub 用户名规则：字母开头，字母数字或单个连字符，3-39 字符
            if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{2,38}", u) and "--" not in u:
                return u

    def password(self, rng=None):
        rng = rng or random
        base = "".join(rng.choices(string.ascii_letters + string.digits, k=10))
        return base + self.password_suffix

    def display_name(self, rng=None):
        rng = rng or random
        first = rng.choice(["Alex", "Chris", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Quinn"])
        last = rng.choice(["Lee", "Chen", "Smith", "Wang", "Brown", "Garcia", "Kim", "Miller", "Davis", "Lopez"])
        return f"{first} {last}"

    def profile(self, rng=None):
        """生成一套完整 GitHub 个人资料（头像/Bio/Location/公司/网址）。"""
        rng = rng or random
        bios = [
            "Software engineer passionate about open source.",
            "Full-stack developer | coffee enthusiast",
            "Building things on the internet.",
            "Lifelong learner. Code, music, and mountains.",
            "Backend engineer. Rust & Go.",
            "Student, developer, dreamer.",
            "Frontend dev. Design systems and accessibility.",
        ]
        locations = ["San Francisco, CA", "Seattle, WA", "Austin, TX", "New York, NY",
                     "Toronto, Canada", "London, UK", "Berlin, Germany", "Tokyo, Japan",
                     "Singapore", "Melbourne, Australia", "Vancouver, Canada", "Portland, OR"]
        companies = ["", "", "", "Acme Inc.", "Globex", "Initech", "Umbrella Corp",
                     "Stark Industries", "Wayne Enterprises", "Hooli"]
        sites = ["", "", "https://dev.to/" + self.username(rng), "https://github.com/" + self.username(rng)]
        return {
            "name": self.display_name(rng),
            "bio": rng.choice(bios),
            "location": rng.choice(locations),
            "company": rng.choice(companies),
            "website": rng.choice(sites),
        }


class AccountStore:
    """SQLite 存储：记录注册进度与账号凭证。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS accounts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT UNIQUE,
        password    TEXT,
        email       TEXT,
        created_at  REAL,
        status      TEXT DEFAULT 'pending',   -- pending/registered/starred/failed
        star_time   REAL,
        ip          TEXT,
        profile     TEXT,                     -- JSON: 姓名/bio/地点/公司/网站
        proxy       TEXT,                     -- 粘滞代理
        session_file TEXT,                    -- 会话文件路径
        note        TEXT
    );
    """

    def __init__(self, db_path="creds.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(self.SCHEMA)
        self.conn.commit()

    def add_pending(self, username, password, email):
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO accounts (username, password, email, created_at, status) VALUES (?,?,?,?,?)",
                    (username, password, email, time.time(), "pending"),
                )
                self.conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error("写入账号失败: %s", e)
                return False

    def update_status(self, username, status, ip=None, note=None):
        with self._lock:
            self.conn.execute(
                "UPDATE accounts SET status=?, ip=COALESCE(?, ip), note=COALESCE(?, note) WHERE username=?",
                (status, ip, note, username),
            )
            self.conn.commit()

    def save_profile(self, username, profile, proxy=None):
        """保存完整 profile（JSON 序列化）与粘滞代理。"""
        with self._lock:
            self.conn.execute(
                "UPDATE accounts SET profile=?, proxy=COALESCE(?, proxy) WHERE username=?",
                (json.dumps(profile, ensure_ascii=False), proxy, username),
            )
            self.conn.commit()

    def get(self, username):
        with self._lock:
            cur = self.conn.execute("SELECT * FROM accounts WHERE username=?", (username,))
            row = cur.fetchone()
            return dict(row) if row else None

    def mark_starred(self, username, star_time=None):
        with self._lock:
            self.conn.execute(
                "UPDATE accounts SET status='starred', star_time=? WHERE username=?",
                (star_time or time.time(), username),
            )
            self.conn.commit()

    def get_all(self):
        with self._lock:
            cur = self.conn.execute("SELECT * FROM accounts ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def count_by_status(self):
        with self._lock:
            cur = self.conn.execute("SELECT status, COUNT(*) c FROM accounts GROUP BY status")
            return {r["status"]: r["c"] for r in cur.fetchall()}

    def export_txt(self, out_file="accounts.txt"):
        lines = ["# username\tpassword\temail\tstatus"]
        for a in self.get_all():
            lines.append(f"{a['username']}\t{a['password']}\t{a['email']}\t{a['status']}")
        with open(out_file, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info("账号列表已导出: %s", out_file)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gen = AccountGenerator()
    print("示例用户名:", [gen.username() for _ in range(5)])
    print("示例密码:", gen.password())
