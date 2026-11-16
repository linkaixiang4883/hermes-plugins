# Changelog — model-audit

本文件记录该插件的所有重要变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)；**版本真源是 `plugin.yaml` 的 `version`**，本文件与它同步。
小节标题保持英文（Added / Changed / Fixed / Removed / Security），条目用中文。

## [Unreleased]

### Changed
- 说明书：诊断文件改指实际落点 `$HERMES_HOME/plugin-data/model-audit/capture-debug.jsonl`（0.4.0 起随库移出插件树）。
- 说明书：状态图例与顶部汇总卡补齐 `body_mismatch`（⚠️ 体证不同）/ `body_only`（○ 仅体证），与页面的 8 种展示态对齐。
- 代码注释：文件头把 opencode-go 的自证头写成「2026-10-19 起已撤回」的现状。

### Fixed
- 说明书：修正「外部依赖 = 无需 git/联网」「别删 data/ 数据目录」「doctor 会报 WinError 32」三处与 0.4.x 实际行为矛盾的表述。

### Removed
- 清理无任何引用的 `SCHEMA_VERSION` 常量（schema 版本由迁移链与 meta 表记录）。

### Added
- 新增本 `CHANGELOG.md`。

## [0.4.2] - 2026-11-11

### Added
- `opencode-go` 纳入「结构性无自证」：厂商自 2026-10-19 起撤掉 `x-opencode-upstream-model-id` / `x-opencode-endpoint-id`，此类行判「◌ 无自证」，不再混进「○ 仅体证」。

### Changed
- 兼容 Hermes 0.23.1：加载 / 单测 / `hermes plugins doctor` / 采集链路复核通过（`requires_hermes` 仍为 `>=0.21.6`）。
- 建库/迁移加进程内锁；并发补 `provider` 列时把 `duplicate column` 当幂等处理。

### Fixed
- 按实测重算说明书附录 A 的字节数与 sha256（`test_audit_core.py` 用例数同步更新）。

## [0.4.1] - 2026-10-17

### Added
- 本仓库首次收录（快照版本 0.4.1）。

### Fixed
- 修正说明书里写错的包版本号并重算哈希。

## [0.4.0] - 日期不详

### Changed
- 对账库移出插件树：`<插件根>/data/model_audit.db` → `$HERMES_HOME/plugin-data/model-audit/model_audit.db`。
- Windows 上 `hermes plugins doctor` 的 `WinError 32`（库在插件树内被自己打开）随之消失。

### Added
- 升级时由 agent 半用 SQLite `backup()` 接收老库、把老文件改名 `*.migrated` 退场，并加两道安全闸。

## [0.3.0] - 日期不详

### Changed
- 仪表盘后端半改为纯客户端：只读探测 `schema_ready`，不建库、不改 schema。
- 库未就绪时读接口返回 200 + 空结果 + `initialized: false`，写接口 503。

## [0.2.x] - 日期不详

### Fixed
- 库未建时读接口返回 500 的问题（0.3.0 起修复）。
