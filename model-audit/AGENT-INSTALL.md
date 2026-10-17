# model-audit 安装指导（写给 agent 执行）

> **给 agent**：这是你（Hermes Agent 或其它编码 agent）要执行的安装说明书。按 §2 → §7 走，
> **§5 的每一条都要真跑并贴出真实输出**，别只写"应该可以"。卡住就停下来问用户，不要猜、不要绕过。
> **给人**：把本目录整个丢给你的 agent，说一句「按 `AGENT-INSTALL.md` 把 model-audit 装上并验收」。

| 项 | 值 |
|---|---|
| 包版本 | `0.4.0`（与源插件逐字节一致，sha256 见附录 A） |
| 安装源 | 本文件所在的目录 = 插件树本身，同时是 **Git 仓库的子目录**（`hermes plugins install` 可直接装，见 §3.1）；本说明书随插件一起装进去 |
| 安装目标 | `<HERMES_HOME>/plugins/model-audit/` |
| 派生目标 | 无。本插件**没有桌面半**（不在桌面端 App 里加 UI）；页面由仪表盘的插件机制直接加载 |
| 要改的配置 | `<HERMES_HOME>/config.yaml` 的 `plugins.enabled`（用 CLI 改，别手编 YAML） |
| 外部依赖 | 无。只用 Hermes 自带 venv 里的 fastapi + Python 标准库，不用 pip、不用 git、不用联网安装 |
| 依赖的上游机制 | 插件 hook `post_api_request`（**公开契约内**）+ 内部符号 `agent.served_model.install_served_model_capture`（**契约外**，fail-open：符号缺失只降级为「无信号」，不报错、不影响主流程） |
| 数据位置 | `$HH/plugin-data/model-audit/model_audit.db` —— **0.4.0 起脱离插件树**（见 §2.2、§7） |
| 需要人做的事 | ① 重启一次承载仪表盘的后端（桌面端 App / `hermes dashboard`）；② 在页面上目测一眼（§5.5） |
| 预计耗时 | 5 分钟 |

**符号约定**（下文通用）：

- `<HERMES_HOME>` / `$HH` = Hermes 主目录（获取办法见 §2.0，别猜路径）。
- `<本目录>` = 你手上这份材料的目录（`AGENT-INSTALL.md` 所在目录）= **插件树本身**：要装进 `$HH/plugins/model-audit/` 的就是它。
- `<仓库根目录>` = 包含本目录的那个 Git 仓库的根（`model-audit/` 是它的子目录）——本地 Git 安装命令要用到它。
- `$VENV` = Hermes 自带 venv 的 python（Windows：`$HH\hermes-agent\venv\Scripts\python.exe`；macOS/Linux：`$HH/hermes-agent/venv/bin/python`）。
- `$NODE` = 任一 node ≥ 18（Windows 可用 Hermes 自带的那份：`$HH\node\node.exe`；macOS/Linux 用系统 `node` 即可）。

---

## 1. 它是什么 / 它不做什么

**是什么**：Hermes **仪表盘**的「模型对账」插件。逐次记录每次**主对话** API 调用的
「请求 alias → 上游实际返回的 model / 路由端点」（真值取自**响应头**），在 **Model Audit** 页对账：
`✅ 一致 / 🟢 已认可 / ❌ 不匹配 / ⚠️ 新路由 / ○ 仅体证 / ◌ 无自证 / — 无信号`。
用途：发现中转**掉包 / 悄悄降级 / 换路由**；出问题时页面里留着 trace id（`x-opencode-log-id` / `x-trace-id`），
可以直接找厂商投诉定位。

它拆成三个半边：

| 半边 | 文件 | 作用 | 生效条件 |
|---|---|---|---|
| agent 半（**服务端**） | `__init__.py` + `model_audit_core.py` | 运行时给核心的 served-model 采集**包一层响应钩子**（白名单响应头按 session 暂存），并在 `post_api_request` hook 里把原始事实落库；**唯一负责建库 / 迁移**（register 时 `ensure_db`，幂等 + busy 重试）。库在 `$HH/plugin-data/model-audit/`（0.4.0 起） | agent/gateway 进程重启后 |
| 后端半（**客户端**） | `dashboard/plugin_api.py` | FastAPI 路由 `/api/plugins/model-audit/{health,rows,summary,approvals,settings,builtin,maintenance/prune}`；**只读探测 `schema_ready`，不建库、不改 schema**——库未就绪时读接口返回空结果 + `initialized:false`，写接口 503（绝不 500），单写者 ⇒ 无跨半竞态 | 该插件进 `plugins.enabled` **且** 承载仪表盘的后端进程重启 |
| 页面半 | `dashboard/dist/index.js` | 仪表盘页（对账 / 分组统计 / 认可管理 三视图） | 仪表盘刷新即加载 |

**它不做什么**（边界写死，别多做也别担心）：

- **不消耗任何套餐额度**：不发起新的模型请求——只是搭在你已有的请求上读响应头。
- **不发遥测**：唯一的对外网络就是本机仪表盘的 REST；没有任何第三方上报。
- **不碰 API key**：不读、不打印、不落盘 key；响应头白名单里没有 `Authorization` / `Cookie`，DB 里也没有 key 列。
- **不改 Hermes 源码文件**：只在运行时**内存里**包装一个函数（fail-open），源码树一个字节都不动。
- **不记录消息正文**：只记元数据（模型名、端点、时间、tokens、finish_reason、会话 id 与标题）。
- **只覆盖主对话调用**：辅助调用（标题生成 / 压缩 / 识图）不走这条链路，不采集。
- **不是所有 provider 都能验**：有的家结构上就不发自证头（如 Command Code——body 里的 `model` 只是请求别名的回声）→
  它的行只能是「◌ 无自证」，模型级掉包检测对那一家无解。这是上游不给信息，**不是插件故障**。

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
| 1 | Hermes Agent **v0.21.6+**（见 §2.2） | `hermes --version`（本包在 **v0.22.2** 端到端实测通过；v0.21.6 是所依赖符号的最早正式 release） | 先升级 Hermes 再装。版本不对会被清单硬门**干净拦下**（`requires hermes >=0.21.6, running …`），不是崩溃 |
| 2 | **核心采集符号存在** | Windows：`& "$HH\hermes-agent\venv\Scripts\python.exe" -c "from agent import served_model as sm; print(callable(getattr(sm,'install_served_model_capture',None)))"`；macOS/Linux：`"$HH/hermes-agent/venv/bin/python" -c "…同上…"` → 期望 `True` | `False`：插件能装、页面能开，但**采不到数**（全「—无信号」）→ 先升级 Hermes |
| 3 | 会话库存在（否则标题列只显示会话 id） | `test -f "$HH/state.db" && echo yes`（Windows：`Test-Path "$HH\state.db"`） | 可继续；标题列会是空/退化 |
| 4 | 有仪表盘入口（页面长在那里） | `hermes dashboard --status`；没在跑就 `hermes dashboard`（默认 <http://127.0.0.1:9119/>） | 先请用户把仪表盘跑起来；数据照采，但看不到页面 |
| 5 | 能写 `$HH` 且能重启仪表盘/App | 常规用户目录，一般没问题 | 权限问题交给用户 |

> 不需要任何 API key——插件读的是本地已有的调用痕迹（响应头 + 会话库标题）。

### 2.2 版本对应关系（哪个 Hermes 装哪个插件版本）

包内 `plugin.yaml` 用 Hermes 的官方字段声明了版本下限：

```yaml
requires_hermes: ">=0.21.6"
```

- **它是硬门**：版本不满足时 Hermes **干净跳过**该插件（不导入、无 traceback），原因出现在
  `hermes plugins list` / `doctor` 里（`requires hermes >=0.21.6, running X.Y.Z`）——
  不会出现「装上了但满屏无信号」这种糊涂状态。
- **依据**：`v0.21.6` 是本仓库最早的**正式** release tag（`v0.21.3/4/5` 从未正式发布），
  且本包依赖的每个符号在该 tag 上逐一做过**存在性验证**；全量端到端实测版本是 **v0.22.2**。
- **版本配对由发布方掌握**：每个插件 release（git tag）声明自己需要的 `requires_hermes`；
  使用者按需选 release。升级插件**不会**改动任何 Hermes 组件，只做拦截与提示。
- **装指定版本**：`hermes plugins install linkaixiang4883/hermes-plugins/model-audit --ref <40 位 commit SHA>`
  —— ⚠️ `--ref` **只接受完整 commit SHA，不接受 tag 名**（拿 tag 的 SHA：`git rev-list -n1 <tag>`）。
  官方 catalog 会同时记 `sha` + `pin`(tag)，是版本锁定最省事的路子。


---

## 3. 安装（标准 Git 安装：一条命令；手工复制作兜底）

> 本插件按 Hermes 的**标准 Git 安装形态**发布：`hermes plugins install` 认 git 源——GitHub/Gitee/自建仓库、
> 以及**下载到本地的源码目录**都走同一条命令，装完文件落在 `$HH/plugins/model-audit/`（本说明书也在里面）。
> 前提：机器上有 `git`（Hermes 用系统 git 做 clone）。

### 3.1 来源 A（推荐）：一条命令从 Git 源安装

**从 GitHub（或任何 git 托管）**：

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --enable     # owner/repo 简写；也接受完整 URL / GitHub tree URL
```

**从本地源码目录**（仓库已下载/解压到本机；本目录就是该仓库的子目录 `model-audit/`）：

```powershell
# Windows（pwsh）——Windows 上 file:// 必须写成两斜杠 file://C:/…
# （RFC 的三斜杠 file:///C:/… 会被 git 解析成 /C:/… 后失败，实测如此）
$repo = '<仓库根目录绝对路径，如 C:/Users/me/Downloads/hermes-plugins>'
hermes plugins install "file://$repo#model-audit" --enable
```

```bash
# macOS / Linux
hermes plugins install "file://<仓库根目录绝对路径>#model-audit" --enable
```

命令做的事：clone 到临时目录 → 取 `model-audit/` 子目录 → 装进 `$HH/plugins/model-audit/` → 写 `plugins.enabled`
→ 记录来源（以后 `hermes plugins update model-audit` 可更新）。
成功标志（输出里找这两行）：`✓ Plugin model-audit enabled.` 和 `Restart the gateway for the plugin to take effect`。

- 从 GitHub 下载的 zip、或拷贝时漏掉 `.git` 时，先补个仓库再装：
  `cd <仓库根目录> && git init -q && git add -A && git commit -qm "vendor snapshot"`。
- URL 安装会先打一行 `Warning: custom (unreviewed) source — not from the Hermes catalog.` —— 不在官方 catalog 里都这样，**不是错误**。
- 没有 git 或完全离线：走下面的 3.2 手工复制。

### 3.2 来源 B（兜底）：手工复制插件树

把**本目录**的内容复制到 `$HH/plugins/model-audit/`（本说明书也跟着进去，它是给维护者看的，不影响运行），最后的目录结构必须是：

```
<HERMES_HOME>/plugins/model-audit/
├── AGENT-INSTALL.md             # 本说明书（随插件走；不参与附录 A 校验）
├── plugin.yaml                  # 清单：name=model-audit, version=0.3.0, provides_hooks=[post_api_request]
├── __init__.py                  # agent 半（响应钩子 + post_api_request 落库）
├── model_audit_core.py          # 共享核心（判定 / 认可 / 标题只读 / 清理 / 分组）
├── dashboard/
│   ├── manifest.json            # tab.path=/model-audit（Analytics 之后）+ api=plugin_api.py
│   ├── plugin_api.py            # 后端（读端点 + 认可/设置/清理写端点）
│   └── dist/index.js            # 页面（三视图，ESM）
└── tests/
    ├── test_audit_core.py       # 离线自检（§5.1 用）
    ├── test_agent_half.py
    ├── test_plugin_api.py
    └── smoke.mjs
```

Windows PowerShell（7+）：

```powershell
$HH = Split-Path -Parent (hermes config path)
$dst = Join-Path $HH 'plugins\model-audit'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force '<本目录>\*' $dst
Get-ChildItem -Recurse -File $dst | Select-Object -ExpandProperty FullName
```

macOS / Linux：

```bash
HH="$(dirname "$(hermes config path)")"
mkdir -p "$HH/plugins/model-audit"
cp -R "<本目录>/." "$HH/plugins/model-audit/"
find "$HH/plugins/model-audit" -type f
```

**幂等**：目标已存在就覆盖（`Copy-Item -Force` / `cp -R`）——更新同版本/新版本都用同一条命令。
`data/`（SQLite）与 `__pycache__/` 不在包里，是运行期产物，**别删数据目录**（删了=清空历史记录）。

### 3.3 启用插件（写 `plugins.enabled` 白名单）

如果用了 §3.1 的 `--enable`，这一步已经完成；否则手动写白名单：

```bash
hermes plugins enable model-audit
```

这会把名字写进 `config.yaml` 的 `plugins.enabled`。**后端半只有在这个白名单里才会被导入**
（`plugins.disabled` 是更高优先级的黑名单，确保里面没有它）。

核对：

```bash
hermes plugins list | grep -i model-audit      # 期望 Status = enabled，Version = 0.3.0
hermes plugins doctor model-audit              # 读法见 §5.2（Windows 上有已知的 WinError 32，别慌）
```

### 3.4 重启，然后给用户一句话

后端半在承载进程**启动时**才导入 `plugin_api.py`；agent 半也要新进程才会挂钩子。所以：

- 桌面端 App：**完全退出再打开**（不是只关窗口，托盘/后台也要退干净）；
- 单独跑的仪表盘：`hermes dashboard --stop` 然后重新 `hermes dashboard`；
- 常驻 gateway / CLI 会话：重启后生效（新会话即开始采集）。

给用户的说法：

> 插件已装好并启用。请**完全退出并重新打开** Hermes 桌面端 / 仪表盘服务。
> 回来后打开仪表盘（`hermes dashboard`，默认 <http://127.0.0.1:9119/>），
> 左侧导航 **Analytics 之后**应该出现「**Model Audit**」页；在里面能看到刚才之后新发生的调用逐条出现。

---

## 4. 生效与页面位置

| 东西 | 什么时候生效 | 去哪里看 |
|---|---|---|
| 采集（agent 半） | 进程重启后的**下一次主对话 API 调用** | §5.4 只读查库 / 页面对账表 |
| 后端路由 | 承载仪表盘的后端进程重启后 | §5.3 日志行 |
| 页面 | 仪表盘刷新后（左侧导航 **Analytics 之后**，图标盾牌） | 浏览器打开仪表盘 |

- 页面是**仪表盘（Web UI）的插件页**——不是桌面端 App 的 `Capabilities → Plugins` 里那种东西
  （那里只会看到插件的启用状态，那是 Python 插件列表，不是本页面）。
- 历史数据不受影响：装之前发生的调用不会补记（采集是逐次实时落库）。

---

## 5. 验收（每条都要真跑，贴真实输出；不许"应该没问题"）

### 5.1 离线自检（最硬的一条，不依赖仪表盘）

用 Hermes 自带 venv 的 python 跑包内 4 个脚本（全部用**临时库**，不会写真实插件库）：

```powershell
# Windows（pwsh）
$HH = Split-Path -Parent (hermes config path)
cd "$HH\plugins\model-audit"
& "$HH\hermes-agent\venv\Scripts\python.exe" tests\test_audit_core.py
& "$HH\hermes-agent\venv\Scripts\python.exe" tests\test_agent_half.py
& "$HH\hermes-agent\venv\Scripts\python.exe" tests\test_plugin_api.py
& "$HH\node\node.exe" tests\smoke.mjs dashboard\dist\index.js
```

```bash
# macOS / Linux
HH="$(dirname "$(hermes config path)")"
cd "$HH/plugins/model-audit"
"$HH/hermes-agent/venv/bin/python" tests/test_audit_core.py
"$HH/hermes-agent/venv/bin/python" tests/test_agent_half.py
"$HH/hermes-agent/venv/bin/python" tests/test_plugin_api.py
node tests/smoke.mjs dashboard/dist/index.js
```

**期望**（4 条全为结尾 `FAILED: none`，退出码 0）：

| 脚本 | PASS 条数（本包实测） | 结尾 |
|---|---|---|
| `test_audit_core.py` | 148 | `FAILED: none` |
| `test_agent_half.py` | 21 | `FAILED: none` |
| `test_plugin_api.py` | 60 | `FAILED: none` |
| `smoke.mjs` | 50 | `FAILED: none` |

说明：这几条都只依赖标准库 + fastapi + node，**不需要 key、不需要联网、不会碰真实数据**；
条数比上表少 0~2 条属正常（不同 python/node 版本的断言分支），**FAILED 非 none 才是问题**。
macOS/Linux 的 venv/node 路径若不同，按 §2.0 的规则自行替换（本包只在 Windows 上实跑过这两条路径）。

### 5.2 插件注册检查（读法）

```bash
hermes plugins doctor model-audit
```

期望（逐字读这两行，其余都别看）：

```
  manifest: model-audit 0.4.0 (standalone)
  registrations: 0 tool(s), 1 hook(s)
```

**0.4.0 起这条已消失**：库不再放在插件树内（`WinError 32` 的根因是 doctor 拷不动**正被插件打开**的 SQLite）。
升级后若仍看到它，说明有进程还开着老位置的文件 → 确认已**完全重启**，并检查
`$HH/plugins/model-audit/data/` 是否只剩 `*.migrated` 退场文件（见 §7）。

### 5.3 后端挂载检查

```bash
HH="$(dirname "$(hermes config path)")"
grep -h "Mounted plugin API routes: /api/plugins/model-audit/" "$HH"/logs/*.log | tail -1
```

期望（有该行即挂上；出现在承载仪表盘的那个进程的日志里，别只盯某一个文件）：

```
2026-09-30 11:47:56,522 INFO hermes_cli.web_server: Mounted plugin API routes: /api/plugins/model-audit/
```

### 5.4 采集判活（关掉仪表盘也能查）

**只读**查库（必须带 `mode=ro`，因为插件同时在写）。Windows（pwsh）：

```powershell
$HH = Split-Path -Parent (hermes config path)
$vp = Join-Path $HH 'hermes-agent\venv\Scripts\python.exe'
& $vp -c "import sqlite3; p = r'$HH\plugin-data\model-audit\model_audit.db'; con = sqlite3.connect(f'file:{p}?mode=ro', uri=True); print('calls:', con.execute('select count(*), max(ts_start) from calls').fetchone()); print('meta :', dict(con.execute('select key,value from meta').fetchall()))"
```

macOS / Linux：

```bash
HH="$(dirname "$(hermes config path)")"
"$HH/hermes-agent/venv/bin/python" -c "import sqlite3; p = r'$HH/plugin-data/model-audit/model_audit.db'; con = sqlite3.connect(f'file:{p}?mode=ro', uri=True); print('calls:', con.execute('select count(*), max(ts_start) from calls').fetchone()); print('meta :', dict(con.execute('select key,value from meta').fetchall()))"
```

**判活两条**（本机实测样本）：

```
calls: (2708, 1790748617.796811)
meta : {'retention_days': '90', 'capture_installed': '1790740076.0470893', 'patch_ok': '1', 'hermes_version': '0.21.5', ...}
```

1. `meta.patch_ok == '1'`（`0` = 采集钩子没装上 → 重启 App/dashboard 再来；还是 0 就看 §2.1 第 2 条）；
2. **发一条消息后 `calls` 计数增长**（用普通对话发一句即可）——数字涨了 = 端到端通了。

### 5.5 界面确认（需要人在界面上看，你不能替他点）

告诉用户，逐条确认：

1. 仪表盘左侧导航 **Analytics 之后**有「**Model Audit**」，点开不报错；
2. 顶部汇总卡有数字（调用 / 一致 / 已认可 / 不匹配 / 新路由 / 无自证 / 无信号），**各卡之和 = 调用总数**；
3. 明细表有行：时间 / 会话标题 / provider / alias / 上游 model / 端点 / 状态 / 耗时；
4. 刚发的那条消息出现在表里（顶部）；
5. 任意一条 `⚠️新路由` / `❌不匹配` 的行点「**认可**」→ 变绿 `🟢已认可`，且不再出现在"只看异常"里；
   「认可管理」页能删掉它并**恢复原判定**；
6. 切「分组统计」：维度下拉（上游 model / alias / provider / 端点 / profile / 状态）切换正常，异常多的排最前；
7. 主题切换（调色板）后页面配色跟随，无写死颜色；
8. 浏览器 F12 控制台无红色报错，`/api/plugins/model-audit/*` 请求全 200。

上面都对 = 验收通过。任何一条不对 → 查 §6。

---

## 6. 故障对照表

| 现象 | 最可能的原因 | 处理 |
|---|---|---|
| 仪表盘左侧没有「Model Audit」 | 后端半没被导入（`plugins.enabled` 没生效 / 没重启）；或打开的不是仪表盘（Web UI） | §3.3 核对 `hermes plugins list`；§3.4 重启；§5.3 看挂载日志 |
| 页面在，但 `/api/plugins/model-audit/*` 404 | 后端没挂载（**enable 与重启的顺序反了**：白名单要在重启之前写好） | 重跑 §3.3 → §3.4（再重启一次即好） |
| 页面在但**没有任何数据** | ① 采集钩子没装（`meta.patch_ok=0`）；② 装完还没发生过主对话调用 | §5.4 查 `patch_ok`；发一条消息再看 |
| 页面能开但**全是 0 / 空表**，接口带 `initialized: false` | **正常**：这台设备还没有任何 agent 进程跑过（schema 由 agent 半 = 服务端创建），本来就没有数据可显示 | 启动一次桌面端 / 网关 / CLI（agent 半会建库），数据随后自动出现 |
| 写操作（认可 / 设置 / 清理）返回 **503** | 库尚未初始化（同上：还没有 agent 进程跑过） | 先启动一次 agent 进程。这是**有意设计**：后端半（客户端）不建库，避免双写者竞态 |
| `/rows` / `/summary` / `/approvals` 返回 **500**（仅 0.2.0 及以下） | 旧版 bug：读接口既没建库兜底、也没优雅降级 | 升级到 **0.3.0+**（0.2.1~0.2.2 的中间版本是「读接口自建空库」，0.3.0 起改为「客户端只读 + `initialized` 标记」） |
| 满屏「— 无信号」 | ① 当前 provider 不发自证头（如 commandcode——它结构上就不发，body 里的 model 只是请求 alias 回声，不是插件故障）；② 采集钩子没装 | ① 正常，不是故障（见 §1 边界）；② 看 `data/capture-debug.jsonl` 的 `resp`/`hook` 行（哪个环节断的） |
| 「只看异常」里出现一堆「⚠️ 新路由」 | 上游走了不同端点（换机房/路由池是常态） | 对确认无问题的组合点「认可」/「仅模型」放行，或让维护者加进内置标准 |
| 某行 `profile` 显示成路径 | 旧行缺 `profile_name`（老数据） | 新行正常；旧行可忽略或让维护者回填 |
| 标题列为空 | 该会话 `title` 为 NULL（压缩产生的父会话本来就没有标题；已实现沿子会话链取） | 属正常；若**所有**行都空，查 §2.1 第 3 条 |
| 分组统计「共 0 组」 | 后端是旧进程（`group_by` 是后加参数） | 重启承载仪表盘的后端 |
| `hermes plugins update` / `--force` 重装时报 **`WinError 32 另一个程序正在使用此文件`**（目录改名失败） | Windows 上插件目录被某个进程占着——**某个终端的工作目录正停在插件目录里**，或探针/杀软句柄没释放（0.4.0 起 SQLite 已移出插件树，不再是占用源） | 把那个终端 `cd` 出去、关掉相关进程再重试；不行就改用「新目录覆盖 + 重启」的方式 |
| Windows 上 doctor 报 `WinError 32`（**仅 ≤0.3.0**） | 库在插件树内、被插件自己开着，doctor 拷不动 | 升级到 **0.4.0**（库移出插件树 = 根因消失）；旧版忽略即可 |
| 提示"找不到 venv python" | Hermes 安装方式不同（非 git / 非 venv 布局） | 用 `hermes plugins doctor`（§5.2）+ §5.4 只读查库 + §5.5 界面判活 |

**排查用的只读探针**（按顺序跑，谁先不对就查那一层）：

```bash
HH="$(dirname "$(hermes config path)")"
hermes plugins list                        # ① 插件被发现且 enabled，Version 0.3.0
hermes plugins doctor model-audit          # ② manifest + registrations（§5.2 读法）
grep -h "Mounted plugin API routes: /api/plugins/model-audit/" "$HH"/logs/*.log | tail -1   # ③ 后端挂载
# ④ 采集：§5.4 的只读查库（patch_ok=1 + calls 增长）
test -f "$HH/state.db" && echo "state.db: ok"    # ⑤ 标题来源
```

日志里不会有 key 明文，也不会有消息正文——本插件这两样都不落。

---

## 7. 卸载 / 更新

**卸载**：

```bash
hermes plugins disable model-audit       # 或：hermes plugins remove model-audit
```

然后删目录并重启（数据要不要留由用户决定）：

```bash
# 只停用、保留数据：什么都不用删（0.4.0 起数据在 $HH/plugin-data/model-audit/，删插件目录也不影响）
# 彻底清掉：
rm -rf "$HH/plugins/model-audit"
```

**更新**：Git 安装的用 `hermes plugins update model-audit`；手工复制装的用新包重跑 §3.2 → §3.4（覆盖 + 重启）。DB 迁移是幂等的，历史数据保留。

---

## 8. 红线（agent 必读）

1. **不要读、不要打印、不要上传任何 API key**（本插件也不需要 key）。
2. **不要改 Hermes 源码/官方文件**（`hermes-agent/` 下的东西一律别动）。本插件只新增它自己的目录 + 一条 `plugins.enabled`。
3. **不要改插件源码**（改了 sha256 就对不上，见附录 A）；需要改就先问维护者。
4. 查库一律 `mode=ro`（插件在写）；**不要**用写模式打开、不要"顺手"清理数据。
5. 装不上/验收不过就**如实报告 + 把 §6 排查结果贴出来**，不要用"应该可以了"收尾，也不要伪造输出。

---

## 附录 A：文件清单与校验和

安装完在 `$HH/plugins/model-audit/` 下应恰好是这 10 个文件 + 本说明书 `AGENT-INSTALL.md`（说明书不参与校验；`__pycache__/` 是运行期产物；`data/` 只在从 ≤0.3.0 升级时出现，且只剩 `*.migrated` 退场文件）：

| 文件 | 字节 | sha256 |
|---|---|---|
| `plugin.yaml` | 833 | `16cbe9f0aef952560faa9e2a40c13ed072adc16a46ca1b90428f20fcab4e1475` |
| `__init__.py` | 10303 | `1a1053a65086cf36a8bc3885396147632f2725342f86e6a75555e70fdcd205e8` |
| `model_audit_core.py` | 45163 | `0e107297a10242ea37106d13f84d8a40cbdb317943f0b9cf446a5f3da9f5febc` |
| `dashboard/manifest.json` | 333 | `5b67ec5a9487a2ae7f6b2cc84f14880e62904cb93e57b98a0fce60b5ac90aae7` |
| `dashboard/plugin_api.py` | 9331 | `cffd01817950e7d3839d4e36846799833ade2145753f8ce66fef812568e4beb3` |
| `dashboard/dist/index.js` | 32731 | `7967772b98e885b9908042a574cdcd60a9bbb2d959c7e75e84c8b7c987271e04` |
| `tests/test_audit_core.py` | 37957 | `9ce30d901c705c0943fbf57f68ca3682c9b41a74d136efd467a017ec9d3a9762` |
| `tests/test_agent_half.py` | 5974 | `a754eaf4f1ddb12a362aabd6cafe930ea51ea35fc5609173b9407f4c9e91c31e` |
| `tests/test_plugin_api.py` | 14517 | `9331f246e15a808e5b2ce92909c39853af72fbd07d6b97e038230c1c6fc236f3` |
| `tests/smoke.mjs` | 15732 | `fefb288e341cbd1db69200da2783f590067f75d251d32e0bb5d879d65a333ea1` | `fefb288e341cbd1db69200da2783f590067f75d251d32e0bb5d879d65a333ea1` | `fefb288e341cbd1db69200da2783f590067f75d251d32e0bb5d879d65a333ea1` |

自查（可选）：

```bash
cd "$HH/plugins/model-audit" && find . -type f -not -name 'AGENT-INSTALL.md' -not -path '*__pycache__*' -not -path './data/*' -print0 | xargs -0 sha256sum | sort
```

---

## 附录 B：English TL;DR

`model-audit` is a **Hermes dashboard** plugin (three halves: agent-side `post_api_request` hook +
runtime response-header capture; FastAPI backend under `dashboard/`; an ESM page bundle). It records,
per main-conversation API call, the **requested alias vs the model/endpoint the upstream actually
served** (read from response headers such as `x-opencode-upstream-model-id` / `x-litellm-model-id`),
and surfaces them on a **Model Audit** page (reconciliation table / group-by statistics / approvals).
Read-only, zero cost (no extra model calls), no telemetry, no API keys touched, no Hermes source
changes (fail-open in-memory wrap).

Install (agent-executed):

1. Standard install: `hermes plugins install linkaixiang4883/hermes-plugins/model-audit --enable` (GitHub) or, from a local checkout,
   `hermes plugins install "file://<repo-root>#model-audit" --enable` (on Windows the file URL must be `file://C:/…`, two slashes).
   Manual copy still works as the offline fallback.
2. `hermes plugins enable model-audit` (needed for the Python backend to be imported).
3. Ask the user to fully restart the dashboard-bearing backend (desktop app / `hermes dashboard`).
4. Verify for real: run the four bundled test scripts with the bundled venv python / any node ≥ 18
   (expect `FAILED: none`), read the `manifest:` + `registrations:` lines of `hermes plugins doctor`
   (a `WinError 32` on Windows while the plugin is live is expected, not a failure), grep the
   `Mounted plugin API routes: /api/plugins/model-audit/` log line, and confirm `meta.patch_ok = 1`
   plus a growing `calls` count with the read-only sqlite probe (§5.4).
5. The page appears in the Hermes **dashboard** sidebar right after "Analytics". Troubleshooting: §6.
