# GitHub Star 刷取工具（实验性存档，实战不可用）

> ## ⚠️ 重要声明：本项目实战不可用，请勿用于生产或商业用途
>
> 1. **违反 GitHub 服务条款**：批量注册账号、虚假 Star 均违反 GitHub ToS，会导致账号封禁、仓库被风控标记，相关风险由使用者自行承担。
> 2. **实战已证实不可行**：本项目经过反复调试与实测，注册链路受 DataDome 风控保护（TLS 指纹 + IP 信誉 + JS 指纹 + 行为分析多层评分），Tor / 机房 IP 几乎全部被拦截；即使使用住宅代理池，账号封禁率依然极高，无法稳定工作。
> 3. **本仓库仅作技术实验存档**：代码保留了风控对抗相关的实验性实现（指纹、滑块、代理池等），仅供安全研究与学习参考，不构成任何可用性承诺。
>
> 若需为开源项目获得关注，请走正规渠道：社区运营、技术内容推广、开源平台官方曝光等。

## 项目背景（历史）

本项目最初尝试批量注册 GitHub 小号并给目标仓库刷 Star（或使用已有账号刷 Star）。
经过多轮加固（指纹对抗、行为模拟、代理池、会话持久化等），**实战结论仍是无法稳定工作**，原因：

- GitHub `/signup` 注册页部署 DataDome 高敏风控，**IP 信誉是第一变量**，Tor 出口 / 数据中心 IP 几乎必拦；
- 新号集中为同一仓库刷 Star 极易触发异常检测，账号连坐封禁、仓库被标记；
- 已有账号直接刷 Star（登录/仓库页不拦）相对可用，但同样违反 ToS，且账号来源本身就是风险。

## 项目结构

```
main.py          # 主入口 + 并发调度（检查点续跑、优雅停机 SIGTERM）
registrar.py     # 注册器（DataDome 检测、滑块自动解、邮箱验证码）
star_booster.py  # 登录 + 刷 Star（会话复用）
account.py       # 随机账号/Profile 生成 + SQLite 存储
email_client.py  # mail.tm 临时邮箱客户端
tor_control.py   # Tor NEWNYM 换 IP
network.py       # 网络模式切换（Tor 透明代理 <-> 直连）
stealth.py       # 浏览器指纹对抗（Canvas/WebGL/Audio/Fonts/UA/Client-Hints）
humanize.py      # 人类化行为（贝塞尔鼠标、逐字打字、悬停、页面探索）
challenge.py     # 风控检测（JS 对象、响应头、iframe、挑战分类）
slider.py        # DataDome 滑块自动拖动
proxy_pool.py    # 代理池（评分、存活检测、会话粘滞）
session_store.py # Cookie/指纹/代理粘滞持久化
check_ip.py      # 出口 IP 与注册页连通性检测
tor_sweep.py     # Tor 出口批量探测（实验性）
config.yaml      # 配置文件
requirements.txt # 依赖锁定
```

## 环境准备

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

浏览器：需系统装有 Chromium，并在 `config.yaml` 的 `browser.executable_path` 指定路径。

## 使用方式（仅供研究，不保证可用）

### 模式 B：已有账号直接刷 Star

准备账号文件（Tab 分隔，`username<TAB>password<TAB>email`）：

```
user1	pass1	user1@x.com
user2	pass2	user2@x.com
```

```bash
./venv/bin/python main.py --accounts accounts.txt --repo owner/repo --count 10
```

### 模式 A：注册新账号再刷 Star（实测基本无法成功）

```bash
./venv/bin/python main.py --config config.yaml
```

### 网络快速诊断

```bash
./venv/bin/python check_ip.py --probe   # 查出口 IP + 注册页是否被拦
```

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--config` | 配置文件路径（默认 config.yaml） |
| `--accounts` | 已有账号文件，启用模式 B |
| `--repo` | 覆盖目标仓库 owner/repo |
| `--count` | 覆盖刷星数量 |
| `--network tor\|direct` | 覆盖网络模式 |
| `--no-rotate` | 不换 Tor IP |

## 数据存储

- `creds.db`：SQLite，记录账号状态（pending/registered/starred/failed）。
- `accounts.txt`：账号清单导出。
- `sessions/`：每个账号的 Cookie/指纹/代理会话（自动生成）。

## 常见问题

**注册总是失败/被拦截？**
正常。注册页受 DataDome 风控，Tor/数据中心 IP 信誉差，本工具实战不可用。请不要在生产环境尝试。
