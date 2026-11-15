# CHANGELOG — agnes-image

> 版本来源：`plugin.yaml` 的 `version`（真源）。2026-11-16 目录扁平化前的历史路径为 `image_gen/agnes-image/`。

## Unreleased

- 文档：图片落点改为实际路径 `$HERMES_HOME/cache/generated/images/`；删掉「import 时写 `model_metadata` 上下文缓存」这条不存在的描述。
- 文档：`doctor` 期望补 `registrations: … provider(s): agnes-image, agnes-cn-image`；手工复制补 pwsh 分支；新增本 `CHANGELOG.md`。
- 仓库布局：`image_gen/agnes-image/` → `agnes-image/`（安装落点仍是 `plugins/agnes-image/`）。

## 1.2.2 — 2026-11-11

- 变更：Hermes 0.23.1 兼容收口 —— 全仓统一 LF；`plugin.yaml` 补 v0.23.1 复核结论。
- 文档：`__init__.py` 文档串的图片缓存路径改为 `$HERMES_HOME/cache/generated/images/`；`AGENT-INSTALL.md` 补齐安装与验收。

## 1.2.1 — 2026-10-17

- 修复：取 key 改用官方 `agent.secret_scope.get_secret()`，多 profile 网关下不再读到别的 profile 的凭据。
- 文档：写准 key 只能写 `$HH/.env`（生成后端不在凭据注册表里）。

## 1.2.0 — 2026-10-17

- 新增：国内站 `agnes-cn-image`（`api.agnes-ai.cn`，`AGNES_CN_API_KEY`），与 `agnes-image`（国际站）合为一个插件两个 provider。
- 变更：国内站模型清单不含 `agnes-image-2.0-flash`（其 `/v1/models` 不返回），国际站保留。

## 1.1.1 — 2026-10-17

- 首个版本：Agnes AI 国际站图像生成后端，OpenAI 兼容 `POST /v1/images/generations`；支持文生图、图生图、多图合成（`response_format` 必须放 `extra_body`），单文件上限 10MB。
- 注册为 `kind: backend` 的图像生成 provider，声明 `requires_hermes: >=0.21.6`。
