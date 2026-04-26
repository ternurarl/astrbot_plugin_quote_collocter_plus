from __future__ import annotations

from typing import Any

try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )
except Exception:  # pragma: no cover - only used outside an AstrBot runtime.
    AiocqhttpMessageEvent = None


def format_group_id_for_api(group_id: Any) -> int | Any:
    try:
        return int(group_id)
    except (TypeError, ValueError):
        return group_id


class OneBotClient:
    def __init__(self, logger: Any = None):
        self.logger = logger

    def is_aiocqhttp_event(self, event: Any) -> bool:
        return AiocqhttpMessageEvent is not None and isinstance(event, AiocqhttpMessageEvent)

    async def call_action(self, event: Any, action: str, **payload: Any) -> Any:
        bot = getattr(event, "bot", None)
        api = getattr(bot, "api", None)
        if api and hasattr(api, "call_action"):
            return await api.call_action(action, **payload)
        if bot and hasattr(bot, "call_action"):
            return await bot.call_action(action, **payload)
        raise RuntimeError("当前平台不支持 OneBot API 调用")

    async def get_msg(self, event: Any, message_id: Any) -> Any:
        return await self.call_action(event, "get_msg", message_id=message_id)

    async def get_image(self, event: Any, file_id: str) -> Any:
        return await self.call_action(event, "get_image", file_id=file_id)

    async def get_forward_msg(self, event: Any, **payload: Any) -> Any:
        return await self.call_action(event, "get_forward_msg", **payload)
