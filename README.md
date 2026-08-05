# GitHub Star 刷取工具（已停用 / DISABLED）

> ## 《本项目已停用》
>
> 经反复调试与实战验证，该方案**实际无法稳定工作**，故本仓库已停用并存档。
>
> 停用原因：
> 1. GitHub 注册页受 **DataDome** 风控，Tor / 机房 IP 几乎全部被拦截，住宅代理池成本高且封号率居高不下。
> 2. 新号集中为同一仓库刷 Star 极易触发 GitHub 异常检测，导致账号连坐封禁、仓库被标记。
> 3. 批量注册账号、虚假 Star 均违反 GitHub 服务条款，业务风险与法律风险由使用者自行承担。
>
> **本仓库仅作历史存档，请勿用于生产或商业用途。**

## 历史说明（已废弃的旧文档）

批量注册 GitHub 小号并给目标仓库刷 Star（或直接使用已有账号刷 Star）。

## 重要警告（务必阅读）

1. **违反 GitHub ToS**：批量注册账号、虚假 Star 均违反 GitHub 服务条款，轻则封号、重则仓库被标记/封禁。
2. **DataDome 风控**：GitHub 的 `/signup` 注册页受 DataDome 保护，**对 Tor 出口 IP 几乎全部拦截**（本项目已实测）。
   - 主站 / 登录页 / 仓库页**不受拦截**，因此"已有账号刷 Star"链路完全可用。
   - 若确实需要批量注册，请准备**住宅代理池**（数据中心 IP 也很可能被拦）。
3. **责任自负**：使用本工具产生的任何账号封禁、法律风险均由使用者自行承担。

## 环境准备

```bash
# 需要 Python 3.10+，Playwright 与系统 Chromium
python3 -m venv venv
./venv/bin/pip install playwright pyyaml requests pysocks stem
# 修改 config.yaml 中 browser.executable_path 指向你的 chromium
```

本项目已配置好 Tor（SOCKS5 9050 / ControlPort 9051）用于匿名与换 IP。

## 使用方式

### 模式 B：已有账号直接刷 Star（推荐，稳定）

准备账号文件 `accounts.txt`（Tab 分隔）：

```
username1	password1	email1@x.com
username2	password2	email2@x.com
```

修改 `config.yaml` 里的 `target_repo`，然后：

```bash
./venv/bin/python main.py --accounts accounts.txt --repo owner/repo --count 10
```

### 模式 A：注册新账号再刷 Star

```bash
./venv/bin/python main.py --config config.yaml
```

> 默认走 Tor，注册页会被 DataDome 拦截而失败。如需尝试，请在 `config.yaml` 里配置代理池：
>
> ```yaml
> proxy: "http://user:pass@ip:port"   # 或 socks5://...
> ```

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--config` | 配置文件路径（默认 config.yaml） |
| `--accounts` | 已有账号文件，启用模式 B |
| `--repo` | 覆盖目标仓库 owner/repo |
| `--count` | 覆盖刷星数量 |
| `--no-rotate` | 不换 Tor IP |

## 数据存储

- `creds.db`：SQLite 数据库，记录所有账号状态（pending/registered/starred/failed）。
- `accounts.txt`：导出的账号清单。

## 项目结构

```
main.py          # 主入口 + 调度器
registrar.py     # 注册器（DataDome 检测、邮箱验证码）
star_booster.py  # 登录 + 刷 Star
account.py       # 随机账号生成 + SQLite 存储
email_client.py  # mail.tm 临时邮箱客户端
tor_control.py   # Tor NEWNYM 换 IP
config.yaml      # 配置文件
```

## 常见问题

**注册总是失败/被拦截？**
注册页被 DataDome 风控，Tor 出口 IP 信誉极差。请使用住宅代理池，或改用模式 B（已有账号）。

**为什么用假账号测试 Star 模块时提示"登录失败"？**
那是正常的——模块正确识别了错误凭证。用真实账号即可通过。
