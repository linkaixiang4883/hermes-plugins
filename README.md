# hermes-plugins

6 个自建 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 插件：2 个独立工具 + 3 个 Agnes AI 模型与生成后端 + 1 个 OpenDesign Cloud 模型 provider。
**各自独立，可只装一个。**

## 插件一览

### 两个工具插件

| 目录 | 插件 | 一句话 | 需要 API key？ | 版本 |
|---|---|---|---|---|
| [`model-audit/`](model-audit/) | **模型对账**（仪表盘页） | 逐次记录「请求 alias → 上游实际返回的 model / 路由端点」，在 Model Audit 页对账；用于发现中转掉包 / 降级 / 换路由 | 不需要 | `0.4.2` |
| [`opencode-go-usage/`](opencode-go-usage/) | **编码套餐用量芯片**（桌面端状态栏） | OpenCode Go / Command Code GOAT 用量（5h / 周 / 月窗口 + 详情面板），只在使用对应套餐模型时显示 | 需要用户自己的套餐 key（已配进 Hermes） | `1.2.2` |

### Agnes AI 模型 provider / 图像 / 视频生成后端（按需选装）

| 目录 | 插件 | 作用 | `kind` | 版本 |
|---|---|---|---|---|
| [`agnes`](agnes/) | `agnes` + `agnes-cn` | 模型提供方：国际站（apihub.agnes-ai.com / `AGNES_API_KEY`）与国内站（api.agnes-ai.cn / `AGNES_CN_API_KEY`） | `model-provider` | `1.1.0` |
| [`agnes-image`](agnes-image/) | `agnes-image` + `agnes-cn-image` | 图像生成后端：国际站（`AGNES_API_KEY`，含 2.0-flash）与国内站（`AGNES_CN_API_KEY`，无 2.0-flash） | `backend` | `1.2.2` |
| [`agnes-video`](agnes-video/) | `agnes-video` + `agnes-cn-video` | 视频生成后端：国际站（`AGNES_API_KEY`）与国内站（`AGNES_CN_API_KEY`），模型集相同 | `backend` | `1.3.2` |

> 三个 agnes 插件每个都注册**两个 provider**（国际站 + 国内站）—— 选择器里因此是**两个并列条目**，
> 这是设计如此（Hermes 没有「子选项」这种形式），不是重复配置。
>
> ⚠️ `model-audit` 的「上游 model」依赖 provider 的响应头自证：`opencode-go` 自 2026-10-19 起、
> `commandcode` 结构性都不再提供 → 这两家目前只能记录调用/用量/耗时，无法判断是否掉包；
> 带自证头的 provider（如 LiteLLM 系）仍正常。

### OpenDesign Cloud 模型 provider（按需选装）

| 目录 | 插件 | 作用 | `kind` | 版本 |
|---|---|---|---|---|
| [`opendesign`](opendesign/) | `opendesign` | 模型提供方：OpenDesign Cloud（`amr-link.open-design.ai/v1` / `OPENDESIGN_API_KEY`）；chat completions 主路径，上下文/输出/图片模态取自 `/v1/models` 的 metadata，生图模型自动过滤 | `model-provider` | `0.3.2` |

> 只接 **chat** 面：`/responses` 的思考只是被改写的摘要，`/messages` 的 `reasoning_effort` 无效且上游有「200 + 空 content」缺陷。
> 生图（`/images/generations`）与套餐额度是另外的插件形态，本插件不含。

**`opendesign` 的已知限制**（都是有意的取舍，不是待办）：

- **不发 `max_tokens`** —— 交给服务端按模型自己定；Hermes 截断时自动加档、超窗时自动降档。
- **不提供额度查询** —— 运行时 key 层没有任何用量路由；额度只在控制面（需会话凭据），要做得另立插件。
- **未登记的模型不发 `reasoning_effort`** —— 网关新增模型后，思考档位要等一次插件发布（写进静态表）才给出，避免发错值 400。
- **多网点共用进程时上下文取「最近一次抓取」** —— `_PREFERRED_CATALOG` 是单槽、不区分 `base_url`（step 0d 拿不到 base_url）；只有你同时给不同 profile 配不同 `OPENDESIGN_BASE_URL` 时才可能串，单网点无影响。
- **不改错误分类** —— 429 / 额度 / 鉴权一律交回 Hermes 内置策略（`rate_limit` → 先原地重试一次、再轮换凭据、再 fallback）。插件不重新解释上游返回：没有实测依据去判断网关的 RPM 是「按 key」还是「按账号」。
- **`plugins.isolation: host` 下目录补全只在插件宿主进程内生效** —— 默认 `in_process` 无影响；宿主模式下 `model_capabilities` 是发现期快照，新模型的视觉声明要等静态表更新。


每个插件目录都带两份文档：**`AGENT-INSTALL.md`**（写给智能体的说明书：前置核对 / 安装 / 验收 / 故障对照表）和 **`CHANGELOG.md`**（逐版变更；版本真源是 `plugin.yaml` 的 `version`，上面的版本列与它同步）—— 查「装的是不是最新 / 这版改了什么」先看 CHANGELOG。

## 安装

`hermes plugins install` 需要机器上有 `git`。**装完要重启承载插件的进程**（桌面端 App / `hermes dashboard` / `gateway run`）才生效。
5 个插件要求 **Hermes ≥ 0.21.6**，`opendesign` 要求 **≥ 0.23.1**（`plugin.yaml` 里的 `requires_hermes`）。
注意：`requires_hermes` 只被 `hermes plugins validate` / 插件管理器检查，**provider 发现链本身不做版本闸** ——
低版本装 model-provider 不会报错，但缺 hook 时行为未定义，装前先看版本。

### 两个工具插件

**从 GitHub**：

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --enable
hermes plugins install linkaixiang4883/hermes-plugins/opencode-go-usage --enable
```

> `opencode-go-usage` 只是**读**用量：先让 Hermes 里有一把套餐 key（`hermes auth add opencode-go` / `hermes auth add commandcode`，或 `.env` 里写 `OPENCODE_GO_API_KEY` / `COMMANDCODE_API_KEY`），否则芯片只会显示 `Go —` / `GOAT —`。

**装固定版本**（`--ref` 只接受完整 commit SHA，不接受 tag 名）：

> `--ref` 装出来的是 **pinned** 安装：`hermes plugins update` 会拒绝它（提示改用 `install --force --ref <新 40 位 SHA>`）。想跟分支更新就别用 `--ref`。

```bash
git ls-remote https://github.com/linkaixiang4883/hermes-plugins.git refs/heads/main   # 取当前 SHA
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --ref <40位SHA> --enable
```

**从本地源码**（仓库已 clone 到本机，在仓库根目录执行）：

```bash
hermes plugins install "file://$PWD#model-audit" --enable                           # macOS / Linux
```

```powershell
hermes plugins install "file://C:/path/to/hermes-plugins#model-audit" --enable      # Windows：file:// 必须两斜杠
```

> - 如果你手上是 GitHub 网页「Download ZIP」解出来的目录（没有 `.git`，`git clone file://…` 会失败）：先 `cd hermes-plugins && git init -q && git add -A && git commit -qm "vendor snapshot"`，再装。
> - 首次装会打一行 `custom (unreviewed) source` 警告 —— 不在官方 catalog 里都这样，不是错误。
> - 完全离线：手工把插件目录复制到 `<HERMES_HOME>/plugins/<插件名>/`，再 `hermes plugins enable <插件名>`。
>   ⚠️ 这样装的**没有装源记录**，之后 `update` 会拒绝它（想能 update 就用 `install`）。

### OpenDesign Cloud（模型 provider，一个）

```bash
hermes plugins install linkaixiang4883/hermes-plugins/opendesign --enable
```

装完两件事：① 在 `<HERMES_HOME>/.env` 写 `OPENDESIGN_API_KEY=`（运行时 key，`sk-amr-` 开头；也可 `hermes auth add opendesign`）；
② 重启承载进程。然后在 `hermes model` 里选 `OpenDesign Cloud`，再选一个模型（**模型必须选**，本插件没有静态默认模型）。

**验收**：`hermes plugins validate <插件目录>` 通过；`hermes plugins doctor <插件名>`（按名解析到 `plugins/<插件名>/`；也可传目录路径）
打印 `provider(s): opendesign`；`hermes model` 里出现 `OpenDesign Cloud` 一行；
`hermes -z "只回复：连接成功" --provider opendesign -m deepseek-v4.1-flash` 有回复。

### Agnes 系列（1 个模型 provider + 2 个生成后端）

```bash
hermes plugins install linkaixiang4883/hermes-plugins/agnes --enable
hermes plugins install linkaixiang4883/hermes-plugins/agnes-image --enable
hermes plugins install linkaixiang4883/hermes-plugins/agnes-video --enable
```

装完还差一步，否则插件在、但不工作：

1. **填 key**：在 `<HERMES_HOME>/.env` 里写 `AGNES_API_KEY=`（国际站）和 `AGNES_CN_API_KEY=`（国内站）——
   只用一家时另一把留空即可（交互式安装会提示这两个变量，直接回车可跳过）。
   模型 provider 也可改用 `hermes auth add agnes --api-key <国际站 key>`（国内站把 `agnes` 换成 `agnes-cn`）；
   **图像 / 视频后端只认 `.env`** —— 它们的 provider id 不在凭据注册表里，`hermes auth add agnes-image` 会回 `Unknown provider`。

（重启承载进程见本文开头 —— 不重启的话选择器里看不到新注册的 provider。）

**怎么把它选上** —— 四条等价的路（改的是同一个配置键，选哪条都行）：

| 要选的 | ① 命令行 | ② Dashboard | ③ 桌面端 App | ④ 直接改 config |
|---|---|---|---|---|
| **模型**<br>`model.provider` | `hermes model` → 选 `agnes` / `agnes-cn` | **Models 页** | 模型选择器 | `model.provider: agnes` |
| **图像**<br>`image_gen.provider` | `hermes tools`（不带子命令 = 交互式 UI）→「🎨 Image Generation」→ `Agnes AI (Intl)` / `Agnes AI (CN)` | **Skills → Toolsets** → Image Generation（或 **Config 页**） | **Capabilities → Toolsets** → Image Generation | `image_gen.provider: agnes-image`（国内站 `agnes-cn-image`） |
| **视频**<br>`video_gen.provider` | 同上，选「🎬 Video Generation」 | **Skills → Toolsets** → Video Generation | **Capabilities → Toolsets** → Video Generation | `video_gen.provider: agnes-video`（国内站 `agnes-cn-video`） |

> ⚠️ **视频生成默认是关闭的** —— 先 `hermes tools enable video_gen`（或在上面任一界面里启用），否则选不到视频后端。
>
> ⚠️ 装完插件落在 `plugins/<插件名>/`（如 `plugins/agnes`）—— 更新 / 卸载用的就是这个**插件名**。

**验收**：`hermes plugins list` 里 `agnes` / `agnes-image` / `agnes-video` 都应是 enabled；
`hermes plugins doctor <插件名>`（或传绝对路径 `"$HERMES_HOME/plugins/<插件名>"`）应打印 `OK: runtime discovery, manifest parsing, import, and registration passed`；注意 `plugins/<插件名>` 这种**相对路径**只在当前目录 = `<HERMES_HOME>` 时才成立。

（固定版本 `--ref`、本地源码 `file://…#子目录` 的装法与上面两个工具插件相同，把子目录名换掉即可。）

## 通过 Agent 安装（把整句复制给你的智能体）

不想自己敲命令？**整句复制**给任意一个 Hermes Agent 即可 —— 每个插件都带 `AGENT-INSTALL.md`，
它会照着走完（前置核对 → 安装 → 验收 → 故障排查），不需要你再补信息。需要 key 的插件，提示词里都已写明「key 你自己填，agent 不索取、不代填明文」。

**`model-audit`**：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 model-audit 子目录：按该目录下的 AGENT-INSTALL.md 做，装完重启承载进程，并把 hermes plugins doctor model-audit 的真实输出贴给我。
```

**`opencode-go-usage`**：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 opencode-go-usage 子目录：按该目录下的 AGENT-INSTALL.md 做，装完重启承载进程，并把 hermes plugins doctor opencode-go-usage 的真实输出贴给我。
```

**OpenDesign Cloud 模型 provider**：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 opendesign 子目录：按该目录下的 AGENT-INSTALL.md 做；OPENDESIGN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把 hermes plugins validate / doctor 的真实输出和 hermes model 里那一行贴给我。
```

**三个 agnes 插件**：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 agnes 子目录：按该目录下的 AGENT-INSTALL.md 做；AGNES_API_KEY / AGNES_CN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把验收结果和 hermes plugins doctor 的真实输出贴给我。
```

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 agnes-image 子目录：按该目录下的 AGENT-INSTALL.md 做；AGNES_API_KEY / AGNES_CN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把验收结果和 hermes plugins doctor 的真实输出贴给我。
```

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 agnes-video 子目录：按该目录下的 AGENT-INSTALL.md 做；AGNES_API_KEY / AGNES_CN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把验收结果和 hermes plugins doctor 的真实输出贴给我。
```

**想一次装多个**：把子目录列在一起说全即可，例如「装 `linkaixiang4883/hermes-plugins` 里的
`agnes` 和 `agnes-image` 两个子目录，各按它自己的 `AGENT-INSTALL.md` 做；
key 我自己填，你不要索取明文；装完重启承载进程。」

**想确认有没有新版 / 完成更新** —— 两条路都行：

- **你自己查**：拿 [上面插件表](#插件一览) 里的版本与本地 `hermes plugins list` 显示的版本对照一下即可；
  若当初是 `install` 装的，直接 `hermes plugins update <插件名>` 就行（= 检查 + 更新，输出含义见 §更新 / 卸载）。
- **让 agent 查**（**手工复制安装的**尤其适合 —— 那种安装没装源记录，`update` 会拒绝）：

```
检查 https://github.com/linkaixiang4883/hermes-plugins 里 model-audit 有没有新版（对比该目录 plugin.yaml 的 version 与本地已装版本），有就更新到最新、重启承载进程，并把 hermes plugins doctor 的真实输出贴给我。
```

### 布局变更（2026-11）

插件目录已从分类形态（`model-providers/<名>`、`image_gen/<名>`、`video_gen/<名>`）迁到顶层（`<名>`），
让「仓库目录名 = `plugin.yaml` 的 `name` = 安装目录名」三者一致。Hermes 两种布局都支持，扁平只是消除歧义。

**如果你在 2026-11 之前装过**：`hermes plugins update <插件名>` 会因旧子目录路径已不存在而失败，按新路径重装一次即可：

```bash
hermes plugins remove <插件名>        # 必做：旧目录还在时 install 会回 already exists；
                                     # 分类目录下的旧装不删会被再装一份，同名 provider 重复注册
hermes plugins install linkaixiang4883/hermes-plugins/<插件名> --enable
```

数据不受影响（库在 `<HERMES_HOME>/plugin-data/model-audit/`，`remove` / `update` 都碰不到，详见 §更新 / 卸载）。

## 更新 / 卸载

`<插件名>` 取 `model-audit` / `opencode-go-usage` / `agnes` / `agnes-image` / `agnes-video` / `opendesign`：

```bash
hermes plugins update <插件名>       # 有新版则重装到最新；没有则答 "already up to date"（= 检查 + 更新一步到位）
hermes plugins disable <插件名>      # 停用（不删文件）
hermes plugins remove <插件名>       # 连目录一起删
```

**`update` 同时就是"检查更新"**：有新版会打印 `Re-installed from <源>: 旧..新`，没有则打印 `already up to date`。两条限制：

- **`hermes plugins check-updates` 看不到本仓库插件的版本号**：一个仓库放多个插件时是「子目录安装」，装出来的目录**没有 `.git`** —— 该命令会把它列成 `drift` / `unknown`，备注 `provenance drift … reinstall from the recorded source`。这是布局后果、不是坏了：`update` 仍可用（按记录的源重新克隆），只是 `plugins.auto_apply` 不会自动更新它们，要升就手动 `hermes plugins update <插件名>`。
- **手工复制安装的**（见 §安装 的离线做法）没有装源记录 → `update` 会拒绝（`Plugin 'X' was not installed from git … Cannot update.`）。

**插件名 ≠ provider 名**：上面用的是**插件名**；`config.yaml` 与 `hermes model` 里写的是 **provider id**
（`agnes` / `agnes-cn` / `agnes-image` / `agnes-cn-image` / `agnes-video` / `agnes-cn-video`）。

**数据在哪（别删错）**：`model-audit` 把 SQLite 放在 `<HERMES_HOME>/plugin-data/model-audit/`，**不在插件目录里** ——
`remove` / `update` 都碰不到历史数据。（从 ≤0.3.0 升级时，老库会改名 `model_audit.db.migrated` 原地留档，可自行删除。）

## 安全与边界

- **6 个插件都不发遥测**、不上传数据。
- `model-audit` 的调用元数据（模型名 / 端点 / 时间 / 耗时 / 会话 id）只写在本机
  `<HERMES_HOME>/plugin-data/model-audit/`（SQLite），**不含消息正文**；会话标题不落库 —— 页面渲染时只读 Hermes 的
  `state.db`（`sessions.title`）当场取，取不到就空着。它完全不碰任何 key。
- **凭据**：`opencode-go-usage` 读 Hermes 自己的凭证存储（`auth.json` 的凭证池 + `.env`），只把它发给对应厂商的用量端点；
  `agnes` / `agnes-cn` 的 key 由 Hermes **框架**解析（插件本身不碰 key）；`agnes-image` / `agnes-video` 只从环境变量读
  `AGNES_API_KEY` / `AGNES_CN_API_KEY`。key 不打印、不落盘、不进日志。
- 都不修改 Hermes 源码文件：`model-audit` 只在运行时内存里包一层 **fail-open** 的采集钩子（装不上就降级为「无信号」）。
- **`model-audit` / `agnes` 会 import 私有核心符号（已知债）**：`model-audit` 用 `agent.served_model` 与 `hermes_cli.profiles.get_active_profile_name` 装采集钩子；`agnes` 在 import 时还往 `hermes_cli.providers.HERMES_OVERLAYS` 与 `hermes_cli.models._PROVIDER_MODELS` 两个模块级 dict 注入条目（只改内存、不落盘）。因此这两个插件的 `hermes plugins validate` 会打印 `⚠ private core imports`，结论仍是 `Validation passed` —— 已知债，不是装坏；代价是核心一改就可能失效。`opendesign` / `agnes-image` / `agnes-video` 无此警告。

## 许可

内部 / 自用分享，暂未附开源许可证；如需对外分发，请先补 `LICENSE`。
