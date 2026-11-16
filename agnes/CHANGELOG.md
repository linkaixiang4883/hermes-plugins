# Changelog — agnes

本文件记录该插件的所有重要变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)；**版本真源是 `plugin.yaml` 的 `version`**，本文件与它同步。
小节标题保持英文（Added / Changed / Fixed / Removed / Security），条目用中文。

## [Unreleased]

### Changed
- 说明书：安装路径跟随扁平化（`agnes/`）；非交互式切换改为 `hermes config set model.provider agnes`（`hermes model` 没有位置参数）。
- 说明书：模型清单标注 `2.5-pro-beta`（付费预览）/ `3.0-pro`（即将上线）。
- 代码注释：技术债说明按 2026-11-16 复核结论改写（v0.23.1 已提供 `provider_overlay` / `static_models` 正式面）。

### Added
- 说明书：披露「import 时向 `HERMES_OVERLAYS` / `_PROVIDER_MODELS` 注入」这条已知技术债，并说明 `validate` 的 `⚠ private core imports` 属预期。
- 新增本 `CHANGELOG.md`。

## [1.1.0] - 2026-10-17

### Changed
- 原先并列的两个独立插件合并为一个插件注册两个 provider —— `agnes`（国际站，`AGNES_API_KEY`）与 `agnes-cn`（国内站，`AGNES_CN_API_KEY`）。
- 两家共用同一份模型清单与 `model_capabilities`；`agnes-cn` 保留 `agnes-ai` / `agnes_ai` / `sapiens` 别名。
- 目录扁平化（2026-11-16）：`model-providers/agnes/` → `agnes/`，安装落点改为 `plugins/agnes/`。

### Fixed
- `build_extra_body()` 与 `build_api_kwargs_extras()` 都注入 `chat_template_kwargs.enable_thinking=true`，`/reasoning` 关闭时不再误停用 thinking。

### Added
- `AGENT-INSTALL.md`：key 来源、四条模型切换路径、`update` / 检查更新的适用面。

## [1.0.3] - 2026-10-17

### Fixed
- 按官方文档对齐模型清单与上下文窗口：移除已废弃的 `agnes-2.0-flash`，补入 `agnes-2.5-pro`（1M ctx）；新增 `model_capabilities`，修掉上下文被当成 200k 的兜底。

## [1.0.2] - 2026-10-17

### Added
- 首个入库版本：Agnes AI 文本模型 provider（国际站 `agnes`），声明 `requires_hermes: ">=0.21.6"`；同期另有独立插件 `agnes-cn`（v1.3.3，1.1.0 时并入）。
