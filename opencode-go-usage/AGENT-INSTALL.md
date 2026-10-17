# opencode-go-usage 安装指导（写给 agent 执行）

> **给 agent**：这是你（Hermes Agent 或其它编码 agent）要执行的安装说明书。按 §2 → §6 走，
> **§6 的每一条都要真跑并贴出真实输出**，别只写"应该可以"。卡住就停下来问用户，不要猜、不要绕过。
> **给人**：把本目录整个丢给你的 agent，说一句「按 AGENT-INSTALL.md 把 opencode-go-usage 装上并验收」。

| 项 | 值 |
|---|---|
| 包版本 | `1.2.1`（与源插件逐字节一致，sha256 见附录 A） |
| 安装源 | 本文件所在的目录 = 插件树本身，同时是 **Git 仓库的子目录**（`hermes plugins install` 可直接装，见 §3.1）；本说明书随插件一起装进去 |
| 安装目标 | `<HERMES_HOME>/plugins/opencode-go-usage/` |
| 派生目标（App 自动写，**不要手改**） | `<HERMES_HOME>/desktop-plugins/opencode-go-usage/` |
| 要改的配置 | `<HERMES_HOME>/config.yaml` 的 `plugins.enabled`（用 CLI 改，别手编 YAML） |
| 外部依赖 | 无。只用 Hermes 自带 venv 里的 fastapi + Python 标准库，不用 pip、不用 git、不用联网安装 |
| 需要人做的事 | 重启一次 Hermes 桌面端 App；最后在界面上确认芯片 |
| 预计耗时 | 3 分钟 |

**符号约定**（下文通用）：

- `<HERMES_HOME>` / `$HH` = Hermes 主目录（获取办法见 §2.0，别猜路径）。
- `<本目录>` = 你手上这份材料的解压目录 = 本文件（`AGENT-INSTALL.md`）所在目录 = **插件树本身**：要装进 `$HH/plugins/opencode-go-usage/` 的就是它。
- `<仓库根目录>` = 包含本目录的那个 Git 仓库的根（`opencode-go-usage/` 是它的子目录）——本地 Git 安装命令要用到它。

---

## 1. 它是什么 / 它不做什么

**是什么**：Hermes 桌面端的状态栏芯片插件，显示你当前所在**编码套餐**的用量百分比
（滚动 5h / 周 / 月三个窗口），点击展开详情面板。支持两家：**OpenCode Go**（芯片前缀 `Go`，
端点 `/zen/go/v1/usage`）与 **Command Code GOAT / Pro / Max**（芯片前缀 `GOAT`，
端点 `/alpha/billing/credits` + `/alpha/billing/subscriptions`）。它是一个"统一包"——三半合一：

| 半边 | 文件 | 作用 | 生效条件 |
|---|---|---|---|
| agent 半 | `__init__.py` | 空 `register()` 占位，让插件在 CLI/仪表盘里是一个完整可管理的插件 | 无需重启 |
| 后端半 | `dashboard/plugin_api.py` | FastAPI 路由 `/api/plugins/opencode-go-usage/{usage,gate}`，读凭证池 → 套餐注册表（`opencode-go` / `commandcode-goat`）选端点 → 归一化 | 该插件进 `plugins.enabled` **且** 承载它的后端进程重启 |
| 桌面半 | `desktop/plugin.js` | 状态栏芯片 + 弹层（ESM，无构建） | App 把它复制到 `desktop-plugins/` 后热加载 |

**它不做什么**（明确边界，别多做也别担心）：

- 不消耗套餐配额：只调只读的用量元数据端点，不触发任何计费请求。
- 不发遥测、不上报、不写第三方；唯一的对外网络是上面两家官方端点（按当前套餐二选一）。
- 不打印、不落盘、不返回你的 API key（key 只在插件进程内存与请求头里出现）。
- **不修改 Hermes 源码**：只新增 `plugins/` 下自己的目录，加一条 `plugins.enabled`。

---

## 2. 前置条件核对（先做，缺哪条就停下来问用户，别硬装）

### 2.0 先定位 HERMES_HOME

```bash
# 通用（三种 OS 都一样）：打印 config.yaml 路径，其父目录就是 HERMES_HOME
hermes config path          # 例：C:\Users\<you>\AppData\Local\hermes\config.yaml
hermes config env-path      # 例：C:\Users\<you>\AppData\Local\hermes\.env
```

下文用 `$HH` 指代这个目录。Windows 默认 `%LOCALAPPDATA%\hermes`，macOS/Linux 默认 `~/.hermes`
（设了 `HERMES_HOME` 环境变量则以它为准）。

### 2.1 逐条核对

| # | 条件 | 怎么核对 | 不满足怎么办 |
|---|---|---|---|
| 1 | Hermes **桌面端 App** 存在（只有 CLI/Gateway 不行，芯片长在 App 里） | 能启动 App；`hermes --version` 应 ≥ 0.21（本包在 v0.21.3 / 2026.9.14 实测通过） | 先装/升级桌面端 |
| 2 | **至少一家**套餐的 API key 已配进 Hermes：OpenCode Go 或 Command Code（GOAT/Pro/Max） | Go：`hermes auth list opencode-go`（**只显示标签/状态，不显示密钥**）→ 至少 1 条 `api_key`；或 `$HH/.env` 里有 `OPENCODE_GO_API_KEY=`。Command Code：`$HH/.env` 里有 `COMMANDCODE_API_KEY=`（或 `COMMAND_CODE_API_KEY=`） | 让用户自己去后台建 key 并写进 `.env` / 凭证池。**不要向用户索要 key 明文，也不要自己写 key** |
| 3 | App 能把 `desktop/` 半提升到 app 级目录（v0.21+ 的"统一包"机制；老版本没有） | 看 `$HH/desktop-plugins/` 是否存在，或装完看 §6.3 | 走 §5.2 的手动落地方案 |
| 4 | 能写 `$HH` 且能重启 App | 常规用户目录，一般没问题 | 权限问题交给用户 |

> 两家都没 key 的话，装上去芯片会显示 `—`，没有意义——**先确认第 2 条再动手**。
> 只配了一家也正常：另一家对应的模型下芯片会隐藏（门控），不是故障。

---

## 3. 安装（标准 Git 安装：一条命令；手工复制作兜底）

> 本插件按 Hermes 的**标准 Git 安装形态**发布：`hermes plugins install` 认 git 源——GitHub/Gitee/自建仓库、
> 以及**下载到本地的源码目录**都走同一条命令，装完文件落在 `$HH/plugins/opencode-go-usage/`（本说明书也在里面）。
> 前提：机器上有 `git`（Hermes 用系统 git 做 clone）。

### 3.1 来源 A（推荐）：一条命令从 Git 源安装

**从 GitHub（或任何 git 托管）**：

```bash
hermes plugins install linkaixiang4883/hermes-plugins/opencode-go-usage --enable     # owner/repo 简写；也接受完整 URL / GitHub tree URL
```

**从本地源码目录**（仓库已下载/解压到本机；本目录就是该仓库的子目录 `opencode-go-usage/`）：

```powershell
# Windows（pwsh）——Windows 上 file:// 必须写成两斜杠 file://C:/…
# （RFC 的三斜杠 file:///C:/… 会被 git 解析成 /C:/… 后失败，实测如此）
$repo = '<仓库根目录绝对路径，如 C:/Users/me/Downloads/hermes-plugins>'
hermes plugins install "file://$repo#opencode-go-usage" --enable
```

```bash
# macOS / Linux
hermes plugins install "file://<仓库根目录绝对路径>#opencode-go-usage" --enable
```

命令做的事：clone 到临时目录 → 取 `opencode-go-usage/` 子目录 → 装进 `$HH/plugins/opencode-go-usage/`
→ 写 `plugins.enabled` → 记录来源（以后 `hermes plugins update opencode-go-usage` 可更新）。
成功标志（输出里找这两行）：`✓ Plugin opencode-go-usage enabled.` 和 `Restart the gateway for the plugin to take effect`。

- 从 GitHub 下载的 zip、或拷贝时漏掉 `.git` 时，先补个仓库再装：
  `cd <仓库根目录> && git init -q && git add -A && git commit -qm "vendor snapshot"`。
- URL 安装会先打一行 `Warning: custom (unreviewed) source — not from the Hermes catalog.` —— 不在官方 catalog 里都这样，**不是错误**。
- 没有 git 或完全离线：走下面的 3.2 手工复制。

### 3.2 来源 B（兜底）：手工复制插件树

把**本目录**的内容复制到 `$HH/plugins/opencode-go-usage/`（本说明书也跟着进去，不影响运行），最后的目录结构必须是：

```
<HERMES_HOME>/plugins/opencode-go-usage/
├── AGENT-INSTALL.md             # 本说明书（随插件走；不参与附录 A 校验）
├── plugin.yaml                  # 清单：name=opencode-go-usage, version=1.2.1, kind=standalone
├── __init__.py                  # agent 半（空 register）
├── dashboard/
│   ├── manifest.json            # tab.hidden=true + api=plugin_api.py
│   ├── plugin_api.py            # 后端（提供商注册表 + 凭证池跟随 + 模型门控）
│   └── dist/index.js            # 占位（SPA 会盲加载每个 manifest 的 entry，缺文件=404）
├── desktop/
│   └── plugin.js                # 桌面半（状态栏芯片）
└── tests/
    └── test_plugin_api.py       # 离线自检脚本（§6.1 用）
```

Windows PowerShell（7+）：

```powershell
$HH = Split-Path -Parent (hermes config path)
$dst = Join-Path $HH 'plugins\opencode-go-usage'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force '<本目录>\*' $dst
Get-ChildItem -Recurse -File $dst | Select-Object -ExpandProperty FullName
```

macOS / Linux：

```bash
HH="$(dirname "$(hermes config path)")"
mkdir -p "$HH/plugins/opencode-go-usage"
cp -R "<本目录>/." "$HH/plugins/opencode-go-usage/"
find "$HH/plugins/opencode-go-usage" -type f
```

**幂等**：目标已存在就覆盖（`Copy-Item -Force` / `cp -R`）——更新同版本/新版本都用同一条命令。

### 3.3 启用插件（写 `plugins.enabled` 白名单）

如果用了 §3.1 的 `--enable`，这一步已经完成；否则手动写白名单：

```bash
hermes plugins enable opencode-go-usage
```

这会把名字写进 `config.yaml` 的 `plugins.enabled`。**后端半只有在这个白名单里才会被导入**
（`plugins.disabled` 是更高优先级的黑名单，确保里面没有它）。

核对：

```bash
hermes plugins list | grep -i opencode-go-usage      # 期望 Status = enabled，Version = 1.2.1
hermes plugins doctor opencode-go-usage              # 期望 "OK: runtime discovery, manifest parsing, import, and registration passed"
```

### 3.4 给用户一句话，然后等他重启 App

后端进程（App 自己拉起的 serve）在启动时导入 `plugin_api.py`；桌面半也要 App 启动时才会被复制过去。
**所以：必须重开一次 Hermes 桌面端 App。**

给用户的说法：

> 插件文件已装好并启用。请**完全退出并重新打开 Hermes 桌面端**（不是只关窗口，托盘/后台也要退干净）。
> 回来后在状态栏右侧看有没有用量芯片：`Go [████░░░░░░] NN%`（用 OpenCode Go 模型时）
> 或 `GOAT [██░░░░░░░░] NN%`（用 Command Code 模型时）——不在对应套餐的模型下它会故意不显示。

App 已经开着、只是不想重开时的替代路径（能救活桌面半，救不了后端半）：
**设置 → Plugins** 打开这一页（会触发一次 reconcile + rescan，把 `desktop/` 半复制过去并重载），
或命令面板搜 **Reload desktop plugins**。后端半仍然需要重启。

---

## 4. 门控核对（可选，但能省掉 90% 的"芯片不出现"）

芯片**只在当前模型跑在注册表 `model_providers` 里的 provider 上时才显示**。
本包注册的 provider 名是：

- `opencode-go` / `opencode_go` / `opencode-go-sub` → 显示 `Go` 芯片
- `commandcode` / `command-code` / `command_code` / `commandcode-goat` → 显示 `GOAT` 芯片
- 其他（含 `opencode-zen`）→ 芯片隐藏，这是设计。

判定顺序（`plugin_api.py` 的 `/gate`）：① 模型串前缀**且**该前缀在注册表里 → ② 会话在
`state.db` 的 provider（`model_config.provider` → `billing_provider`；本行解析不出时沿
压缩链 `parent_session_id` 上溯，自动压缩轮转后也稳定）→ ③ `config.yaml` 的
`model.provider`。注意**不要**指望"模型串首段就是 provider"：Command Code 的模型 id 形如
`deepseek/deepseek-v4.1-flash`，首段是模型厂商名，所以前缀规则只认注册表内的名字。

核对办法：

```bash
hermes model list 2>/dev/null | head -20      # 或直接问用户/看 config.yaml 的 model 段
```

若用户的 provider 名**不在上面两行里**（比如自定义了别的名字），改一行即可——编辑
`$HH/plugins/opencode-go-usage/dashboard/plugin_api.py`，在对应 `ProviderSpec(...).model_providers`
里加上那个名字，然后重启 App。**只加名字，别改别的**。

---

## 5. 生效与兜底

### 5.1 正常路径

App 启动 →（a）后端进程按 `plugins.enabled` 导入后端半；（b）Electron 主进程把
`plugins/opencode-go-usage/desktop/` 复制到 `desktop-plugins/opencode-go-usage/` 并写
`.hermes-package.json` 标记（记录来源与 mtime，源文件更新后自动重拷）→ 渲染层发现并热加载。
都不需要你手工碰 `desktop-plugins/`。

### 5.2 兜底：App 没有自动提升桌面半（老版本 / 权限问题）

手动把 `<本目录>/desktop/plugin.js` 复制到 `$HH/desktop-plugins/opencode-go-usage/plugin.js`，
然后在 App 里命令面板执行 **Reload desktop plugins**。

注意两点，并告知用户：

- 手工复制的目录**没有** `.hermes-package.json` 标记 → 属于"用户自己装的独立插件"，
  App 永不覆盖它，**以后升级要手动重拷**。
- 同样地，源目录里的 `desktop/` 再更新也不会自动同步到这个手拷副本。

---

## 6. 验收（每条都要真跑，贴真实输出；不许"应该没问题"）

### 6.1 后端自检（最硬的一条，不依赖 App）

用 **Hermes 自带 venv 的 python** 跑包内自检脚本（脚本用 FastAPI `TestClient` 直接把
`plugin_api.py` 装进一个 app 里测，会真实请求一次用量端点）：

```powershell
# Windows
$HH = Split-Path -Parent (hermes config path)
& "$HH\hermes-agent\venv\Scripts\python.exe" "$HH\plugins\opencode-go-usage\tests\test_plugin_api.py"
```

```bash
# macOS / Linux
HH="$(dirname "$(hermes config path)")"
"$HH/hermes-agent/venv/bin/python" "$HH/plugins/opencode-go-usage/tests/test_plugin_api.py"
```

期望结尾：

```
== 结果 ==
FAILURES: 无 —— 全部通过
```

并且 ① / ①b 两段会分别打印两家套餐的三个窗口百分比，例如 `[1, 0, 69]`：

```
   windows: [{"id":"rolling","percent":1,...},{"id":"weekly","percent":0,...},{"id":"monthly","percent":69,...}]
   provider: {'id': 'commandcode-goat', 'display': 'Command Code GOAT', 'short': 'GOAT', 'kind': 'windows'}
```

- 与官网 console / Studio 面板对照允许 **±1** 差异（端点向下取整、网页四舍五入），不是 bug。
- 没有 key / 没有订阅时对应那段会 FAIL——那是**环境缺 key**，不是包坏了；先回 §2.1 第 2 条。
  只配了一家的机器上，另一家的 ① 段固定 FAIL 属预期（包本身没坏）。
- 找不到 venv python：退而用 `hermes plugins doctor opencode-go-usage`（§6.2）+ 让用户看界面（§6.4）。

### 6.2 插件契约检查

```bash
hermes plugins doctor opencode-go-usage
```

期望（逐字）：

```
  manifest: opencode-go-usage 1.2.1 (standalone)
  OK: runtime discovery, manifest parsing, import, and registration passed
```

### 6.3 桌面半落地检查

```powershell
Test-Path (Join-Path (Split-Path -Parent (hermes config path)) 'desktop-plugins\opencode-go-usage\plugin.js')   # True
```

```bash
test -f "$(dirname "$(hermes config path)")/desktop-plugins/opencode-go-usage/plugin.js" && echo True
```

同目录下应有 `.hermes-package.json`（内容含 `"package": "opencode-go-usage"` 和 `source` 指向
`plugins/opencode-go-usage/desktop`）——有它 = App 自动同步的；没有 = 你在 §5.2 手拷的。

### 6.4 端到端（需要人在界面上确认，你不能替他点）

告诉用户（两家都测；只配了 API key 的那家）：

1. 把模型切到一个 **OpenCode Go** 的模型 → 状态栏右侧出现 `Go [████░░░░░░] NN%`；
2. 再切到一个 **Command Code**（provider 名 `commandcode`）的模型 → 芯片变成 `GOAT [██░░░░░░░░] NN%`；
3. 颜色：<50% 绿 / 50–74% 黄 / ≥75% 红；
4. 点一下芯片 → 弹出面板：三个窗口（滚动 5h / 周 / 月）+ 各自重置倒计时 + 池内 key 数
   （GOAT 的月窗口重置时间 = 账单周期末）；
5. 再把模型切到 Zen 或别家 → 芯片**消失**（门控生效，属正常）；
6. 面板底部「更新于 hh:mm」的时间戳应在刷新后变化。

上面都对 = 验收通过。任何一条不对 → 查 §7。

---

## 7. 故障对照表

| 现象 | 最可能的原因 | 处理 |
|---|---|---|
| 芯片**完全不出现** | 当前模型 provider 不在注册表的 `model_providers` 里（门控判定不命中） | §4：把用户的 provider 名加进 `model_providers` 后重启 App；或先切一个 Go 模型验证 |
| 芯片不出现，且切到 Go 模型也不出现 | 后端半没被导入（`plugins.enabled` 没生效 / 没重启）；或桌面半没落地 | §3.3 核对 `hermes plugins list`；§6.3 核对桌面半文件；然后重启 App |
| 芯片显示 `Go —`，面板写"找不到 API key" | 凭证池里没有 opencode-go 的 key，`.env` 里也没有 `OPENCODE_GO_API_KEY` | §2.1 第 2 条（key 由用户自己配，你别碰明文） |
| 芯片显示 `GOAT —`，面板写"找不到 API key" | `.env` 里没有 `COMMANDCODE_API_KEY`（或 `COMMAND_CODE_API_KEY`） | §2.1 第 2 条（key 由用户自己配） |
| 面板写"key 被拒（401）" | 那把 key 无效/已删除 | 让用户换 key；`hermes auth list opencode-go` 看池里有哪几把 |
| 面板写"该 key 没有对应订阅（403）" | Go：该 key 所属 workspace 没有 Go 订阅，或上游抖动把 403 冒出来了。Command Code：403 = `upgrade_required`（Go 档是唯一没有 API 访问权的档，GOAT/Pro/Max 才有） | Go：先让用户确认订阅；上游抖动会让 Hermes 把 key 冷却 1h，可用 `hermes auth reset opencode-go` 清掉再试。Command Code：让用户确认套餐档位 |
| 面板写"后端不可达 — 确认已加入 plugins.enabled 并重启后端" | 就是字面意思：白名单或重启没做 | §3.3 + §3.4 |
| 面板写"读取凭证池（auth.json）失败" | `auth.json` 正被并发写（Hermes 会重试一次） | 让用户再刷一次；持续失败再看文件权限 |
| 面板写网络错误/超时 | 出网被拦（企业代理/防火墙） | 插件后端用 `urllib` 直连上游（opencode.ai / api.commandcode.ai）；确需代理就设 `HTTPS_PROXY` 环境变量后重启 App。**别把 urllib 的默认 UA 改掉**——默认 UA 会被 Cloudflare 挡成 `403 error code: 1010`，本插件已带专用 UA |
| 面板里"已顺延到下一把可用 key" | 正常行为：主力 key 401/403，自动改用池里下一把 | 不用处理；想切回主力：`hermes auth reset opencode-go` |
| App 报 "Plugin opencode-go-usage failed to load" | 桌面半文件损坏/被手改 | 从本目录重拷 `desktop/plugin.js`，再 Reload desktop plugins |
| Go 一直 403，但订阅看起来是好的 | Go 订阅按【工作区 + 登录账号】绑定；且**入口不同看到的订阅不同** | 让用户从 **Zen 入口**（`opencode.ai/zen` → 登录）进控制台查看/管理自己的 Go 订阅——从 Go 入口进的旧 Console 可能看不到旧订阅 |
| 三个百分比与官网差 1 | 端点 floor vs 网页 round | 正常，别修 |

**排查用的只读探针**（按顺序跑，谁先不对就查那一层）：

```bash
HH="$(dirname "$(hermes config path)")"

hermes plugins list                       # ① 插件被发现且 enabled
hermes plugins doctor opencode-go-usage   # ② 清单/导入/注册 OK
grep "Mounted plugin API routes: /api/plugins/opencode-go-usage/" "$HH/logs/gui.log" | tail -1
# ③ 期望：Mounted plugin API routes: /api/plugins/opencode-go-usage/   ← 后端这一层装上了
grep "hermes_dashboard_plugin_opencode-go-usage:" "$HH/logs/agent.log" | tail -3
# ④ 期望每次取数一行：opencode-go-usage: provider=opencode-go key=<标签> pool=N available=M fetch=ok
test -f "$HH/desktop-plugins/opencode-go-usage/plugin.js" && echo "desktop half: ok"   # ⑤ 桌面半落地
```

`fetch=` 的值就是失败原因（`unauthorized` / `entitlement` / `network` / `timeout`），日志里不会有 key 明文。

---

## 8. 卸载 / 更新

**卸载**：

```bash
hermes plugins disable opencode-go-usage        # 或：hermes plugins remove opencode-go-usage
```

然后删两个目录，并让用户在 App 里 Reload desktop plugins：

```bash
rm -rf "$HH/plugins/opencode-go-usage" "$HH/desktop-plugins/opencode-go-usage"
```

（`desktop-plugins/` 下那份如果带 `.hermes-package.json`，App 在源目录消失后也会自己清掉。）

**更新**：Git 安装的用 `hermes plugins update opencode-go-usage`；手工复制装的用新包重跑 §3.2 → §3.4（覆盖 + 重启 App）。源 `desktop/plugin.js` 变了的话，
App 下次 reconcile 会自动重拷桌面半（不需要你手改 `desktop-plugins/`——手改会被覆盖）。

---

## 9. 红线（agent 必读）

1. **不要读、不要打印、不要上传任何 API key**；不要把 key 写进任何文件、日志、commit、聊天记录。
   本插件的响应体里没有 key，你也不需要它。
2. **不要改 Hermes 源码/官方文件**（`hermes-agent/` 下的东西一律别动）。本插件只新增它自己的目录 +
   一条 `plugins.enabled`。
3. **不要自己动 `desktop-plugins/opencode-go-usage/`**（除 §5.2 的兜底），那是 App 的派生目录。
4. 改 `plugin_api.py` 只允许 §4 那种"往 `model_providers` 加一个名字"的最小改动；改完重启 App 并重跑 §6.1。
5. 装不上/验收不过就**如实报告 + 把 §7 排查结果贴出来**，不要用"应该可以了"收尾，也不要伪造输出。

---

## 附录 A：文件清单与校验和

安装完在 `$HH/plugins/opencode-go-usage/` 下应恰好是这 7 个文件 + 本说明书 `AGENT-INSTALL.md`（说明书不参与校验；`__pycache__/` 是运行期产物，可出现）：

| 文件 | 字节 | sha256 |
|---|---|---|
| `plugin.yaml` | 349 | `5bb233dccda758a635ffa7ccb4b90a35aff7bf18aadfd0ba53f6187c28bf8cf5` |
| `__init__.py` | 711 | `4116f16b270fb8ebdf505c19f3f2b9077d922d64845abf4c4e4d842da564a8df` |
| `dashboard/manifest.json` | 406 | `937aab1606567d1866b2b80753152640fe7a57ef76a660c0071a13fbeac99c9d` |
| `dashboard/plugin_api.py` | 30299 | `0da83f13ab58d8ebe67cb7ffae2f17bb83ee43b31be6c8851f7ace1699bc9fe2` |
| `dashboard/dist/index.js` | 304 | `45685cfc0675ce36620d347ba1a9026a8dd691fdcb52087c5f7671a76fa5a6a6` |
| `desktop/plugin.js` | 20013 | `59488e8525897468746ddb2d7ec055faef3a8e12da7ccd89bb0b5924041c6944` |
| `tests/test_plugin_api.py` | 21162 | `52e040f664de184afd2572597400a075f778eb82b61110c2568a998fa4d8ce95` |

自查（可选）：

```bash
cd "$HH/plugins/opencode-go-usage" && find . -type f -not -name 'AGENT-INSTALL.md' -not -path '*__pycache__*' -print0 | xargs -0 sha256sum | sort
```

---

## 附录 B：English TL;DR

`opencode-go-usage` is a Hermes **desktop** status-bar chip showing **coding-plan** usage
(rolling 5h / weekly / monthly), gated to the plan's own models, read-only over official
key-based endpoints: `GET https://opencode.ai/zen/go/v1/usage` (OpenCode Go) or
`GET https://api.commandcode.ai/alpha/billing/credits` + `…/subscriptions` (Command Code GOAT).

Install (agent-executed):

1. Standard install: `hermes plugins install linkaixiang4883/hermes-plugins/opencode-go-usage --enable` (GitHub) or, from a local checkout,
   `hermes plugins install "file://<repo-root>#opencode-go-usage" --enable` (on Windows the file URL must be `file://C:/…`, two slashes).
   Manual copy still works as the offline fallback.
2. `hermes plugins enable opencode-go-usage` (needed for the Python backend to be imported).
3. Ask the user to fully restart the Hermes desktop app (backend import + desktop-half materialization
   both happen at app start). Toasts/dirs to check: `$HH/desktop-plugins/opencode-go-usage/plugin.js`.
4. Verify for real: run `tests/test_plugin_api.py` with the bundled venv python (expect
   `FAILURES: 无 —— 全部通过`), `hermes plugins doctor opencode-go-usage` (expect OK), then have the user
   confirm the chip appears as `Go [████░░░░░░] NN%` on a Go model, `GOAT [██░░░░░░░░] NN%` on a
   Command Code model, and disappears on any other provider.
5. Prerequisite: at least one plan's API key already configured in Hermes (credential pool or
   `OPENCODE_GO_API_KEY` / `COMMANDCODE_API_KEY` in `$HH/.env`). Never handle the key itself.
   Troubleshooting: see §7 above.
