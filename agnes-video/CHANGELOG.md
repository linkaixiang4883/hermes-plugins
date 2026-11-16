# Changelog — agnes-video

本文件记录该插件的所有重要变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)；**版本真源是 `plugin.yaml` 的 `version`**，本文件与它同步。
小节标题保持英文（Added / Changed / Fixed / Removed / Security），条目用中文。

## [Unreleased]

### Fixed
- 说明书：执行顺序补上 §4（先 `hermes tools enable video_gen` 再选 provider，否则装完仍不可用）。
- 说明书：删掉「import 时写上下文缓存」这条本插件不存在的描述；「不产生任何数据文件」改为「生成的视频缓存在 `$HH/cache/generated/videos/`」。
- 说明书：探针去掉分类目录兜底、收敛 `SPECS`、补模型清单断言。

### Changed
- 说明书：安装一节写明会追问 env 变量（直接回车跳过）；手工复制补 pwsh 分支。
- 目录扁平化（2026-11-16）：`video_gen/agnes-video/` → `agnes-video/`。

### Added
- 新增本 `CHANGELOG.md`。

## [1.3.2] - 2026-11-11

### Changed
- 在 Hermes v0.23.1 上复核加载 / `doctor` / 注册两个 provider 通过，结论补进 `plugin.yaml` 注释。
- 包版本与验收期望值升到 1.3.2，附录 A 按 LF 重算。

### Fixed
- 文件头缓存落点注释改为 `$HERMES_HOME/cache/generated/videos/`。

## [1.3.1] - 2026-10-17

### Fixed
- 取 API key 改用官方 `agent.secret_scope.get_secret()`，避免多 profile 下读到别的 profile 的 key。

### Added
- `AGENT-INSTALL.md`（含内联注册探针与故障对照表）；写明生成后端只能用 `$HERMES_HOME/.env`。

## [1.3.0] - 2026-10-17

### Changed
- 国际站与国内站合并为一个插件两个 provider（`agnes-video` / `agnes-cn-video`）；区域差异收敛为子类常量。

### Fixed
- 轮询地址由硬编码改为 `API_BASE` 派生的 `agnesapi_url`（`/agnesapi` 在站点根下，不在 `/v1` 下）。

## [1.2.2] - 2026-10-17

### Fixed
- 模型清单按两家 `/v1/models` 实测对齐，移除已下线的 `agnes-video-v2.0`，只留 `agnes-video-2.5` / `agnes-video-2.5-flash`。

## [1.2.1] - 2026-10-17

### Added
- 首个版本：Agnes AI 视频生成后端（国际站），异步任务 API `POST /v1/videos` → `GET /agnesapi?video_id=…` 轮询 → 缓存视频。
- 声明 `requires_hermes: >=0.21.6`；国内站当时是独立插件 `agnes-cn-video`。
