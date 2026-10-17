# hermes-plugins

5 个自建 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 插件：2 个独立工具 + 3 个 Agnes AI 模型与生成后端。
**各自独立，可只装一个。**

## 插件一览

### 两个工具插件

| 目录 | 插件 | 一句话 | 需要 API key？ | 版本 |
|---|---|---|---|---|
| [`model-audit/`](model-audit/) | **模型对账**（仪表盘页） | 逐次记录「请求 alias → 上游实际返回的 model / 路由端点」，在 Model Audit 页对账；用于发现中转掉包 / 降级 / 换路由 | 不需要 | `0.4.1` |
| [`opencode-go-usage/`](opencode-go-usage/) | **编码套餐用量芯片**（桌面端状态栏） | OpenCode Go / Command Code GOAT 用量（5h / 周 / 月窗口 + 详情面板），只在使用对应套餐模型时显示 | 需要用户自己的套餐 key（已配进 Hermes） | `1.2.1` |

### Agnes AI 文本 / 图像 / 视频后端（按需选装）

| 目录 | 插件 | 作用 | `kind` | 版本 |
|---|---|---|---|---|
| [`model-providers/agnes`](model-providers/agnes/) | `agnes` + `agnes-cn` | 模型提供方：国际站（apihub.agnes-ai.com / `AGNES_API_KEY`）与国内站（api.agnes-ai.cn / `AGNES_CN_API_KEY`） | `model-provider` | `1.1.0` |
| [`image_gen/agnes-image`](image_gen/agnes-image/) | `agnes-image` + `agnes-cn-image` | 图像生成后端：国际站（`AGNES_API_KEY`，含 2.0-flash）与国内站（`AGNES_CN_API_KEY`，无 2.0-flash） | `backend` | `1.2.1` |
| [`video_gen/agnes-video`](video_gen/agnes-video/) | `agnes-video` + `agnes-cn-video` | 视频生成后端：国际站（`AGNES_API_KEY`）与国内站（`AGNES_CN_API_KEY`），模型集相同 | `backend` | `1.3.1` |

> 三个 agnes 插件每个都注册**两个 provider**（国际站 + 国内站）—— 选择器里因此是**两个并列条目**，
> 这是设计如此（Hermes 没有「子选项」这种形式），不是重复配置。

每个插件目录都带一份 **`AGENT-INSTALL.md`**（写给智能体的说明书：前置核对 / 安装 / 验收 / 故障对照表）。

## 安装

`hermes plugins install` 需要机器上有 `git`。**装完要重启承载插件的进程**（桌面端 App / `hermes dashboard` / `gateway run`）才生效。
5 个插件都要求 **Hermes ≥ 0.21.6**（`plugin.yaml` 里的 `requires_hermes`；不满足会被干净跳过，`hermes plugins list` 会说明原因）。

### 两个工具插件

**从 GitHub**：

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --enable
hermes plugins install linkaixiang4883/hermes-plugins/opencode-go-usage --enable
```

**装固定版本**（`--ref` 只接受完整 commit SHA，不接受 tag 名）：

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

> - 下载的 zip 里若没有 `.git`：先 `cd hermes-plugins && git init -q && git add -A && git commit -qm "vendor snapshot"`，再装。
> - 首次装会打一行 `custom (unreviewed) source` 警告 —— 不在官方 catalog 里都这样，不是错误。
> - 完全离线：手工把插件目录复制到 `<HERMES_HOME>/plugins/<插件名>/`，再 `hermes plugins enable <插件名>`。
>   ⚠️ 这样装的**没有装源记录**，之后 `update` 会拒绝它（想能 update 就用 `install`）。

### Agnes 系列（三个后端）

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-providers/agnes --enable
hermes plugins install linkaixiang4883/hermes-plugins/image_gen/agnes-image --enable
hermes plugins install linkaixiang4883/hermes-plugins/video_gen/agnes-video --enable
```

装完还差两步，否则插件在、但不工作：

1. **填 key**：在 `<HERMES_HOME>/.env` 里写 `AGNES_API_KEY=`（国际站）和 `AGNES_CN_API_KEY=`（国内站）——
   只用一家时另一把留空即可（交互式安装会提示这两个变量，直接回车可跳过）。
   模型 provider 也可改用 `hermes auth add agnes --api-key <key>`；**图像 / 视频后端只认 `.env`**。
2. **重启承载进程**（桌面端 App / `hermes dashboard` / `gateway run`）。

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
`hermes plugins doctor plugins/<子目录路径>` 应打印 `OK: runtime discovery, manifest parsing, import, and registration passed`。

（固定版本 `--ref`、本地源码 `file://…#子目录` 的装法与上面两个工具插件相同，把子目录名换掉即可。）

## 通过 Agent 安装（把整句复制给你的智能体）

不想自己敲命令？**整句复制**给任意一个 Hermes Agent 即可 —— 每个插件都带 `AGENT-INSTALL.md`，
它会照着走完（前置核对 → 安装 → 验收 → 故障排查），不需要你再补信息。

**`model-audit`**：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 model-audit 子目录：按该目录下的 AGENT-INSTALL.md 做，装完重启承载进程，并把 hermes plugins doctor model-audit 的真实输出贴给我。
```

**`opencode-go-usage`**：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 opencode-go-usage 子目录：按该目录下的 AGENT-INSTALL.md 做，装完重启承载进程，并把 hermes plugins doctor opencode-go-usage 的真实输出贴给我。
```

**三个 agnes 插件**（需要 API key，提示词里已替你写明「不要索取明文」）：

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 model-providers/agnes 子目录：按该目录下的 AGENT-INSTALL.md 做；AGNES_API_KEY / AGNES_CN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把验收结果和 hermes plugins doctor 的真实输出贴给我。
```

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 image_gen/agnes-image 子目录：按该目录下的 AGENT-INSTALL.md 做；AGNES_API_KEY / AGNES_CN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把验收结果和 hermes plugins doctor 的真实输出贴给我。
```

```
装 https://github.com/linkaixiang4883/hermes-plugins 里的 video_gen/agnes-video 子目录：按该目录下的 AGENT-INSTALL.md 做；AGNES_API_KEY / AGNES_CN_API_KEY 我自己填进 .env，你不要索取、不要代填明文；装完重启承载进程，把验收结果和 hermes plugins doctor 的真实输出贴给我。
```

**想一次装多个**：把子目录列在一起说全即可，例如「装 `linkaixiang4883/hermes-plugins` 里的
`model-providers/agnes` 和 `image_gen/agnes-image` 两个子目录，各按它自己的 `AGENT-INSTALL.md` 做；
key 我自己填，你不要索取明文；装完重启承载进程。」

**想让它检查 / 完成更新**：

```
检查 https://github.com/linkaixiang4883/hermes-plugins 里 model-audit 有没有新版（对比该目录 plugin.yaml 的 version 与本地已装版本），有就更新到最新、重启承载进程，并把 hermes plugins doctor 的真实输出贴给我。
```

> 这条对**手工复制安装的**同样管用 —— agent 会去比对仓库，而不是依赖本机的 `update`（那种安装没有装源记录，`update` 会拒绝）。

## 更新 / 卸载

`<插件名>` 取 `model-audit` / `opencode-go-usage` / `agnes` / `agnes-image` / `agnes-video`：

```bash
hermes plugins update <插件名>       # 有新版则重装到最新；没有则答 "already up to date"（= 检查 + 更新一步到位）
hermes plugins disable <插件名>      # 停用（不删文件）
hermes plugins remove <插件名>       # 连目录一起删
```

**`update` 同时就是"检查更新"**：有新版会打印 `Re-installed from <源>: 旧..新`，没有则打印 `already up to date`。两条限制：

- **`hermes plugins check-updates` 看不到本仓库插件的版本号**：那是 monorepo 的固有现象 —— 一个仓库放多个插件时安装形态是"子目录安装"，装出来的目录里**没有 `.git`**，而那个命令需要 `.git` 才能比版本。`update` 不受影响（它按记录的源重新克隆）。
- **手工复制安装的**（见 §安装 的离线做法）没有装源记录 → `update` 会拒绝（`Plugin 'X' was not installed from git … Cannot update.`）。

**插件名 ≠ provider 名**：上面用的是**插件名**；`config.yaml` 与 `hermes model` 里写的是 **provider id**
（`agnes` / `agnes-cn` / `agnes-image` / `agnes-cn-image` / `agnes-video` / `agnes-cn-video`）。

**数据在哪（别删错）**：`model-audit` 把 SQLite 放在 `<HERMES_HOME>/plugin-data/model-audit/`，**不在插件目录里** ——
`remove` / `update` 都碰不到历史数据。（从 ≤0.3.0 升级时，老库会改名 `model_audit.db.migrated` 原地留档，可自行删除。）

## 安全与边界

- **5 个插件都不发遥测**、不上传数据。
- `model-audit` 的调用元数据（模型名 / 端点 / 时间 / 耗时 / 会话 id 与标题）只写在本机
  `<HERMES_HOME>/plugin-data/model-audit/`（SQLite），**不含消息正文**；它完全不碰任何 key。
- **凭据**：`opencode-go-usage` 读 Hermes 自己的凭证存储（`auth.json` 的凭证池 + `.env`），只把它发给对应厂商的用量端点；
  `agnes` / `agnes-cn` 的 key 由 Hermes **框架**解析（插件本身不碰 key）；`agnes-image` / `agnes-video` 只从环境变量读
  `AGNES_API_KEY` / `AGNES_CN_API_KEY`。key 不打印、不落盘、不进日志。
- 都不修改 Hermes 源码文件：`model-audit` 只在运行时内存里包一层 **fail-open** 的采集钩子（装不上就降级为「无信号」）。

## 许可

内部 / 自用分享，暂未附开源许可证；如需对外分发，请先补 `LICENSE`。
