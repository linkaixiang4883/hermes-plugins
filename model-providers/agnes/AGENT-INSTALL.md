# agnes 安装指导（写给 agent 执行）

> **给人**：把本目录整个丢给你的 agent，说一句「按 `AGENT-INSTALL.md` 把 agnes 装上并验收」。
> **给 agent**：照 §2 → §3 → §5 顺序执行。§5 每条都要**真跑并贴真实输出**，不许用「应该没问题」收尾。

| 项 | 值 |
|---|---|
| 包版本 | `1.1.0`（与本仓库 `model-providers/agnes/` 当前文件逐字节一致，sha256 见附录 A） |
| 安装源 | 本文件所在目录 = 插件树本身，同时是 **Git 仓库的子目录**（`hermes plugins install` 可直接装，见 §3.1） |
| 安装目标 | `<HERMES_HOME>/plugins/agnes/` —— ⚠️ **会被扁平化**，**不是** `plugins/model-providers/agnes/` |
| 插件身份 | `name: agnes`、`kind: model-provider`、声明 `requires_hermes: ">=0.21.6"` |
| 注册的 provider | **两个**（一个插件注册两个 provider，形态同内置 `opencode-zen`）：`agnes`（国际站 apihub.agnes-ai.com / `AGNES_API_KEY`）与 `agnes-cn`（国内站 api.agnes-ai.cn / `AGNES_CN_API_KEY`） |
| 派生目标 | 无。没有桌面半、没有仪表盘页、不建数据库、不写任何状态文件 |

## 1. 它是什么 / 它不做什么

**是什么**：Agnes AI（Sapiens AI）的**文本模型 provider**，一次提供国际站与国内站两个 provider。
两家模型集一致：`agnes-3.0-flash` / `agnes-2.5-flash`（512K 上下文，免费促销中）、
`agnes-2.5-pro`（1M 上下文，reasoning，付费）、`agnes-2.5-pro-beta`、`agnes-3.0-pro`。
上游是 OpenAI 兼容接口，支持 vision、tool calling 与 thinking 模式
（账本里的 `agnes-2.0-flash` **已废弃**，文档明确「请勿继续作为兼容回退」，本插件不含）。

**不做什么**（避免 agent 自己脑补）：

- 不修改 Hermes 源码、不改 `config.yaml`、不动 `auth.json`。
- 不读写任何 Hermes 内部数据库；只在 `import` 时往 `agent.model_metadata` 的上下文缓存里写几条
  `(model, base_url) → context_window`（幂等，`save_context_length`；失败静默忽略）。
- 不发遥测、不上传任何数据；只从环境变量读 API key，key 不打印、不落盘、不进日志。

> **为什么"一个插件两个 provider"**：Hermes **没有** variant / 子选择概念，多区域只能靠
> 「一个 `register_provider()` 调多次」（provider 类插件）或「`register()` 里注册多个 provider」
> （backend 类插件）实现。所以选择器里它们是**两个并列条目**，不是某个条目下的子选项。
> 这不是配置重复，别试图"合并"掉其中一个。

## 2. 前置条件核对（先做，缺哪条就停下来问用户，别硬装）

### 2.0 先定位 HERMES_HOME

```bash
hermes config path          # 打印 <HERMES_HOME>/config.yaml
HH="$(dirname "$(hermes config path)")" && echo "$HH"
```

### 2.1 逐条核对

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | Hermes ≥ 0.21.6 | `hermes --version` | 版本号 ≥ 0.21.6（`plugin.yaml` 里有 `requires_hermes`，不满足会被**干净跳过**） |
| 2 | `git` 可用 | `git --version` | 有输出（§3.1 需要；没有就走 §3.2 手工复制） |
| 3 | 插件目录可写 | `ls -d "$HH/plugins"` | 存在且可写 |
| 4 | **API key** | 见 §2.2 | 至少有一把（国际站 / 国内站） |

### 2.2 API key 从哪来 —— **停下问用户，不要让用户把 key 贴进聊天**

两把 key 对应两个站点，**只用一家就只填一把**：

| provider | 站点 | 环境变量 | 去哪申请 |
|---|---|---|---|
| `agnes` | 国际站 apihub.agnes-ai.com | `AGNES_API_KEY` | https://agnes-ai.com/ |
| `agnes-cn` | 国内站 api.agnes-ai.cn | `AGNES_CN_API_KEY` | https://platform.agnes-ai.cn/ |

**key 放哪（本插件已实测）**：本插件是**模型 provider**，provider 名（含别名）**在 Hermes 的凭据注册表里**（`hermes auth list` 能看到 `agnes` / `agnes-cn`）。所以两处都行：
① 写 `$HH/.env`（本节做法）；② `hermes auth add agnes --api-key <key>` 交给凭据池管。
两种都会被框架采用 —— 池里那两条凭据的来源就是 `env:AGNES_API_KEY` / `env:AGNES_CN_API_KEY`。

用户把 key 填进 `$HH/.env`（§3.3 给命令）。**agent 只负责写占位行 / 检查是否已存在，不要索取 key 明文**。

## 3. 安装（标准 Git 安装：一条命令；手工复制作兜底）

### 3.1 来源 A（推荐）：一条命令从 Git 源安装

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-providers/agnes --enable
```

**装固定版本**（`--ref` 只接受完整 40 位 commit SHA，不接受 tag 名）：

```bash
git ls-remote https://github.com/linkaixiang4883/hermes-plugins.git refs/heads/main
hermes plugins install linkaixiang4883/hermes-plugins/model-providers/agnes --ref <40位SHA> --enable
```

**从本机源码装**（本目录已是仓库子目录；在仓库根目录执行）：

```bash
# macOS / Linux
hermes plugins install "file://$PWD#model-providers/agnes" --enable
```

```powershell
# Windows（pwsh）—— file:// 必须两斜杠，三斜杠会被 Git for Windows 解析失败（实测）
hermes plugins install "file://C:/path/to/hermes-plugins#model-providers/agnes" --enable
```

> 首次装会打一行 `custom (unreviewed) source` 警告 —— 不在官方 catalog 里都这样，不是错误。

### 3.2 来源 B（兜底）：手工复制插件树

没有 `git` / 完全离线时：

```bash
mkdir -p "$HH/plugins" && cp -r <本目录> "$HH/plugins/agnes"
```

⚠️ 目标目录名必须是 **`agnes`**（= `plugin.yaml` 的 `name`），不是 `model-providers/agnes`。

### 3.3 写 API key 到 `$HH/.env`

```bash
grep -q '^AGNES_API_KEY=' "$HH/.env" 2>/dev/null || echo 'AGNES_API_KEY=' >> "$HH/.env"
grep -q '^AGNES_CN_API_KEY=' "$HH/.env" 2>/dev/null || echo 'AGNES_CN_API_KEY=' >> "$HH/.env"
```

然后**请用户**把两行的 `=` 后面补上真实 key（只用一家的另一行留空即可）。
补完检查（只确认非空，**不要**打印值）：

```bash
awk -F= '/^AGNES_API_KEY=|AGNES_CN_API_KEY=/ {print $1"=" ($2=="" ? "(空)" : "(已填, " length($2) " 字符)")}' "$HH/.env"
```

### 3.4 启用 + 重启（给用户一句话，然后等）

```bash
hermes plugins enable agnes       # 若 §3.1 已带 --enable 则会提示已启用
```

**请用户重启承载进程**才生效（provider 注册表**每个进程只发现一次**）：

- 桌面端 App（Electron）
- `hermes dashboard`（若在跑）
- `gateway run`（若在跑）

> 不重启不会坏，只是新插件/新版本还没进内存。**等用户确认重启完**再做 §5.3。

## 4. 生效后在哪里用它

在 `hermes model` 里选 **`agnes`**（国际站）或 **`agnes-cn`**（国内站）——
两个**并列条目**，同理不是配置重复。选完 `hermes model` 会把它写进 `config.yaml` 的
`model.provider`；也可以直接 `hermes model agnes`（或 `agnes-cn`）非交互式切换。

**四条路等价**（改的都是 `model.provider`）：`hermes model`（命令行）/ dashboard 的 **Models 页** /
桌面端 App 的模型选择器 / 直接改 `config.yaml`。

上下文窗口由插件的 `model_capabilities` **正式声明**（flash 512K / `2.5-pro` 1M），
所以不会掉回 models.dev 的 200k 兜底 —— 这正是本插件存在的理由之一。

## 5. 验收（每条都要真跑，贴真实输出；不许"应该没问题"）

### 5.1 清单与契约

```bash
hermes plugins list | grep -i agnes                 # 期望：enabled，版本 1.1.0
hermes plugins validate "$HH/plugins/agnes"          # 期望：Validation passed
hermes plugins doctor  "$HH/plugins/agnes"           # 期望：OK: runtime discovery, manifest parsing, import, and registration passed
```

### 5.2 注册自检（最硬的一条：直接断言"两个 provider 都注册了"）

用 Hermes 自己的解释器跑（Windows 是 `Scripts/python.exe`，macOS/Linux 是 `bin/python`）：

```bash
PY="$HH/hermes-agent/venv/Scripts/python.exe"     # Windows
# PY="$HH/hermes-agent/venv/bin/python"           # macOS / Linux
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
"$PY" - "$HH" <<'PYEOF'
import importlib.util, pathlib, sys
HH = pathlib.Path(sys.argv[1])          # 由外层命令传入 $HH
sys.path.insert(0, str(HH / "hermes-agent"))
spec_path = HH / "plugins" / "agnes" / "__init__.py"      # 扁平安装（hermes plugins install 的落点）
if not spec_path.is_file():                                   # 兜底：手工放在分类子目录里的形态
    cand = sorted(HH.glob("plugins/*/agnes/__init__.py"))
    assert cand, "找不到 agnes/__init__.py（既不在 plugins/agnes/，也不在 plugins/*/agnes/）"
    spec_path = cand[0]
spec = importlib.util.spec_from_file_location("p", spec_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
from providers import get_provider_profile
for name, base, env in [("agnes", "https://apihub.agnes-ai.com/v1", "AGNES_API_KEY"), ("agnes-cn", "https://api.agnes-ai.cn/v1", "AGNES_CN_API_KEY")]:
    p = get_provider_profile(name)
    assert p is not None, f"{name} 没注册上"
    assert p.base_url == base, f"{name} base_url={p.base_url} 期望 {base}"
    assert tuple(p.env_vars) == (env,), f"{name} env_vars={p.env_vars} 期望 {env}"
    print(f"  ✅ {name}: {p.base_url}  env={env}")
ctx = tuple(get_provider_profile(n).model_capabilities.get("agnes-3.0-flash", {}) for n in ("agnes", "agnes-cn"))
print("  ✅ 上下文声明:", [c.get("context_window") for c in ctx])
print("OK: 两个 provider 均注册，base_url / env 与文档一致")
PYEOF
```

> 这条**不依赖重启**（在新进程里直接 import 插件模块），所以它能区分「插件本身坏了」和
> 「进程还没重启」——重启后仍不过，才是真问题。

### 5.3 重启后确认（等用户确认已重启再跑）

```bash
hermes plugins list | grep -i agnes      # 期望 Status = enabled，Version = 1.1.0
```


## 6. 故障对照表

| 症状 | 原因 | 处理 |
|---|---|---|
| `hermes plugins list` 里**根本没有** `agnes` | 没装进去 / 目录名不对 | 确认 `$HH/plugins/agnes/plugin.yaml` 存在；目录名必须是 `agnes`（不是 `model-providers/agnes`） |
| 显示 `disabled` 或缺 `enabled` | 白名单没写 | `hermes plugins enable agnes`（`config.yaml` 是安全敏感文件，**不要**手工改，用 CLI） |
| 显示 `requires hermes >=0.21.6, running X.Y.Z` + `0 tool(s), 0 hook(s)` | 版本门控**干净跳过**（无 traceback） | 升级 Hermes；或按 §3.1 装匹配的旧版本插件 |
| `doctor` 报 `import` 失败 | 依赖符号变动 / 包不完整 | 贴出报错全文；确认 ``providers.register_provider` / `providers.base.ProviderProfile` 在 v0.21.6 起存在` |
| 重启后验收 §5.2 过了、但功能仍不可用 | key 没填 / 填错站点 | 回 §3.3 检查（只查非空，别打印值）；确认 `只用一家时另一把留空即可（插件不会因为缺 key 而加载失败，只是那个 provider 用不了）` |
| 装完目录在 `plugins/model-providers/agnes/` 而不是 `plugins/agnes/` | 装法错了（手抄路径没扁平化） | 移正：`mv "$HH/plugins/model-providers/agnes" ...` 不适用——**删掉重装**（§3.1 或 §3.2 目标名写对） |

## 7. 卸载 / 更新

```bash
hermes plugins update  agnes     # 有新版则重装到最新，没有则答 "already up to date"
hermes plugins disable agnes     # 停用（不删文件）
hermes plugins remove  agnes     # 连目录一起删
```

本插件**不产生任何数据文件**，所以 `remove` 没有需要保留的东西。
（注意用**插件名** `agnes`；`agnes` / `agnes-cn` 是 **provider id**，出现在 `hermes model` 的选择列表 / `config.yaml` 的 `model.provider` 里，别混。）

> `update` 同时就是"检查更新"：有新版会打印 `Re-installed from <源>: 旧..新`，没有则 `already up to date`。
> ⚠️ 只在**按 §3.1 用 `install` 装的**上面有效；**§3.2 手工复制**的没有装源记录，`update` 会拒绝
> （`Plugin 'X' was not installed from git … Cannot update.`）—— 那种情况要更新就重跑一次 §3.1/§3.2。
> ⚠️ `hermes plugins check-updates` 看不到本插件的版本号（本仓库是一个仓库放多个插件，"子目录安装"的目录里没有 `.git`，
> 而那条命令要靠 `.git` 比版本）；要确认有没有新版，用 `update` 或让 agent 去比对仓库里的 `plugin.yaml`。

## 8. 红线（agent 必读）

1. **不要索取、不要打印、不要代填 API key** —— 让用户自己写进 `$HH/.env`；本说明书只检查"非空"。
2. **不要改 `config.yaml` / `auth.json` / `hermes-agent/` 下的任何文件**；本插件只新增它自己的目录。
3. **不要改插件源码**（改了 sha256 就对不上，见附录 A）；需要改就先问维护者。
4. **不要绕过版本门控**（删 `requires_hermes` 之类）—— 门控是保护，跳过后坏了没人能帮你定位。
5. 装不上 / 验收不过就**如实报告 + 贴 §6 的排查结果**，不要用"应该可以了"收尾，也不要伪造输出。

---

## 附录 A：文件清单与校验和

安装完在 `$HH/plugins/agnes/` 下应恰好是这 2 个文件 + 本说明书 `AGENT-INSTALL.md`（说明书不参与校验；`__pycache__/` 是运行期产物）：

| 文件 | 字节 | sha256 |
|---|---|---|
| `__init__.py` | 8141 | `498332ee208b5bb0f199ca0d4a5630f6e20a1bd77c06aa770204e811eff6b279` |
| `plugin.yaml` | 1312 | `6dec9bb21b503af393a6d2b86bd1a957373b3e0d05c117660988e1902eea88eb` |

自查（可选）：

```bash
cd "$HH/plugins/agnes" && find . -type f -not -name 'AGENT-INSTALL.md' -not -path '*__pycache__*' -print0 | xargs -0 sha256sum | sort
```

---

## 附录 B：English TL;DR

`agnes` is a Hermes **model-provider** plugin that registers **two** providers in one plugin (same shape as
the bundled `opencode-zen`): `agnes` (international endpoint, `AGNES_API_KEY`) and `agnes-cn` (domestic endpoint, `AGNES_CN_API_KEY`). Hermes has no variant/sub-selection
concept, so they appear as **two side-by-side entries**, not as a sub-choice.

Install with `hermes plugins install linkaixiang4883/hermes-plugins/model-providers/agnes --enable`, put the API
key(s) in `<HERMES_HOME>/.env` (AGNES_API_KEY / AGNES_CN_API_KEY; only one is required if you use a single region),
then **restart the hosting process** (desktop app / `hermes dashboard` / `gateway run`) — the provider
registry is discovered once per process. Verify with `hermes plugins doctor`, plus the inline probe in
§5.2. No telemetry, no Hermes source modification, no state files, no keys touched beyond reading the
two env vars.
