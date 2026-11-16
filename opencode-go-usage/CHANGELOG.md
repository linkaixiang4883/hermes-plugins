# Changelog — opencode-go-usage

本文件记录该插件的所有重要变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)；**版本真源是 `plugin.yaml` 的 `version`**，本文件与它同步。
小节标题保持英文（Added / Changed / Fixed / Removed / Security），条目用中文。

## [Unreleased]

### Fixed
- 单测放宽 GOAT 重置时间断言：未开始（`percent=0`）的窗口上游不给 `resetsAt`，只对 `percent>0` 的窗口要求 ISO 8601。
- 说明书：版本门改为 `>=0.21.6`（原写 `>=0.21`，低版本会被「干净跳过」）；删掉不存在的 `hermes model list` 命令；GOAT 套餐价改为 `$70/月`。
- 说明书：写准「GOAT 月窗可能缺席」「未开始的窗口没有重置倒计时」的口径。

### Changed
- 附录 A 按当前文件重算 `tests/test_plugin_api.py` 的字节数与 sha256。

### Added
- 新增本 `CHANGELOG.md`。

## [1.2.2] - 2026-11-11

### Changed
- 冷却 TTL 对齐 Hermes 0.23.1：`failure_reason=billing_unverified` 且非 402 时一律短冷却（60s）。
- `plugin.yaml` 补记依赖面实测结论，并记录 v0.23.1 复核结果。
- 全仓 LF 规则落地；`dashboard/manifest.json` 版本号升到 1.2.2，附录 A 按 LF 重算。

### Added
- 单测新增两条 TTL 断言（`billing_unverified` 402 / 非 402）。

## [1.2.1] - 2026-10-17

### Added
- 本仓首个入库版本：桌面状态栏芯片 + 只读后端（提供商注册表版），支持 `opencode-go` 与 `commandcode-goat`。
- 模型门控 `/gate` 三级解析：模型串前缀（仅认注册表内 provider）→ `state.db` 会话行（沿 `parent_session_id` 上溯压缩链）→ `config.yaml` 默认 provider。
- 多 key 跟随 Hermes 凭证池轮换：401/403 顺延下一把；冷却 TTL 与 `agent/credential_pool.py` 对齐。
- `AGENT-INSTALL.md` 安装说明书与附录 A 文件校验和。
