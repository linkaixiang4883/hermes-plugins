# hermes-plugins

本仓库有 **5 个**自建 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 插件：
2 个独立工具（模型对账 / 用量芯片）+ 3 个 Agnes AI 模型与生成后端，**各自独立、可只装一个**。
按 Hermes 的**标准 Git 安装形态**发布：从 GitHub 装、从本地源码装，走的是同一条 `hermes plugins install` 命令。

## 插件一览

### 两个工具插件

| 目录 | 插件 | 一句话 | 需要 API key？ | 版本 |
|---|---|---|---|---|
| [`model-audit/`](model-audit/) | **模型对账**（仪表盘页） | 逐次记录「请求 alias → 上游实际返回的 model / 路由端点」，在 Model Audit 页对账；用于发现中转掉包 / 降级 / 换路由 | 不需要 | `0.4.1` |
| [`opencode-go-usage/`](opencode-go-usage/) | **编码套餐用量芯片**（桌面端状态栏） | OpenCode Go / Command Code GOAT 用量（5h / 周 / 月窗口 + 详情面板），只在使用对应套餐模型时显示 | 需要用户**自己的**套餐 key（且已配进 Hermes） | `1.2.1` |

这两个目录里各带一份 **`AGENT-INSTALL.md`**（写给智能体的完整说明书：前置核对 / 安装 / 验收阶梯 / 故障对照表）
和一整套离线自检脚本（`tests/`）。

### 另外 3 个：Agnes AI 文本 / 图像 / 视频后端（按需选装）

| 目录 | 插件 | 作用 | `kind` | 版本 |
|---|---|---|---|---|
| [`model-providers/agnes`](model-providers/agnes/) | `agnes` + `agnes-cn` | Agnes AI 模型提供方 —— **一个插件两个 provider**（形态同内置 `opencode-zen`）：国际站（apihub.agnes-ai.com / `AGNES_API_KEY`）与国内站（api.agnes-ai.cn / `AGNES_CN_API_KEY`） | `model-provider` | `1.1.0` |
| [`image_gen/agnes-image`](image_gen/agnes-image/) | `agnes-image` + `agnes-cn-image` | 图像生成后端 —— **一个插件两个 provider**：国际站（`AGNES_API_KEY`，含 2.0-flash）与国内站（`AGNES_CN_API_KEY`，无 2.0-flash） | `backend` | `1.2.0` |
| [`video_gen/agnes-video`](video_gen/agnes-video/) | `agnes-video` + `agnes-cn-video` | 视频生成后端 —— **一个插件两个 provider**：国际站（`AGNES_API_KEY`）与国内站（`AGNES_CN_API_KEY`），模型集相同 | `backend` | `1.3.0` |

**这三个插件没有 `AGENT-INSTALL.md`，也没有自检脚本** —— 安装 / 取 key / 验证见下方
「安装 → Agnes 系列」一节。它们位于仓库的**分类子目录**下（`model-providers/`、`image_gen/`、`video_gen/`）。

> **为什么一个插件会注册两个 provider**：Hermes **没有** variant / 子选择概念，多区域只能靠
> 「一个插件注册多个 provider」实现（内置的 `opencode-zen` 就是这么同时提供 zen 与 go 的）——
> 所以选择器里 `agnes` 与 `agnes-cn` 是**两个并列条目**，而不是某个条目下的子选项。
>
> `agnes-cn`（v1.3.3）、`agnes-cn-image`（v1.3.2）、`agnes-cn-video`（v1.4.2）原先各是独立插件，
> 现已分别并入上述三个插件；**provider 名 / env vars / base_url 全部未变**
> （如 `agnes-cn-image` 仍是独立的 provider id，只是改由 `agnes-image` 插件注册），
> 故旧配置、`image_gen.provider` / `video_gen.provider`、`auth.json` 都无需改动。

## 安装（一条命令）

`hermes plugins install` 需要机器上有 `git`。**装完都要重启承载插件的进程**
（桌面端 App / `hermes dashboard` / `gateway run`）才生效。

### 两个工具插件

**从 GitHub**：

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --enable
hermes plugins install linkaixiang4883/hermes-plugins/opencode-go-usage --enable
```

**装某个固定版本**（`--ref` 只接受完整 commit SHA，**不接受 tag 名**）：

```bash
# 取 main 的当前 SHA
git ls-remote https://github.com/linkaixiang4883/hermes-plugins.git refs/heads/main
# 按 SHA 安装
hermes plugins install linkaixiang4883/hermes-plugins/model-audit --ref <40位SHA> --enable
```

**从本地源码**（仓库已 clone / 下载到本机；在仓库根目录下执行）：

```bash
# macOS / Linux
hermes plugins install "file://$PWD#model-audit" --enable
hermes plugins install "file://$PWD#opencode-go-usage" --enable
```

```powershell
# Windows（pwsh）——注意 file:// 必须写成两斜杠 file://C:/…
# （RFC 的三斜杠 file:///C:/… 会被 Git for Windows 解析成 /C:/… 后失败，实测如此）
hermes plugins install "file://C:/path/to/hermes-plugins#model-audit" --enable
hermes plugins install "file://C:/path/to/hermes-plugins#opencode-go-usage" --enable
```

> - 若下载的 zip 里没有 `.git`（下载工具漏了点目录），先补一个仓库再装：
>   `cd hermes-plugins && git init -q && git add -A && git commit -qm "vendor snapshot"`。
> - 首次装会打一行 `custom (unreviewed) source` 警告——不在官方 catalog 里都这样，不是错误。
> - 没有 git / 完全离线：也可以手工把插件目录复制到 `<HERMES_HOME>/plugins/<插件名>/`，
>   再 `hermes plugins enable <插件名>`（`model-audit` / `opencode-go-usage` 的细节见其 `AGENT-INSTALL.md` §3.2）。

### Agnes 系列（三个后端）

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-providers/agnes --enable
hermes plugins install linkaixiang4883/hermes-plugins/image_gen/agnes-image --enable
hermes plugins install linkaixiang4883/hermes-plugins/video_gen/agnes-video --enable
```

装完还差两步，否则插件在、但不工作：

1. **填 API key**：在 `<HERMES_HOME>/.env` 里写 `AGNES_API_KEY=`（国际站）和 `AGNES_CN_API_KEY=`（国内站）。
   **只用一家时另一把留空即可**（交互式安装会主动提示这两个变量，直接回车可跳过）。
2. **重启承载进程**（桌面端 App / `hermes dashboard` / `gateway run`）。

**让 Hermes 用上它们**：模型 provider 在 `hermes model` 里选 `agnes`（国际站）或 `agnes-cn`（国内站）；
图像 / 视频后端在 `config.yaml` 里指定 provider id：

```yaml
image_gen:
  provider: agnes-image        # 或 agnes-cn-image
video_gen:
  provider: agnes-video        # 或 agnes-cn-video
```

**验收**：`hermes plugins list` 里 `agnes` / `agnes-image` / `agnes-video` 都应是 enabled；
`hermes plugins doctor plugins/<子目录路径>` 应打印
`OK: runtime discovery, manifest parsing, import, and registration passed`。

> ⚠️ **子目录安装会被扁平化**：装完插件落在 `plugins/<插件名>/`（如 `plugins/agnes`），
> **不是** `plugins/model-providers/agnes`。更新 / 卸载用的名字就是插件名
> （`agnes` / `agnes-image` / `agnes-video`）。

> 这三个的 `--ref` 固定版本、本地源码（`file://…#子目录`）安装写法与上面两个工具插件相同，
> 把路径里的 `model-audit` 换成对应子目录即可。

**版本要求**：**5 个插件**的 `plugin.yaml` 都声明了 `requires_hermes: ">=0.21.6"`。
版本不满足时 Hermes 会**干净跳过**该插件、并在 `hermes plugins list` / `doctor` 里给出原因
（`requires hermes >=0.21.6, running X.Y.Z`）——不会出现「装上了却没数据」这种糊涂状态。
全部 5 个插件都在 **v0.22.2** 上做过端到端实测。

## 给智能体的一句话

把仓库地址（或 clone 下来的本地路径）+ 想装的插件名交给你的 Hermes Agent，说：

> 用 `hermes plugins install <仓库地址或本地路径>/<插件子目录> --enable` 装上 **<插件名>**，
> 重启承载插件的进程（桌面端 App / `hermes dashboard` / `gateway run`），
> 然后跑 `hermes plugins doctor <插件名>` —— 把真实输出贴给我。

**两种情况**：

- **`model-audit` / `opencode-go-usage`** —— 目录里有 `AGENT-INSTALL.md`，一句话就够：
  > 按 `AGENT-INSTALL.md` 把 `model-audit` 装上并验收。

  （它会自己走前置核对 → 安装 → 验收阶梯，不需要你补其他信息。）

- **三个 agnes 插件（`model-providers/agnes`、`image_gen/agnes-image`、`video_gen/agnes-video`）** ——
  **没有说明书**，要把四件事一次说全：
  > 装 `linkaixiang4883/hermes-plugins/model-providers/agnes`（国际站 + 国内站两个 provider）；
  > 在 `hermes .env` 里填 `AGNES_API_KEY` 和 `AGNES_CN_API_KEY`（只用一家可留空另一把）；
  > 重启后确认 `hermes plugins list` 里是 enabled；然后告诉我 `hermes model` 里能看到 `agnes` 与 `agnes-cn`。

  图像 / 视频那两个把路径换成 `image_gen/agnes-image`、`video_gen/agnes-video`，
  并把最后一句换成「`config.yaml` 里 `image_gen.provider` / `video_gen.provider` 要指向哪个 id」。

## 更新 / 卸载

`<插件名>` 取 `model-audit` / `opencode-go-usage` / `agnes` / `agnes-image` / `agnes-video`：

```bash
hermes plugins update <插件名>       # Git 安装的插件：拉最新
hermes plugins disable <插件名>      # 停用（不删文件）
hermes plugins remove <插件名>       # 连目录一起删
```

**别把插件名和 provider 名搞混**：更新 / 卸载用的是**插件名**；`config.yaml` 与 `hermes model`
里写的是 **provider id**（`agnes` / `agnes-cn` / `agnes-image` / `agnes-cn-image` /
`agnes-video` / `agnes-cn-video`）。

**数据在哪（别删错）**：`model-audit` **从 v0.4.0 起**把 SQLite 放在
`<HERMES_HOME>/plugin-data/model-audit/`，**不在插件目录里** —— 所以 `remove` / `update` 都碰不到历史数据。
从 ≤0.3.0 升级时，老库（`plugins/model-audit/data/model_audit.db`）会在首次启动时用 SQLite 的
`backup()` **复制**到新位置，老文件则改名为 `model_audit.db.migrated` **原地保留**作存档
（确认无误后可自行删除）。

> 版本号以本文件的版本表为准（各插件的 `AGENT-INSTALL.md` 可能滞后一两个补丁版本）。

## 安全与边界

- **5 个插件都不发遥测**、不上传数据。
- `model-audit` 的调用元数据（模型名 / 端点 / 时间 / 耗时 / 会话 id 与标题）只写在本机
  `<HERMES_HOME>/plugin-data/model-audit/`（SQLite），**不含消息正文**；它完全不碰任何 key。
- **凭据**：`opencode-go-usage` 读 Hermes 自己的凭证存储（`auth.json` 的凭证池 + `.env`），
  用来判断「当前在用哪把 key」，并只把它发给对应厂商的用量端点；key 不打印、不落盘、不进日志。
  三个 agnes 插件只从环境变量读各自的 key（`AGNES_API_KEY` / `AGNES_CN_API_KEY`）。
- 都不修改 Hermes 源码文件：`model-audit` 只在运行时**内存里**包一层 **fail-open** 的采集钩子
  （装不上就降级为「无信号」，不影响正常使用）。

## 许可

内部 / 自用分享，暂未附开源许可证；如需对外分发，请先补 `LICENSE`。
