# hermes-plugins

两个自建 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 插件，**各自独立、可只装一个**。
按 Hermes 的**标准 Git 安装形态**发布：从 GitHub 装、从本地源码装，走的是同一条 `hermes plugins install` 命令。

| 目录 | 插件 | 一句话 | 需要 API key？ | 版本 |
|---|---|---|---|---|
| [`model-audit/`](model-audit/) | **模型对账**（仪表盘页） | 逐次记录「请求 alias → 上游实际返回的 model / 路由端点」，在 Model Audit 页对账；用于发现中转掉包 / 降级 / 换路由 | 不需要 | `0.4.1` |
| [`opencode-go-usage/`](opencode-go-usage/) | **编码套餐用量芯片**（桌面端状态栏） | OpenCode Go / Command Code GOAT 用量（5h / 周 / 月窗口 + 详情面板），只在使用对应套餐模型时显示 | 需要用户**自己的**套餐 key（且已配进 Hermes） | `1.2.1` |

每个插件目录里都带一份 **`AGENT-INSTALL.md`**（写给智能体的完整说明书：前置核对 / 安装 / 验收阶梯 / 故障对照表）
和一整套离线自检脚本（`tests/`）。

### 附带的模型 / 生成后端（同一仓库，按需单选）

| 目录 | 插件 | 作用 | `kind` | 版本 |
|---|---|---|---|---|
| [`model-providers/agnes`](model-providers/agnes/) | `agnes` + `agnes-cn` | Agnes AI 模型提供方 —— **一个插件两个 provider**（形态同内置 `opencode-zen`）：国际站（apihub.agnes-ai.com / `AGNES_API_KEY`）与国内站（api.agnes-ai.cn / `AGNES_CN_API_KEY`） | `model-provider` | `1.1.0` |
| [`image_gen/agnes-image`](image_gen/agnes-image/) | `agnes-image` + `agnes-cn-image` | 图像生成后端 —— **一个插件两个 provider**：国际站（`AGNES_API_KEY`，含 2.0-flash）与国内站（`AGNES_CN_API_KEY`，无 2.0-flash） | `backend` | `1.2.0` |
| [`video_gen/agnes-video`](video_gen/agnes-video/) | `agnes-video` + `agnes-cn-video` | 视频生成后端 —— **一个插件两个 provider**：国际站（`AGNES_API_KEY`）与国内站（`AGNES_CN_API_KEY`），模型集相同 | `backend` | `1.3.0` |

它们在仓库里位于**分类子目录**下（`model-providers/`、`image_gen/`、`video_gen/`），安装时把整套相对路径写进
`owner/repo/` 后面即可：

```bash
hermes plugins install linkaixiang4883/hermes-plugins/model-providers/agnes --enable
hermes plugins install linkaixiang4883/hermes-plugins/image_gen/agnes-image --enable
hermes plugins install linkaixiang4883/hermes-plugins/video_gen/agnes-video --enable
```

> **三个 agnes 插件都是"一个插件注册两个 provider"**（国际站 + 国内站）—— Hermes 没有
> variant / 子选择概念，所以选择器里它们各是两个**并列条目**（这正是内置 `opencode-zen` 呈现
> zen / go 的方式）。原先独立的 `agnes-cn`（v1.3.3）、`agnes-cn-image`（v1.3.2）、
> `agnes-cn-video`（v1.4.2）三个插件已分别并入上述三个插件。
>
> **provider 名 / env vars / base_url 全部未变**（如 `agnes-cn-image` 仍是独立的 provider id，
> 由 `agnes-image` 插件注册），故旧配置、`image_gen.provider`、`auth.json` 都无需改动；
> `plugins.enabled` 里的插件名也未变（仍是 `agnes` / `agnes-image` / `agnes-video`）。

> 这 3 个的 `plugin.yaml` 同样声明 `requires_hermes: ">=0.21.6"`。
> 图像/视频后端的 provider 接口（`agents.image_gen_provider` / `agent.video_gen_provider`）在 v0.21.6 起稳定，
> 后端已实现文档中的全部成员（含 `capabilities()`）。

**版本要求**：两个插件的 `plugin.yaml` 都声明了 `requires_hermes: ">=0.21.6"`。
版本不满足时 Hermes 会**干净跳过**该插件、并在 `hermes plugins list` / `doctor` 里给出原因
（`requires hermes >=0.21.6, running X.Y.Z`）——不会出现「装上了却没数据」这种糊涂状态。
两端全量端到端实测版本：**v0.22.2**。

## 安装（一条命令）

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

> - `hermes plugins install` 需要机器上有 `git`；装完要**重启承载插件的进程**（桌面端 App / `hermes dashboard` / `gateway`）才生效。
> - 若下载的 zip 里没有 `.git`（下载工具漏了点目录），先补一个仓库再装：
>   `cd hermes-plugins && git init -q && git add -A && git commit -qm "vendor snapshot"`。
> - 首次装会打一行 `custom (unreviewed) source` 警告——不在官方 catalog 里都这样，不是错误。
> - 没有 git / 完全离线：也可以手工把插件目录复制到 `<HERMES_HOME>/plugins/<插件名>/`，再 `hermes plugins enable <插件名>`
>   （细节见各插件的 `AGENT-INSTALL.md` §3.2）。

## 给智能体的一句话

把这份仓库（或某个插件子目录）交给你的 Hermes Agent，说：

> 按 `AGENT-INSTALL.md` 把 `model-audit`（或 `opencode-go-usage`）装上并验收。

## 更新 / 卸载

```bash
hermes plugins update model-audit          # Git 安装的插件：拉最新
hermes plugins disable model-audit         # 停用（不删文件）
hermes plugins remove  model-audit         # 连目录一起删
```

**数据在哪（别删错）**：`model-audit` **从 v0.4.0 起**把 SQLite 放在
`<HERMES_HOME>/plugin-data/model-audit/`，**不在插件目录里** —— 所以 `remove` / `update` 都碰不到历史数据。
从 ≤0.3.0 升级时，老库（`plugins/model-audit/data/model_audit.db`）会在首次启动时被整库搬到新位置，
并改名为 `*.migrated` 留在原地作为存档（确认无误后可自行删除）。

## 安全与边界

- 两个插件都**不发遥测**、不上传数据；对账数据只写在本机 `<HERMES_HOME>/plugin-data/model-audit/`（SQLite）。
- **凭据**：`opencode-go-usage` 读 Hermes 自己的凭证存储（`auth.json` 的凭证池 + `.env`），
  用来判断「当前在用哪把 key」，并只把它发给对应厂商的用量端点；key 不打印、不落盘、不进日志。
  `model-audit` 完全不碰任何 key。
- 都不修改 Hermes 源码文件：`model-audit` 只在运行时**内存里**包一层 **fail-open** 的采集钩子
  （装不上就降级为「无信号」，不影响正常使用）。
- `model-audit` 会记录调用元数据（模型名 / 端点 / 时间 / 耗时 / 会话 id 与标题），**不含消息正文**。

## 许可

内部 / 自用分享，暂未附开源许可证；如需对外分发，请先补 `LICENSE`。
