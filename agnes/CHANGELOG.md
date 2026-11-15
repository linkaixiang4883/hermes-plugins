# CHANGELOG — agnes

> 版本来源：`plugin.yaml` 的 `version`（真源）。日期取对应提交的 `git log --date=short`。
> 1.0.2 之前的版本未进入本仓库历史，无记录。

## Unreleased

- 文档：安装路径跟随扁平化（`agnes/`），非交互式切换改成 `hermes config set model.provider`（`hermes model` 没有位置参数）。
- 文档：补写「import 时向 `HERMES_OVERLAYS` / `_PROVIDER_MODELS` 注入」这条已知技术债，以及 `validate` 的 `⚠ private core imports` 属预期；模型清单标注 `2.5-pro-beta`（付费预览）/ `3.0-pro`（即将上线）。
- 代码：技术债注释按 2026-11-16 复核结论改写（v0.23.1 已提供 `provider_overlay` / `static_models` 正式面）。
- 文档：新增本 `CHANGELOG.md`。

## 1.1.0 — 2026-10-17

- 变更：原先并列的两个独立插件合并为一个插件注册两个 provider —— `agnes`（国际站，`AGNES_API_KEY`）与 `agnes-cn`（国内站，`AGNES_CN_API_KEY`）。
- 变更：两家共用同一份模型清单与 `model_capabilities`；`agnes-cn` 保留 `agnes-ai` / `agnes_ai` / `sapiens` 别名。
- 变更：`build_extra_body()` 与 `build_api_kwargs_extras()` 都注入 `chat_template_kwargs.enable_thinking=true`。
- 文档：补 `AGENT-INSTALL.md`；2026-11-16 目录扁平化（`model-providers/agnes/` → `agnes/`），安装落点改为 `plugins/agnes/`。

## 1.0.3 — 2026-10-17

- 修复：按官方文档对齐模型清单与上下文窗口，移除已废弃的 `agnes-2.0-flash`，补入 `agnes-2.5-pro`（1M ctx）；新增 `model_capabilities`，修掉上下文被当成 200k 的兜底。

## 1.0.2 — 2026-10-17

- 首个入库版本：Agnes AI 文本模型 provider（国际站 `agnes`），声明 `requires_hermes: ">=0.21.6"`；同期另有独立插件 `agnes-cn`（v1.3.3，1.1.0 时并入）。
