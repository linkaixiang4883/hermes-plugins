# agnes-image 安装指导（写给 agent 执行）

> **给人**：把本目录整个丢给你的 agent，说一句「按 `AGENT-INSTALL.md` 把 agnes-image 装上并验收」。
> **给 agent**：照 §2 → §3 → §5 顺序执行。§5 每条都要**真跑并贴真实输出**，不许用「应该没问题」收尾。

| 项 | 值 |
|---|---|
| 包版本 | `1.2.0`（与本仓库 `image_gen/agnes-image/` 当前文件逐字节一致，sha256 见附录 A） |
| 安装源 | 本文件所在目录 = 插件树本身，同时是 **Git 仓库的子目录**（`hermes plugins install` 可直接装，见 §3.1） |
| 安装目标 | `<HERMES_HOME>/plugins/agnes-image/` —— ⚠️ **会被扁平化**，**不是** `plugins/image_gen/agnes-image/` |
| 插件身份 | `name: agnes-image`、`kind: backend`、声明 `requires_hermes: ">=0.21.6"` |
| 注册的 provider | **两个**（一个插件注册两个 provider，形态同内置 `opencode-zen`）：`agnes-image`（国际站 / `AGNES_API_KEY`）与 `agnes-cn-image`（国内站 / `AGNES_CN_API_KEY`） |
| 派生目标 | 无。没有桌面半、没有仪表盘页、不建数据库、不写任何状态文件 |

## 1. 它是什么 / 它不做什么

**是什么**：Agnes AI 的**图像生成后端**（`kind: backend`），一次提供国际站与国内站两个 provider。
支持文生图、图生图与多图合成（`POST /v1/images/generations`，OpenAI 兼容）。
模型：`agnes-image-2.5-flash`（默认）/ `2.1-flash`；**国际站另有 `2.0-flash`**
（国内站的 `/v1/models` 不返回它，故国内站清单里没有）。

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
| `agnes-image` | 国际站 apihub.agnes-ai.com | `AGNES_API_KEY` | https://agnes-ai.com/ |
| `agnes-cn-image` | 国内站 api.agnes-ai.cn | `AGNES_CN_API_KEY` | https://platform.agnes-ai.cn/ |

**key 放哪（本插件已实测）**：本插件是**生成后端**，provider id（`agnes-image` / `agnes-cn-image`）**不在** Hermes 的凭据注册表里 —— 实测 `hermes auth add agnes-image` 直接回 `Unknown provider`。
所以 key **只能写 `$HH/.env`**（本节做法），不能用 `hermes auth` 管。

用户把 key 填进 `$HH/.env`（§3.3 给命令）。**agent 只负责写占位行 / 检查是否已存在，不要索取 key 明文**。

## 3. 安装（标准 Git 安装：一条命令；手工复制作兜底）

### 3.1 来源 A（推荐）：一条命令从 Git 源安装

```bash
hermes plugins install linkaixiang4883/hermes-plugins/image_gen/agnes-image --enable
```

**装固定版本**（`--ref` 只接受完整 40 位 commit SHA，不接受 tag 名）：

```bash
git ls-remote https://github.com/linkaixiang4883/hermes-plugins.git refs/heads/main
hermes plugins install linkaixiang4883/hermes-plugins/image_gen/agnes-image --ref <40位SHA> --enable
```

**从本机源码装**（本目录已是仓库子目录；在仓库根目录执行）：

```bash
# macOS / Linux
hermes plugins install "file://$PWD#image_gen/agnes-image" --enable
```

```powershell
# Windows（pwsh）—— file:// 必须两斜杠，三斜杠会被 Git for Windows 解析失败（实测）
hermes plugins install "file://C:/path/to/hermes-plugins#image_gen/agnes-image" --enable
```

> 首次装会打一行 `custom (unreviewed) source` 警告 —— 不在官方 catalog 里都这样，不是错误。

### 3.2 来源 B（兜底）：手工复制插件树

没有 `git` / 完全离线时：

```bash
mkdir -p "$HH/plugins" && cp -r <本目录> "$HH/plugins/agnes-image"
```

⚠️ 目标目录名必须是 **`agnes-image`**（= `plugin.yaml` 的 `name`），不是 `image_gen/agnes-image`。

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
hermes plugins enable agnes-image       # 若 §3.1 已带 --enable 则会提示已启用
```

**请用户重启承载进程**才生效（provider 注册表**每个进程只发现一次**）：

- 桌面端 App（Electron）
- `hermes dashboard`（若在跑）
- `gateway run`（若在跑）

> 不重启不会坏，只是新插件/新版本还没进内存。**等用户确认重启完**再做 §5.3。

## 4. 生效后在哪里用它

在 `config.yaml` 里指定用哪个 provider id：

```yaml
image_gen:
  provider: agnes-image        # 或 agnes-cn-image
```

生成出来的图片落在 `<HERMES_HOME>/cache/images/`（`save_b64_image` / `save_url_image`）。

## 5. 验收（每条都要真跑，贴真实输出；不许"应该没问题"）

### 5.1 清单与契约

```bash
hermes plugins list | grep -i agnes-image                 # 期望：enabled，版本 1.2.0
hermes plugins validate "$HH/plugins/agnes-image"          # 期望：Validation passed
hermes plugins doctor  "$HH/plugins/agnes-image"           # 期望：OK: runtime discovery, manifest parsing, import, and registration passed
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
spec_path = HH / "plugins" / "agnes-image" / "__init__.py"      # 扁平安装（hermes plugins install 的落点）
if not spec_path.is_file():                                   # 兜底：手工放在分类子目录里的形态
    cand = sorted(HH.glob("plugins/*/agnes-image/__init__.py"))
    assert cand, "找不到 agnes-image/__init__.py（既不在 plugins/agnes-image/，也不在 plugins/*/agnes-image/）"
    spec_path = cand[0]
spec = importlib.util.spec_from_file_location("p", spec_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class Ctx:  # 假 ctx：只收集注册结果，不碰真注册表
    def __init__(self): self.got = []
    def __getattr__(self, item):
        if item.startswith("register_"):
            return lambda p=None, *a, **k: self.got.append(p) if p is not None else None
        raise AssertionError(f"插件调用了未预期的 ctx.{item}()")

ctx = Ctx(); mod.register(ctx)
by = {p.name: p for p in ctx.got if p is not None}
assert set(by) == {n for n, *_ in [("agnes-image", "Agnes AI (Intl)", "AGNES_API_KEY", "https://apihub.agnes-ai.com/v1"), ("agnes-cn-image", "Agnes AI (CN)", "AGNES_CN_API_KEY", "https://api.agnes-ai.cn/v1")]}, f"注册到的 provider={sorted(by)}"
for name, display, env, base in [("agnes-image", "Agnes AI (Intl)", "AGNES_API_KEY", "https://apihub.agnes-ai.com/v1"), ("agnes-cn-image", "Agnes AI (CN)", "AGNES_CN_API_KEY", "https://api.agnes-ai.cn/v1")]:
    p = by[name]
    assert p.display_name == display, f"{name} display_name={p.display_name}"
    assert p.ENV_VAR == env, f"{name} ENV_VAR={p.ENV_VAR}"
    assert p.API_BASE == base, f"{name} API_BASE={p.API_BASE}"
    k = [e["key"] for e in p.get_setup_schema()["env_vars"]]
    assert k == [env], f"{name} setup_schema key={k}"
    print(f"  ✅ {name}: {p.API_BASE}  env={env}  models={[m['id'] for m in p.list_models()]}")
print("OK: 两个 provider 均注册，base_url / env / 模型清单与文档一致")
PYEOF
```

> 这条**不依赖重启**（在新进程里直接 import 插件模块），所以它能区分「插件本身坏了」和
> 「进程还没重启」——重启后仍不过，才是真问题。

### 5.3 重启后确认（等用户确认已重启再跑）

```bash
hermes plugins list | grep -i agnes-image      # 期望 Status = enabled，Version = 1.2.0
```


## 6. 故障对照表

| 症状 | 原因 | 处理 |
|---|---|---|
| `hermes plugins list` 里**根本没有** `agnes-image` | 没装进去 / 目录名不对 | 确认 `$HH/plugins/agnes-image/plugin.yaml` 存在；目录名必须是 `agnes-image`（不是 `image_gen/agnes-image`） |
| 显示 `disabled` 或缺 `enabled` | 白名单没写 | `hermes plugins enable agnes-image`（`config.yaml` 是安全敏感文件，**不要**手工改，用 CLI） |
| 显示 `requires hermes >=0.21.6, running X.Y.Z` + `0 tool(s), 0 hook(s)` | 版本门控**干净跳过**（无 traceback） | 升级 Hermes；或按 §3.1 装匹配的旧版本插件 |
| `doctor` 报 `import` 失败 | 依赖符号变动 / 包不完整 | 贴出报错全文；确认 ``agent.image_gen_provider` 的 `ImageGenProvider` 及 `ctx.register_image_gen_provider` 在 v0.21.6 起存在` |
| 重启后验收 §5.2 过了、但功能仍不可用 | key 没填 / 填错站点 | 回 §3.3 检查（只查非空，别打印值）；确认 `只用一家时另一把留空即可（另一个 provider 会 `is_available() == False`，但不影响这个）` |
| 装完目录在 `plugins/image_gen/agnes-image/` 而不是 `plugins/agnes-image/` | 装法错了（手抄路径没扁平化） | 移正：`mv "$HH/plugins/image_gen/agnes-image" ...` 不适用——**删掉重装**（§3.1 或 §3.2 目标名写对） |

## 7. 卸载 / 更新

```bash
hermes plugins update  agnes-image     # Git 安装的：拉最新
hermes plugins disable agnes-image     # 停用（不删文件）
hermes plugins remove  agnes-image     # 连目录一起删
```

本插件**不产生任何数据文件**，所以 `remove` 没有需要保留的东西。
（注意用**插件名** `agnes-image`；`agnes-image` / `agnes-cn-image` 是 **provider id**，出现在 `config.yaml` 的 `image_gen.provider` 里，别混。）

## 8. 红线（agent 必读）

1. **不要索取、不要打印、不要代填 API key** —— 让用户自己写进 `$HH/.env`；本说明书只检查"非空"。
2. **不要改 `config.yaml` / `auth.json` / `hermes-agent/` 下的任何文件**；本插件只新增它自己的目录。
3. **不要改插件源码**（改了 sha256 就对不上，见附录 A）；需要改就先问维护者。
4. **不要绕过版本门控**（删 `requires_hermes` 之类）—— 门控是保护，跳过后坏了没人能帮你定位。
5. 装不上 / 验收不过就**如实报告 + 贴 §6 的排查结果**，不要用"应该可以了"收尾，也不要伪造输出。

---

## 附录 A：文件清单与校验和

安装完在 `$HH/plugins/agnes-image/` 下应恰好是这 2 个文件 + 本说明书 `AGENT-INSTALL.md`（说明书不参与校验；`__pycache__/` 是运行期产物）：

| 文件 | 字节 | sha256 |
|---|---|---|
| `__init__.py` | 13585 | `0c292eff3d3dc9742974e75009cb8ca42bf793784da25a763e027353942731d3` |
| `plugin.yaml` | 796 | `deab421f614010925fbdabdaa395f33fd08aaf6a867af61216155fe54158bec9` |

自查（可选）：

```bash
cd "$HH/plugins/agnes-image" && find . -type f -not -name 'AGENT-INSTALL.md' -not -path '*__pycache__*' -print0 | xargs -0 sha256sum | sort
```

---

## 附录 B：English TL;DR

`agnes-image` is a Hermes **backend** plugin that registers **two** providers in one plugin (same shape as
the bundled `opencode-zen`): `agnes-image` (international, `AGNES_API_KEY`, also serves `agnes-image-2.0-flash`) and `agnes-cn-image` (domestic, `AGNES_CN_API_KEY`, no 2.0-flash). Hermes has no variant/sub-selection
concept, so they appear as **two side-by-side entries**, not as a sub-choice.

Install with `hermes plugins install linkaixiang4883/hermes-plugins/image_gen/agnes-image --enable`, put the API
key(s) in `<HERMES_HOME>/.env` (AGNES_API_KEY / AGNES_CN_API_KEY; only one is required if you use a single region),
then **restart the hosting process** (desktop app / `hermes dashboard` / `gateway run`) — the provider
registry is discovered once per process. Verify with `hermes plugins doctor`, plus the inline probe in
§5.2. No telemetry, no Hermes source modification, no state files, no keys touched beyond reading the
two env vars.
