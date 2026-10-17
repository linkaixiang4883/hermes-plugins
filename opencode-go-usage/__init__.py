"""opencode-go-usage —— agent 半（占位，无任何工具/钩子）。

本插件的实际功能在另外两个半边：
  · dashboard/plugin_api.py —— 后端路由 /api/plugins/opencode-go-usage/usage
  · desktop/plugin.js       —— 桌面状态栏芯片

这个空 ``register(ctx)`` 的意义：让插件在 CLI/网关侧是一个形态完整的
standalone 插件（`hermes plugins list / enable / disable` 可正确管理、
仪表盘的 Plugins 页主列表可见）。
"""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:  # noqa: ARG001 - 契约要求该签名
    """No-op：没有需要注册的工具、钩子或命令。"""
    return None
