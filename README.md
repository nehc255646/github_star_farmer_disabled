# GitHub Star 自动化操作研究（已归档）

> ⚠️ **本仓库已归档停用，仅供技术研究与学习参考。**

## 声明

本项目是个人对 GitHub 网页自动化、反机器人风控机制、代理与浏览器指纹对抗的一次技术探索，**仅用于研究与教育目的**。内容包含但不限于自动化、网络层、浏览器安全等相关概念的学习笔记与实验代码。

- 本项目**不提供**任何可规模化运营、用于市场推广或商业用途的"刷 Star"服务能力，作者亦不承接此类需求。
- 使用本项目导致的账号异常、仓库被标记、法律纠纷等后果，**均由使用者自行负责**。
- 请遵守 [GitHub Acceptable Use Policies](https://docs.github.com/zh/site-policy/acceptable-use-policies/github-acceptable-use-policies) 与当地法律法规，**不实用于任何真实仓库**。
- 本仓库不再接受针对实战使用相关的 Issue 与 PR，仅保留文档与代码本身的讨论。

## 项目背景

早期版本探索了以下技术方向（均已停用，仅供理解原理）：

| 链路 | 结论 |
|---|---|
| 已有账号登录自动化 | 技术上可行，但违反平台规范 |
| 新账号批量注册 | 受 DataDome 风控拦截，成功率取决于 IP 信誉，实践上不可持续 |
| 代理池 / Tor 出口 | 作为网络层概念研究，数据中心 / Tor 出口 IP 信誉普遍较差 |

> 结论：该方向因平台风控严格、风险高、且违反平台规范，**已放弃并归档**。

## 环境与依赖（仅供复现研究）

依赖声明见 `requirements.txt`。

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

运行代码需本机装有 Chromium 浏览器；请在 `config.yaml` 中自行配置 `browser.executable_path` 指向本地浏览器可执行文件。

## 项目结构（存档说明）

```
main.py          # 入口 + 并发调度
account.py       # 账号数据模型 + SQLite 存储
email_client.py  # 临时邮箱客户端（mail.tm）
tor_control.py   # Tor NEWNYM 换 IP
network.py       # 网络模式切换
stealth.py       # 浏览器指纹对抗研究
humanize.py      # 人类化行为模拟
challenge.py     # 风控检测与分类
slider.py        # 滑块验证码相关研究
proxy_pool.py    # 代理池数据结构
check_ip.py      # 出口 IP 检测
tor_sweep.py     # Tor 出口批量探测（实验性）
test_smoke.py    # 冒烟测试
```

## 相关数据文件

代码运行会自行生成以下数据文件；均已加入 `.gitignore`，不会随仓库上传：

- `creds.db`：SQLite 数据
- `accounts.txt`：账号清单
- `sessions/`：Cookie/指纹/代理会话
- `proxies.txt`：代理池

## 后续计划（已停止）

- ❌ 停止任何实战用途支持
- ❌ 不再维护滑块/注册对抗等功能的运行结果
- ✅ 仅保留学习笔记、文档与代码存档参考价值

## 许可证

本项目仅用于个人学习与研究，未开放任何商业授权。**请勿将本项目用于任何违反平台条款或当地法律的用途。**