# CHANGELOG — model-audit

> 版本来源：`plugin.yaml` 的 `version`（真源）。日期取对应提交的 `git log --date=short`。
> 本仓库 2026-10-17 才收录本插件，首个快照即 v0.4.1；更早版本的历史未随仓库保留。

## Unreleased

- 文档：说明书把诊断文件路径改为实际落点 `$HH/plugin-data/model-audit/capture-debug.jsonl`（0.4.0 起已随库移出插件树），并修正「外部依赖」「别删数据目录」「doctor 的 WinError 32」三处与现状矛盾的表述。
- 文档：状态图例与汇总卡补齐 `body_mismatch`（⚠️ 体证不同）/ `body_only`（○ 仅体证），与页面的 8 种展示态一一对应。
- 文档：新增本 `CHANGELOG.md`。
- 代码：清理无引用的 `SCHEMA_VERSION` 常量；文件头注释把 opencode-go 的自证头写成「2026-10-19 起已撤回」的现状。

## 0.4.2 — 2026-11-11

- 兼容 Hermes 0.23.1：加载 / 单测 / `hermes plugins doctor` / 采集链路复核通过（`requires_hermes` 仍为 `>=0.21.6`）。
- `opencode-go` 纳入「结构性无自证」：厂商自 2026-10-19 起撤掉 `x-opencode-upstream-model-id` / `x-opencode-endpoint-id`，无自证头且 body 同族回声的行判「◌ 无自证」，不再混进「○ 仅体证」。
- 建库/迁移加进程内锁；并发补 `provider` 列时把 `duplicate column` 当幂等处理。
- 文档：按实测重算附录 A 的字节数与 sha256。

## 0.4.1 — 2026-10-17

- 本仓库首次收录（快照版本 0.4.1）；同日修正说明书里写错的包版本并重算哈希。

## 0.4.0 — 日期不详（早期版本，历史细节未留存）

- 对账库移出插件树：`<插件根>/data/model_audit.db` → `$HH/plugin-data/model-audit/model_audit.db`。
- 升级时由 agent 半用 SQLite `backup()` 接收老库、把老文件改名 `*.migrated` 退场，并加两道安全闸。
- Windows 上 `hermes plugins doctor` 的 `WinError 32`（库在插件树内被自己打开）随之消失。

## 0.3.0 — 日期不详（早期版本，历史细节未留存）

- 仪表盘后端半改为纯客户端：只读探测 `schema_ready`，不建库、不改 schema。
- 库未就绪时读接口返回 200 + 空结果 + `initialized: false`，写接口 503。

## 0.2.x 及更早 — 日期不详（早期版本，历史细节未留存）

- 库未建时读接口返回 500（0.3.0 起修复）。
