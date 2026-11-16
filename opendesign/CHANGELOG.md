# Changelog — opendesign

本文件记录该插件的所有重要变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)；**版本真源是 `plugin.yaml` 的 `version`**，本文件与它同步。
小节标题保持英文（Added / Changed / Fixed / Removed / Security），条目用中文。

## [Unreleased]

### Changed
- 说明书：上下文口径的理由按现状改写（`hostnames` 已登记 amr-link，不再走 custom-endpoint 的 256k probe-down）。
- 说明书：`doctor` 验收改为按名；picker 期望值按 `tui_desc[:40]` 原样输出修正；附录 A 的文件数与自查命令纳入 `CHANGELOG.md`。
- 目录扁平化（2026-11-16）：`model-providers/opendesign/` → `opendesign/`（落点仍是 `plugins/opendesign/`）。

### Fixed
- `USER_AGENT` 版本号从 `0.2` 升到 `0.3.2`。
- `live_context_length` / `get_model_context_length` 的 docstring 去掉过期理由。
- `probe_live.py` 读 `metadata.context_limit` / `metadata.output_budget`（原按 0.1 时代的顶层字段），`.env` 兜底按平台区分。

### Added
- 新增本 `CHANGELOG.md`。

## [0.3.2] - 2026-11-15

### Removed
- 撤销 `classify_api_error` 覆盖：429 / 额度类错误全部交回 Hermes 内置分类器（`rate_limit` → 原地重试 → 轮换凭据 → fallback）。

## [0.3.1] - 2026-11-15

### Changed
- `supported_reasoning_efforts()` 落地三态契约：`()` = 完全不发、`None` = 保留默认词表；未登记模型由 `None` 改为 `()`。
- 极小窗兜底：窗口 < 65,536 时按 75% 上报。

### Removed
- 收窄后的 429 匹配面（0.3.2 已整体撤销）。

## [0.3.0] - 2026-11-15

### Added
- `hostnames` / `models_url`：`amr-link.open-design.ai` 可被 host→provider 反查与 doctor 探活识别。
- 目录抓取成功后用 `/v1/models` 补 `model_capabilities` 缺失条目；`_PREFERRED_CATALOG` 成为 step 0d 的唯一读源。

### Changed
- 未登记模型运行时不发 `reasoning_effort`。

## [0.2.3] - 2026-11-15

### Changed
- 上下文改走 provider bound `get_model_context_length()`（step 0d）：不依赖凭据与网络。

## [0.2.2] - 2026-11-15

### Changed
- 不再发送 `max_tokens`：输出上限交给服务端；`/models` 的 `output_budget` 只解析出来观察。

## [0.2.1] - 2026-11-15

### Changed
- `get_max_tokens()` 改用 `/models` 的 `output_budget` 原值，去掉 65,536 统一上限。

## [0.2.0] - 2026-11-15

### Changed
- 上下文、输出预算与图片模态改取 `/v1/models` 的 metadata；手写上下文值删除，静态表降级为离线兜底。

### Added
- 真 key 抓取的 `tests/fixtures/models.json` 与 `tests/test_metadata.py`，断言静态表与目录不漂移。

## [0.1.0] - 2026-11-15

### Added
- 首个版本：OpenDesign Cloud 文本模型 provider（`amr-link.open-design.ai/v1`，`OPENDESIGN_API_KEY`），chat completions 主路径，按账户套餐实时拉取 `/v1/models`。
