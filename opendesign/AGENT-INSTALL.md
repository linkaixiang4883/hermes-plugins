# opendesign 安装指导（写给 agent 执行）

> **给人**：把本目录整个丢给你的 agent，说一句「按 `AGENT-INSTALL.md` 把 opendesign 装上并验收」。
> **给 agent**：照 §2 → §3 → §5 顺序执行；§5 每条都要**真跑并贴真实输出**，不许用「应该没问题」收尾。

| 项 | 值 |
|---|---|
| 包版本 | `0.3.2`（与本仓库 `opendesign/` 当前文件逐字节一致，sha256 见附录 A） |
| 安装源 | 本文件所在目录 = 插件树本身，同时是 **Git 仓库的子目录**（`hermes plugins install` 可直接装，见 §3.1） |
| 安装目标 | `<HERMES_HOME>/plugins/opendesign/`（目录名 = 插件名）。⚠️ 2026-11 之前装过的可能在旧布局 `plugins/model-providers/opendesign/`，按 §2.1 第 5 条清掉旧的 |
| 插件身份 | `name: opendesign`、`kind: model-provider`、`requires_hermes: ">=0.23.1"` |
| 注册的 provider | **一个**：`opendesign`（`amr-link.open-design.ai/v1` / `OPENDESIGN_API_KEY`） |
| 派生目标 | 无。没有桌面半、没有仪表盘页、不建数据库、不写任何状态文件 |

## 1. 它是什么 / 它不做什么

**是什么**：OpenDesign Cloud（open-design.ai）的**文本模型 provider**。网关 `https://amr-link.open-design.ai/v1`
同一 base 提供 chat / responses / messages / images / models；本插件只接 **chat completions**。

**上下文、输出预算与图片模态取自 `GET /v1/models` 的 metadata**（`metadata.context_limit` /
`metadata.output_budget` / `architecture.input_modalities`），进程内缓存 10 分钟；离线或目录不可用时
才用内置快照兜底（`tests/fixtures/models.json`，2026-11-15 真 key 抓取）。模型目录**按账户套餐过滤**
（Go 拿 14 个，Plus / Pro / Max 更多）。

**上下文窗口口径**：插件实现 `get_model_context_length()`（Hermes 的 step 0d，在持久缓存 / custom-endpoint 探测 / models.dev 之前），
值取自 `/v1/models` 的 `metadata.context_limit`（小窗减 65_536）。**这一步不能省**：`hostnames` 已把 amr-link 登记为已知 provider，
Hermes 不会去探它的 `/models`；而后面的 `live_context_length` 依赖凭据或已有缓存（无 key 时返回 None），
持久缓存与 models.dev 又拿不到 `context_limit` —— 只有 step 0d 能在无凭据、无网络时稳定给出窗口，否则落到默认的 1,000,000。

**`max_tokens` 口径**：**插件不发 `max_tokens`**（`get_max_tokens()` 返回 `None`），交给服务端按模型决定 ——
与内置 `opencode-zen` / `commandcode` 的默认写法一致；Hermes 在截断时会自动加档重试（`turn_truncation`），
在「输入 + max_tokens 超窗」时会自动降档（`turn_overflow._clamp_output_cap`）。
`/models` 的 `output_budget` 仍解析出来只作观察/对账，**不进请求**（实测它不是模型上限：
deepseek-v4.1-flash 发 128k~1,048,576 都 200；OD 客户端自己用 LiteLLM 表 + 覆写，也不读该字段）。
想固定输出上限就用 `agent.max_tokens`。

**账户测试约定**：该账户只允许用 `deepseek-v4.1-flash`（或 `deepseek-v4.1-flash-eco`）做推理测试；
安装验收不要去打其它模型（`tests/probe_live.py` 已按这个限制写好，其它生图/聊天模型只读目录、不发请求）。

**不做什么**（避免 agent 自己脑补）：

- 不修改 Hermes 源码、不改 `config.yaml`、不动 `auth.json`；不建库、不写状态文件、不发遥测。
- 不接 `/responses`（思考只有被改写的摘要）与 `/messages`（`reasoning_effort` 无效、上游有「200 + 空 content」缺陷）。
- 不做生图（`/images/generations` 需要另一个 `image_gen` backend 插件）与额度芯片（控制面另需会话凭据 / `vela`）。

## 2. 前置条件核对（先做，缺哪条就停下来问用户，别硬装）

### 2.0 先定位 HERMES_HOME

```bash
hermes config path          # 打印 <HERMES_HOME>/config.yaml
HH="$(dirname "$(hermes config path)")" && echo "$HH"
```

### 2.1 逐条核对

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | Hermes ≥ 0.23.1 | `hermes --version` | 版本号 ≥ 0.23.1（低版本未验证；`requires_hermes` 只被 validate/PluginManager 检查，运行时发现链不拦） |
| 2 | `git` 可用 | `git --version` | 有输出（§3.1 需要；没有就走 §3.2 手工复制） |
| 3 | 插件目录可写 | `[ -w "$HH/plugins" ] && echo writable \|\| echo "missing-or-readonly"` | `writable` |
| 4 | **API key** | 见 §2.2 | 一把以 `sk-amr-` 开头的运行时 key（**不是**控制台/网页 cookie） |
| 5 | 没有重复安装 | `ls -d "$HH/plugins/opendesign" "$HH/plugins/model-providers/opendesign" 2>/dev/null` | **必须只命中 `plugins/opendesign`**；命中 `model-providers/opendesign` 说明是旧布局残留，删掉它（两处都在会被发现两次，后者覆盖前者） |

### 2.2 API key 从哪来 —— **停下问用户，不要让用户把 key 贴进聊天**

key 在 <https://open-design.ai/cloud/api-keys> 创建（One-click agent setup 也可以，最后核对 API Endpoint 是
`https://amr-link.open-design.ai/v1`）。两种放法，二选一：

| 放法 | 命令（用户自己执行） | 说明 |
|---|---|---|
| `.env` | 在 `$HH/.env` 里加一行 `OPENDESIGN_API_KEY=…` | 图像/视频后端只认 env；模型 provider 也支持（框架统一解析） |
| `hermes auth` | `hermes auth add opendesign` 后按提示粘贴 | 写进 `auth.json` 的凭据池，多 key 可轮换 |

> 免费层只有 `deepseek-v4.1-flash` 可用；付费套餐才有模型表里的其它 id。以 `hermes model` 里实际出现的为准。

## 3. 安装

### 3.1 来源 A（推荐）：一条命令从 Git 源安装

```bash
hermes plugins install linkaixiang4883/hermes-plugins/opendesign --enable
```

装到 `$HH/plugins/opendesign/`（目录名 = 插件名，没有中间层）。

> model-provider 由**独立发现器**加载，`plugins.enabled` 不管它；`--enable` 只是让 `hermes plugins list`
> 显示一致，加上更省心。

### 3.2 来源 B（兜底）：手工复制插件树

```bash
mkdir -p "$HH/plugins/opendesign"
cp -a <本目录>/. "$HH/plugins/opendesign/"
```

⚠️ 整仓 clone 的老副本可能仍在 `model-providers/opendesign/`；按 §2.1 第 5 条只保留一份（`$HH/plugins/opendesign/`）。

### 3.3 写 API key

见 §2.2。`.env` 在进程启动时加载，生效按 §3.4 重启。

### 3.4 重启（给用户一句话，然后等）

> 请重启承载进程：桌面 App 整进程重开（`/restart` 不够，它只重启 gateway）；`hermes dashboard` 或
> `gateway run` 则重启对应进程。重启完告诉我。

**agent 不要替用户杀/重启这些进程。**

## 4. 生效后在哪里用它

| 入口 | 怎么做 |
|---|---|
| CLI 选择器 | `hermes model` → 选 `OpenDesign Cloud`（行号随机器不同）→ 再选模型 |
| 桌面 App | 模型选择器里选 `OpenDesign Cloud`，再选模型 |
| 命令行直接跑 | `hermes -z "只回复：连接成功" --provider opendesign -m deepseek-v4.1-flash` |
| config.yaml | `model.provider: opendesign` **且** `model.default: <模型 id>`（`static_models` 为空 → 不选模型就没有默认值） |

## 5. 验收（每条都要真跑，贴真实输出；不许"应该没问题"）

### 5.1 清单与契约

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | 静态校验 | `hermes plugins validate "$HH/plugins/opendesign"` | `Validation passed.`，且**没有** `⚠ private core imports` |
| 2 | 注册 | `hermes plugins doctor opendesign` | `provider(s): opendesign`（按名解析到 `$HH/plugins/opendesign`；在仓库根执行会命中 cwd 的源码目录，两者都算通过） |
| 3 | 选择器 | `hermes model` | 出现 `OpenDesign Cloud（open-design.ai）套餐制模型网关…` 这一行 |
| 4 | 离线单测（行为） | `<venv python> "$HH/plugins/opendesign/tests/test_profile.py"` | `OK: 16 cases, FAILED: none`，退出码 0 |
| 5 | 离线单测（元数据） | `<venv python> "$HH/plugins/opendesign/tests/test_metadata.py"` | `OK: 6 cases, FAILED: none`（静态兜底表与真 `/models` 快照逐项一致） |
| 6 | 目录元数据 | `<venv python> "$HH/plugins/opendesign/tests/probe_live.py" --case models` | `status=200 count=14`，`fields=[... metadata ...]` |
| 7 | 真跑一轮（仅限 DS） | `hermes -z "只回复：连接成功" --provider opendesign -m deepseek-v4.1-flash` | 输出 `连接成功`、无 401 |

`<venv python>` = `<HERMES_HOME>/hermes-agent/venv/Scripts/python.exe`（Windows）或
`<HERMES_HOME>/hermes-agent/venv/bin/python`（macOS / Linux）。

> 可选探针 `--case tool_image`：验证网关是否接受 **list 型 tool content**（带图 tool 结果）。
> 实测 2026-11-15 `deepseek-v4.1-flash` → `status=200`，故 `supports_vision_tool_messages` 保持默认 `True`。

### 5.2 注册自检（最硬的一条：直接断言 provider 与 picker 行都在）

```bash
"<venv python>" - <<'PY'
import sys
sys.path.insert(0, "<HERMES_HOME>/hermes-agent")   # 换成实际路径
import hermes_bootstrap
from providers import get_provider_profile
from hermes_cli.models import CANONICAL_PROVIDERS
p = get_provider_profile("opendesign")
print("profile:", p.name, p.display_name, p.api_mode, p.base_url)
print("picker:", [(x.slug, x.tui_desc[:40]) for x in CANONICAL_PROVIDERS if x.slug.lower() == "opendesign"])
PY
```

期望：`profile: opendesign OpenDesign Cloud chat_completions https://amr-link.open-design.ai/v1`，
且 `picker:` 里有一行 `('opendesign', 'OpenDesign Cloud（open-design.ai）套餐制模型网关 ')`（这是 `tui_desc[:40]` 的原样输出，末尾空格来自截断，不是笔误）。

### 5.3 没 key 时的口径

`tests/probe_live.py` 在无 key 时打印 `key present: no` + `SKIP(no key)` 并退出 0。
**这不算通过**：报告里必须写 `SKIP(no key)`，不能写成「探测通过」。

## 6. 故障对照表

| 症状 | 先看哪 |
|---|---|
| `401 missing_api_key` | `.env` 的 `OPENDESIGN_API_KEY` 是否真写进**当前** `$HH/.env`；用 `hermes auth list` 看池里有没有；改 `.env` 后是否重启 |
| `402` / 额度耗尽 | 控制台额度；运行时 key 读不到额度（需要控制面会话或 `vela`）。不要反复重试 |
| `404` / 模型不存在 | 模型 id 是否在该账户目录里（`hermes model` 列表为准）；URL 不要重复写 `/v1` |
| `429` | 短时限流，等一会儿；与 402 区分开 |
| 回复为空 / 只有思考 | 思考 token 吃光预算：调小 `/reasoning` 或换非思考档；`minimax-m3.1-flash` 没有 `none`；本网关 chat 面也会出现「200 + message 空 + 计了 reasoning tokens」，可重试或换 `deepseek-v4.1-flash-eco` |
| 模型自报不是请求的型号（问身份答 `gpt-5.5` 之类） | 网关响应头只有 `x-request-id` / `cf-ray`，**没有任何模型自证头**；body 的 `model` 只是别名回声。只能当「多上游/别名路由，无自证」处理，`model-audit` 会显示 ◌ 无自证 |
| 选 `glm-5.3-flash` 报参数错 | 插件已按族 clamp（medium/high→high）；若用户手工在 `extra_body` 里另塞 `reasoning_effort`，删掉 |
| 发图报错 | `deepseek-v4-pro` / `hy4-preview` 不收图；单请求体 > 50 MiB 会被网关拒（整包，不是单图） |
| 工具读到的图模型说看不到 | `kimi-k2.7-code` 对 tool 消息里的图会答「无法读取」（模型侧差异） |
| 想要生图 | 本插件不提供；需要另装 `image_gen` backend 并把 `image_gen.provider` 切过去 |
| `hermes plugins doctor opendesign` 报 not found | 说明 `$HH/plugins/opendesign/` 不存在（还留在旧布局，或没装成）。先看 §2.1 第 5 条；必要时直接传路径 `"$HH/plugins/opendesign"` |

## 7. 卸载 / 更新

| 动作 | 命令 / 做法 |
|---|---|
| 更新（Git 安装） | `hermes plugins update opendesign` |
| 更新（手工复制） | 重新覆盖复制本目录；无 provenance，`update` 会拒绝 |
| 停用 | 把 `model.provider` 切回别的 provider（插件留在盘上不影响） |
| 卸载 | 删 `$HH/plugins/opendesign/`（若还有旧布局的 `plugins/model-providers/opendesign/`，一并删）+ 删 `__pycache__`；`hermes auth remove opendesign`；删 `.env` 里 `OPENDESIGN_API_KEY=` 那一行 |
| 数据 | 本插件不建任何数据目录 |

## 8. 红线（agent 必读）

1. **不索取 key、不代填明文、不回显**；只给用户一条命令或一行 `.env` 变量名。
2. **不改** Hermes 源码 / `config.yaml` / `auth.json`；`config.yaml` 是安全敏感文件，文件工具会拒写。
3. **不替用户重启**桌面 App / gateway / dashboard。
4. **不装两份**：`plugins/opendesign/` 与旧布局 `plugins/model-providers/opendesign/` 只能存在一个（升级用户尤其要查）。
5. **不伪造输出**：没 key 就写 `SKIP(no key)`；没跑过的命令不许贴「期望输出」冒充真实输出。

## 附录 A：文件清单与校验和

安装完在插件目录下应恰好是这 6 个文件 + 两份文档 `AGENT-INSTALL.md`、`CHANGELOG.md`（文档不参与校验；`__pycache__/` 是运行期产物）：

| 文件 | 字节 | sha256 |
|---|---|---|
| `__init__.py` | 21933 | `74ec081cd9376340349b68d301e96002b1a665befbb641fc4c41c6ab31b4e840` |
| `plugin.yaml` | 803 | `2a757d1e96c8eb1d2aec8261cabc711424420fa4560df542019ddce4e1b9b765` |
| `tests/test_profile.py` | 16900 | `02a32c7e7c98fbf1f61e105e66c8585f40e29d422ee7518a97beb18502d82edb` |
| `tests/test_metadata.py` | 4282 | `67f376cc033e5d2b5089efcf8849c1d2985c81f544298ed26e8b66c1b44f3b44` |
| `tests/probe_live.py` | 10233 | `56192bc96df757f6c9992c01d2cb82a323902a57da4addf54f171a3cb3c45cd9` |
| `tests/fixtures/models.json` | 6210 | `2d3468704ced009632ad910aef730dbadfbe57088dceba1227245d17d619f64c` |

自查（LF 口径；Windows 上用 git-bash）：

```bash
cd "<插件目录>" && find . -type f -not -name 'AGENT-INSTALL.md' -not -name 'CHANGELOG.md' -not -path '*__pycache__*' -print0 | xargs -0 sha256sum | sort
```

> `tests/fixtures/models.json` 是 2026-11-15 真 key 抓取的 14 模型快照，已随插件分发（离线兜底用）。

---

## 附录 B：English TL;DR

`opendesign` is a Hermes **model-provider** plugin for OpenDesign Cloud. It registers one provider,
`opendesign`, pointing at `https://amr-link.open-design.ai/v1` (OpenAI-compatible chat completions),
authenticated by a runtime key in `OPENDESIGN_API_KEY` (or `hermes auth add opendesign`).

Install with `hermes plugins install linkaixiang4883/hermes-plugins/opendesign --enable`
(lands in `<HERMES_HOME>/plugins/opendesign/`), put the key in `.env`, then **restart the hosting process**.
Verify with `hermes plugins validate <dir>`, `hermes plugins doctor <dir>` (by name once installed flat, or a path), and a real
`hermes -z "只回复：连接成功" --provider opendesign -m deepseek-v4.1-flash`.

Only the **chat completions** surface is wired. Responses is skipped (thinking comes back as a rewritten
summary) and Messages is skipped (`reasoning_effort` is ineffective there and the gateway has a known
"HTTP 200 with empty content" defect). Image generation and plan quota need separate plugins. The model
catalog is account-tier filtered; `deepseek-v4.1-flash` is the one model every plan can call.
