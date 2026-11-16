# hermes-plugins

[![Hermes](https://img.shields.io/badge/Hermes-%E2%89%A5%200.21.6-6e56cf?style=flat-square)](https://github.com/NousResearch/hermes-agent)
![plugins](https://img.shields.io/badge/plugins-6-2f81f7?style=flat-square)
![docs](https://img.shields.io/badge/%E6%AF%8F%E6%8F%92%E4%BB%B6-AGENT--INSTALL%20%2B%20CHANGELOG-3fb950?style=flat-square)

> 六个自建 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 插件：一个模型对账台、一个套餐用量芯片、Agnes AI 的文本 / 图像 / 视频，以及 OpenDesign Cloud 网关。
> 一仓多插件，**每个都能单独装**，互不依赖。

[插件一览](#插件一览) • [快速开始](#快速开始) • [配置](#配置) • [通过-agent-安装](#通过-agent-安装) • [更新与卸载](#更新与卸载) • [已知限制](#已知限制) • [安全边界](#安全边界) • [故障排查](#故障排查) • [项目结构](#项目结构)

## 插件一览

| 插件 | 类型 | 一句话 | 需要 key | 版本 |
|---|---|---|---|---|
| [`model-audit`](model-audit/) | 仪表盘页 | 逐次记录「请求 alias → 上游实际 model / 端点」，对账掉包、降级、换路由；支持认可绿标与 trace id 追溯 | 否 | `0.4.2` |
| [`opencode-go-usage`](opencode-go-usage/) | 桌面状态栏 | OpenCode Go / Command Code GOAT 的 5h / 周 / 月用量，只在使用这两家模型时出现 | 是 | `1.2.2` |
| [`agnes`](agnes/) | 模型 provider | 国际站 `agnes` + 国内站 `agnes-cn`；`agnes-3.0-flash` / `agnes-2.5-flash`（512K，免费）与 `agnes-2.5-pro`（1M，reasoning） | 是 | `1.1.0` |
| [`agnes-image`](agnes-image/) | 生成后端 | 文生图 / 图生图 / 多图合成，国际站 `agnes-image` + 国内站 `agnes-cn-image` | 是 | `1.2.2` |
| [`agnes-video`](agnes-video/) | 生成后端 | 文生视频 / 图生视频 / 关键帧动画，异步任务 + 轮询；`agnes-video-2.5` / `2.5-flash` | 是 | `1.3.2` |
| [`opendesign`](opendesign/) | 模型 provider | OpenDesign Cloud 套餐网关（`amr-link.open-design.ai/v1`）；chat completions 主路径，上下文 / 输出 / 图片模态取自 `/v1/models` | 是 | `0.3.2` |

`requires_hermes`：前 5 个 **≥ 0.21.6**，`opendesign` **≥ 0.23.1**。版本真源是各插件 `plugin.yaml` 的 `version`。

> [!NOTE]
> 三个 agnes 插件各自注册**两个 provider**（国际站 + 国内站），所以在选择器里是**两个并列条目**。
> Hermes 没有「子选项」这种形式，这是设计如此，不是重复配置。

> [!IMPORTANT]
> 每个插件目录都带两份文档：**`AGENT-INSTALL.md`**（前置核对 → 安装 → 验收 → 故障对照表）和 **`CHANGELOG.md`**（逐版变更）。
> 想知道「装的是不是最新 / 这版改了什么」，看这两份，不要靠猜。

## 快速开始

前置：机器上有 `git`；Hermes 版本满足上表。六个插件走同一条命令形态：

```bash
# 两个工具
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --enable
hermes plugins install linkaixiang4883/hermes-plugins/opencode-go-usage --enable

# Agnes 三件套（需要 key，见「配置」）
hermes plugins install linkaixiang4883/hermes-plugins/agnes --enable
hermes plugins install linkaixiang4883/hermes-plugins/agnes-image --enable
hermes plugins install linkaixiang4883/hermes-plugins/agnes-video --enable

# OpenDesign Cloud
hermes plugins install linkaixiang4883/hermes-plugins/opendesign --enable
```

> [!WARNING]
> **装完必须重启承载插件的进程**：桌面端 App（整进程重开，`/restart` 不够）、`hermes dashboard` 或 `gateway run`。
> 不重启的话，选择器里看不到新注册的 provider，页面 / 接口也可能 404。

> [!TIP]
> **验收三步**：`hermes plugins list` 看到 `enabled` 与正确版本 → `hermes plugins doctor <插件名>` 打出
> `OK: runtime discovery, manifest parsing, import, and registration passed` → 模型 provider 再发一次真请求
> （如 `hermes -z "只回复：连接成功" --provider opendesign -m deepseek-v4.1-flash`）。

> [!TIP]
> **从本地源码装**（仓库已 clone，在仓库根执行）：`hermes plugins install "file://$PWD#model-audit" --enable`
> （Windows 用 `file://C:/path/to/hermes-plugins#model-audit`，`file://` 必须两斜杠）。
> **完全离线**：把插件目录复制到 `<HERMES_HOME>/plugins/<插件名>/`，再 `hermes plugins enable <插件名>` ——
> 这样装的没有装源记录，之后 `update` 会拒绝它（想能更新就用 `install`）。

## 配置

运行时 key 一律写进 `<HERMES_HOME>/.env`（模型 provider 也可交给框架的凭据池）：

| 变量 | 用于 | 备注 |
|---|---|---|
| `AGNES_API_KEY` | `agnes` / `agnes-image` / `agnes-video` 国际站 | 也可 `hermes auth add agnes` |
| `AGNES_CN_API_KEY` | 国内站 `agnes-cn` / `agnes-cn-image` / `agnes-cn-video` | 也可 `hermes auth add agnes-cn` |
| `OPENDESIGN_API_KEY` | `opendesign` | `sk-amr-` 开头的**运行时** key，不是控制台 cookie |
| `OPENCODE_GO_API_KEY` | `opencode-go-usage` | 或 `hermes auth add opencode-go` |
| `COMMANDCODE_API_KEY` | 同上（GOAT） | 别名 `COMMAND_CODE_API_KEY` |

**图像 / 视频后端只认 `.env`**：它们的 provider id 不在凭据注册表里，`hermes auth add agnes-image` 会回 `Unknown provider`。

装好后把它选上（改的都是配置键，命令行 / Dashboard / 桌面端 / 直接改 config 四条路等价）：

| 要选的 | 命令 | 配置键 |
|---|---|---|
| 模型 | `hermes model`（交互式选择器） | `model.provider: agnes` / `agnes-cn` / `opendesign` |
| 图像 | `hermes tools` → Image Generation | `image_gen.provider: agnes-image`（国内站 `agnes-cn-image`） |
| 视频 | `hermes tools enable video_gen`，再 `hermes tools` → Video Generation | `video_gen.provider: agnes-video`（国内站 `agnes-cn-video`） |

> [!TIP]
> 脚本里可用 `hermes config set model.provider agnes`；`hermes model` 本身**没有位置参数**。
> 视频生成默认关闭，不先 `hermes tools enable video_gen` 就选不到任何视频后端。

## 通过 Agent 安装

不想自己敲命令？把下面这句**整句复制**给任意 Hermes Agent，它会照该插件的 `AGENT-INSTALL.md` 走完全流程：

```text
装 https://github.com/linkaixiang4883/hermes-plugins 里的 <插件名> 子目录：按该目录下的 AGENT-INSTALL.md 做，
装完重启承载进程，并把 hermes plugins doctor <插件名> 的真实输出贴给我。
```

需要 key 的插件再加一句：`key 我自己填，你不要索取明文、不要代填`。

## 更新与卸载

```bash
hermes plugins update <插件名>     # 检查 + 更新一步到位（有新版答 Re-installed from …，没有答 already up to date）
hermes plugins disable <插件名>    # 停用，不删文件
hermes plugins remove <插件名>     # 连目录一起删
```

`<插件名>` 取 `model-audit` / `opencode-go-usage` / `agnes` / `agnes-image` / `agnes-video` / `opendesign`。
**插件名 ≠ provider id**：`config.yaml` 与 `hermes model` 里写的是 provider id
（`agnes` / `agnes-cn` / `agnes-image` / `agnes-cn-image` / `agnes-video` / `agnes-cn-video` / `opendesign`）。

> [!NOTE]
> **`hermes plugins check-updates` 看不到本仓库插件的版本号**：一个仓库放多个插件时是「子目录安装」，
> 装出来的目录**没有 `.git`** —— 该命令会把它列成 `drift` / `unknown`（备注 `provenance drift … reinstall from the recorded source`）。
> 这是布局后果、不是坏了：`update` 仍可用（按记录的源重新克隆），只是 `plugins.auto_apply` 不会自动更新它们。

> [!WARNING]
> **`--ref` 装出来是 pinned 安装**：`hermes plugins update` 会拒绝它（提示改用 `install --force --ref <新 40 位 SHA>`）。
> 想跟分支更新就别用 `--ref`；pinned 还只接受完整 commit SHA，不接受 tag 名。

### 布局变更（2026-11）

插件目录已从分类形态（`model-providers/<名>`、`image_gen/<名>`、`video_gen/<名>`）迁到**顶层**（`<名>`），
让「仓库目录名 = `plugin.yaml` 的 `name` = 安装目录名」三者一致。

**在此之前装过的**：旧标识符已不存在，`update` 会失败。先删再按新标识符装（数据不受影响）：

```bash
hermes plugins remove <插件名>        # 必做：旧目录还在时 install 会回 already exists；
                                     # 分类目录下的旧装不删会被再装一份，同名 provider 重复注册
hermes plugins install linkaixiang4883/hermes-plugins/<插件名> --enable
```

## 已知限制

- **`model-audit` 的防掉包依赖响应头自证**：`opencode-go` 自 2026-10-19 起不再发自证头、`commandcode` 结构性无自证 →
  这两家只能记录调用 / 用量 / 耗时；带 `x-litellm-model-id` 一类头的 provider 仍可验。
- **`opendesign` 只接 chat**：`/responses` 的思考只是摘要、`/messages` 的 `reasoning_effort` 无效且上游有「200 + 空 content」缺陷。
- **`opendesign` 不发 `max_tokens`**：输出上限交给服务端；`/models` 的 `output_budget` 只观察、不进请求。
- **未登记模型不发 `reasoning_effort`**：网关上新增模型要等一次插件发布（写进静态表）才有档位，避免发错值 400。
- **`opendesign` 不覆盖错误分类**：429 / 额度 / 鉴权全部交回 Hermes 内置策略（`rate_limit` → 原地重试 → 轮换凭据 → fallback）。
- **`opencode-go-usage` 的 GOAT 月窗可能缺席**：`planId` 查不到套餐表或订阅接口失败时只显示 5h / 周；未开始的窗口没有重置倒计时。

## 安全边界

- 六个插件都**不发遥测、不上传数据**。
- `model-audit` 的调用元数据（模型 / 端点 / 时间 / 耗时 / 会话 id）只写在本机 `<HERMES_HOME>/plugin-data/model-audit/`（SQLite），
  **不含消息正文**；会话标题不落库 —— 渲染时只读 Hermes 的 `state.db` 当场取，取不到就空着。它不碰任何 key。
- 凭据：模型 provider 由 Hermes 框架按 `env_vars` 解析；图像 / 视频后端走 `agent.secret_scope.get_secret()`
  （多 profile 下不会串）；`opencode-go-usage` 只把池里的 key 发给对应厂商的用量端点。key 不打印、不落盘、不进日志。
- 都不修改 Hermes 源码文件：`model-audit` 只在运行时内存里包一层 **fail-open** 的采集钩子（装不上就降级为「无信号」）。
- **已知债**：`model-audit` 与 `agnes` 会 import 私有核心符号，`hermes plugins validate` 会打印 `⚠ private core imports`
  （结论仍是 `Validation passed`）—— 代价是核心一改就可能失效；`opendesign` / `agnes-image` / `agnes-video` 无此警告。

## 故障排查

| 症状 | 先看哪里 |
|---|---|
| 插件没加载 | `hermes plugins list`（`requires_hermes` 不满足会写原因）→ `hermes plugins doctor <插件名>` |
| 页面 / 接口 404 | `plugins.enabled` 里有它吗；`enable` 是否早于进程重启 |
| 桌面芯片不显示 | 是否正在用这两家的套餐模型（门控命中才注册芯片） |
| 模型 / 图像 / 视频选不到 | `hermes model` / `hermes tools` 里有没有；视频还要 `hermes tools enable video_gen` |
| 芯片显示 `Go —` / `GOAT —` | 凭证池与 `.env` 里都没有对应 key |
| `validate` 打 `⚠ private core imports` | 已知债，见「安全边界」，不是装坏 |
| 版本对不上 | `plugin.yaml` ↔ `dashboard/manifest.json` ↔ 本表 ↔ `CHANGELOG.md` |

## 项目结构

```text
hermes-plugins/
├── model-audit/         # 仪表盘页 + 采集钩子 + SQLite 对账库
├── opencode-go-usage/   # 桌面芯片 + 只读用量后端（dashboard/ + desktop/）
├── agnes/               # 模型 provider：agnes + agnes-cn
├── agnes-image/         # 图像生成后端：agnes-image + agnes-cn-image
├── agnes-video/         # 视频生成后端：agnes-video + agnes-cn-video
└── opendesign/          # 模型 provider：opendesign（chat completions）
```

每个插件目录固定包含 `plugin.yaml`、`__init__.py`、`AGENT-INSTALL.md`、`CHANGELOG.md`；
有界面的另有 `dashboard/`（仪表盘页 + 后端）或 `desktop/`（桌面芯片）。本仓**没有构建步骤**，源码即产物。

---

内部 / 自用分享，暂未附开源许可证；如需对外分发，请先补 `LICENSE`。
