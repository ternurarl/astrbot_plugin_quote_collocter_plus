from __future__ import annotations

import base64
import os
from typing import Any

import aiohttp

from .message_parser import MessageParser
from .onebot import OneBotClient
from .storage import QuoteStorage

try:
    from astrbot.core.message.components import Image
except Exception:  # pragma: no cover - only used outside an AstrBot runtime.
    Image = None


def _is_image_component(value: Any) -> bool:
    return Image is not None and isinstance(value, Image)


class ImageService:
    def __init__(
        self,
        storage: QuoteStorage,
        parser: MessageParser,
        onebot: OneBotClient,
        logger: Any = None,
    ):
        self.storage = storage
        self.parser = parser
        self.onebot = onebot
        self.logger = logger

    def _debug(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "debug"):
            self.logger.debug(message)

    def _error(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "error"):
            self.logger.error(message)

    def _info(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "info"):
            self.logger.info(message)

    async def resolve_forward_image_src(self, event: Any, image_ref: Any) -> str | None:
        src = self.parser.image_src_from_ref(image_ref)
        if src:
            return src

        if image_ref is None:
            return None
        file_id = str(image_ref).strip()
        if not file_id:
            return None

        try:
            result = await self.onebot.get_image(event, file_id=file_id)
            data = self.parser.unwrap_api_data(result)
            for key in ("file", "url", "path"):
                src = self.parser.image_src_from_ref(data.get(key))
                if src:
                    return src
            for key in ("base64", "data"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    if value.startswith("data:"):
                        return value.strip()
                    return self.parser.base64_to_data_uri(value)
        except Exception as e:
            self._debug(f"解析合并转发图片失败: {e}, image_ref={file_id}")
        return None

    async def save_image_ref_to_local(self, image_ref: Any, group_id: str) -> str | None:
        if image_ref is None:
            return None
        raw = str(image_ref).strip()
        if not raw:
            return None

        try:
            if raw.startswith("data:") and "," in raw:
                header, payload = raw.split(",", 1)
                if ";base64" not in header:
                    return None
                return self.storage.save_image_bytes(base64.b64decode(payload), group_id)
            if raw.startswith("base64://"):
                payload = "".join(raw[len("base64://"):].split())
                return self.storage.save_image_bytes(base64.b64decode(payload), group_id)

            local_path = None
            if raw.startswith("file://"):
                local_path = self.parser.path_from_file_uri(raw)
            elif os.path.exists(raw):
                local_path = raw

            if local_path and os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    return self.storage.save_image_bytes(f.read(), group_id)

            if raw.startswith(("http://", "https://")):
                async with aiohttp.ClientSession() as session:
                    async with session.get(raw) as response:
                        if response.status == 200:
                            return self.storage.save_image_bytes(await response.read(), group_id)
                        self._error(f"从URL下载图片失败: HTTP {response.status}")
        except Exception as e:
            self._debug(f"直接保存图片引用失败: {e}, image_ref={raw}")
        return None

    async def download_image(self, event: Any, file_id: str, group_id: str) -> str | None:
        try:
            assert self.onebot.is_aiocqhttp_event(event)

            direct_path = await self.save_image_ref_to_local(file_id, group_id)
            if direct_path:
                return direct_path

            result: Any = {}
            download_by_api_failed = 0
            download_by_file_failed = 0

            message_obj = event.message_obj
            image_obj = None

            for item in message_obj.message:
                if _is_image_component(item):
                    image_obj = item
                    break

            if image_obj:
                file_path = await image_obj.convert_to_file_path()
                if file_path:
                    self._info(f"尝试从本地缓存{file_path}读取图片")
                    try:
                        with open(file_path, "rb") as f:
                            return self.storage.save_image_bytes(f.read(), group_id)
                    except Exception as e:
                        download_by_file_failed = 1
                        self._error(f"在读取本地缓存时遇到问题: {str(e)}")
                else:
                    download_by_file_failed = 1
            else:
                download_by_file_failed = 1

            if download_by_file_failed == 1:
                result = await self.onebot.get_image(event, file_id=file_id)
                data = self.parser.unwrap_api_data(result)

                file_path = data.get("file")
                if file_path and os.path.exists(file_path):
                    self._info(f"尝试从协议端api返回的路径{file_path}读取图片")
                    try:
                        with open(file_path, "rb") as f:
                            return self.storage.save_image_bytes(f.read(), group_id)
                    except Exception as e:
                        download_by_api_failed = 1
                        self._error(f"在通过api下载图片时遇到问题: {str(e)}")
                else:
                    download_by_api_failed = 1

            if download_by_api_failed == 1 and download_by_file_failed == 1:
                data = self.parser.unwrap_api_data(result)
                url = data.get("url")
                if url:
                    self._info(f"尝试从URL下载图片: {url}")
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(url) as response:
                                if response.status == 200:
                                    return self.storage.save_image_bytes(await response.read(), group_id)
                                self._error(f"从URL下载图片失败: HTTP {response.status}")
                    except Exception as e:
                        self._error(f"从URL下载出错: {str(e)}")
                else:
                    self._error("API返回结果中没有URL，无法下载")
        except Exception as e:
            raise Exception(f"{str(e)}")
        return None
