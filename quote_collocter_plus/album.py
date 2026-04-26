from __future__ import annotations

import ast
import os
from typing import Any

from .config import coerce_bool
from .models import AlbumSettings, GroupContext, PluginSettings
from .onebot import OneBotClient, format_group_id_for_api
from .storage import QuoteStorage


def extract_album_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    candidates: list[Any] = [payload]
    data = payload.get("data")
    if isinstance(data, (dict, list)):
        candidates.append(data)

    for candidate in candidates:
        if isinstance(candidate, list):
            albums = [item for item in candidate if isinstance(item, dict)]
            if albums:
                return albums
        if isinstance(candidate, dict):
            for key in ("album_list", "albums", "list"):
                value = candidate.get(key)
                if isinstance(value, list):
                    albums = [item for item in value if isinstance(item, dict)]
                    if albums:
                        return albums
    return []


def album_item_id(album: dict[str, Any]) -> str:
    value = album.get("album_id") or album.get("id")
    return str(value).strip() if value is not None else ""


def album_item_name(album: dict[str, Any]) -> str:
    value = album.get("album_name") or album.get("name")
    return str(value).strip() if value is not None else ""


def plugin_album_name_for_group(album_name_config: Any, group_id: str | None) -> str:
    if isinstance(album_name_config, dict):
        if group_id is None:
            return str(album_name_config.get("*", "")).strip()
        value = album_name_config.get(str(group_id), album_name_config.get("*", ""))
        return str(value).strip()

    if isinstance(album_name_config, list):
        if group_id is None:
            return ""
        for item in album_name_config:
            if isinstance(item, dict):
                item_group_id = (
                    item.get("group_id")
                    or item.get("group")
                    or item.get("群号")
                    or item.get("qq_group")
                )
                item_album_name = (
                    item.get("album_name")
                    or item.get("name")
                    or item.get("相册名")
                    or item.get("群相册名")
                )
                if str(item_group_id).strip() == str(group_id) and item_album_name:
                    return str(item_album_name).strip()
                continue

            text = str(item).strip()
            if text.startswith(("[", "{")):
                try:
                    parsed = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    parsed = None
                if isinstance(parsed, (list, dict)):
                    album_name = plugin_album_name_for_group(parsed, group_id)
                    if album_name:
                        return album_name
                    continue
            separator = "：" if "：" in text else ":"
            if separator not in text:
                continue
            item_group_id, item_album_name = text.split(separator, 1)
            if item_group_id.strip() == str(group_id):
                return item_album_name.strip()
        return ""

    value = "" if album_name_config is None else str(album_name_config).strip()
    if value.startswith(("[", "{")):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, (list, dict)):
            return plugin_album_name_for_group(parsed, group_id)
    if "\n" in value and group_id is not None:
        return plugin_album_name_for_group(value.splitlines(), group_id)
    if group_id is not None and (":" in value or "：" in value):
        separator = "：" if "：" in value else ":"
        item_group_id, item_album_name = value.split(separator, 1)
        if item_group_id.strip() == str(group_id):
            return item_album_name.strip()
    return value


def effective_album_settings(
    plugin_settings: PluginSettings,
    group_settings: dict[str, Any] | None,
    group_id: str | None = None,
) -> AlbumSettings:
    group_settings = group_settings or {}

    def get_bool(key: str, default: bool) -> bool:
        if key in group_settings:
            return coerce_bool(group_settings.get(key), default)
        return default

    def get_str(key: str, default: str) -> str:
        value = group_settings.get(key, default)
        if value is None:
            return ""
        return str(value).strip()

    def get_album_name(default: str) -> str:
        if "album_name" not in group_settings:
            return default
        return plugin_album_name_for_group(group_settings.get("album_name"), group_id)

    plugin_album_name = plugin_album_name_for_group(plugin_settings.album_name, group_id)

    return AlbumSettings(
        enabled=get_bool("album_upload_enabled", plugin_settings.enable_album_upload),
        album_name=get_album_name(plugin_album_name),
        album_id=get_str("album_id", plugin_settings.album_id),
        strict=get_bool("album_upload_strict", plugin_settings.album_upload_strict),
        base64_fallback=get_bool(
            "album_upload_use_base64_fallback",
            plugin_settings.album_upload_use_base64_fallback,
        ),
        show_result=get_bool(
            "album_upload_show_result",
            plugin_settings.album_upload_show_result,
        ),
    )


def format_album_upload_status(settings: AlbumSettings) -> str:
    enabled_text = "开启" if settings.enabled else "关闭"
    strict_text = "开启" if settings.strict else "关闭"
    fallback_text = "开启" if settings.base64_fallback else "关闭"
    album_name = settings.album_name or "未配置"
    album_id = settings.album_id or "未配置"
    return (
        f"⭐群相册上传：{enabled_text}\n"
        f"目标相册名称：{album_name}\n"
        f"目标相册ID：{album_id}\n"
        f"严格匹配：{strict_text}\n"
        f"Base64兜底：{fallback_text}"
    )


class AlbumService:
    def __init__(
        self,
        settings: PluginSettings,
        storage: QuoteStorage,
        onebot: OneBotClient,
        logger: Any = None,
    ):
        self.settings = settings
        self.storage = storage
        self.onebot = onebot
        self.logger = logger

    def _debug(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "debug"):
            self.logger.debug(message)

    def _info(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "info"):
            self.logger.info(message)

    def get_effective_settings(
        self,
        group_settings: dict[str, Any] | None,
        group_id: str | None = None,
    ) -> AlbumSettings:
        return effective_album_settings(self.settings, group_settings, group_id)

    async def get_group_album_list(self, event: Any, group_id: str) -> list[dict[str, Any]]:
        if not self.onebot.is_aiocqhttp_event(event):
            self._info("当前平台不是 aiocqhttp，无法获取群相册列表")
            return []

        api_group_id = format_group_id_for_api(group_id)
        actions = [
            ("get_qun_album_list", {"group_id": api_group_id, "attach_info": ""}),
            ("get_group_album_list", {"group_id": api_group_id}),
            ("get_group_albums", {"group_id": api_group_id}),
            ("get_group_root_album_list", {"group_id": api_group_id}),
        ]

        for action, payload in actions:
            try:
                result = await self.onebot.call_action(event, action, **payload)
                albums = extract_album_list(result)
                if albums:
                    self._debug(f"通过 {action} 获取到 {len(albums)} 个群相册")
                    return albums
            except Exception as e:
                self._debug(f"获取群相册列表接口 {action} 调用失败: {e}")
        return []

    async def resolve_album_target(
        self,
        event: Any,
        group_id: str,
        settings: AlbumSettings,
    ) -> tuple[str, str, str]:
        album_id = settings.album_id
        album_name = settings.album_name
        albums: list[dict[str, Any]] = []

        if album_name and not album_id:
            albums = await self.get_group_album_list(event, group_id)
            for album in albums:
                if album_item_name(album) == album_name:
                    album_id = album_item_id(album)
                    if album_id:
                        return album_id, album_name, ""

            message = f"未找到名为“{album_name}”的群相册"
            if settings.strict:
                self._info(message)
            return "", "", message

        if album_id and not album_name:
            albums = await self.get_group_album_list(event, group_id)
            for album in albums:
                if album_item_id(album) == album_id:
                    album_name = album_item_name(album)
                    break

        if not album_id:
            return "", "", "未配置目标相册 ID 或名称"

        return album_id, album_name, ""

    async def call_album_upload(
        self,
        event: Any,
        group_id: str,
        album_id: str,
        album_name: str,
        file_value: str,
    ) -> tuple[bool, str]:
        api_group_id = format_group_id_for_api(group_id)
        params = {
            "group_id": api_group_id,
            "album_id": str(album_id),
            "album_name": album_name or "",
            "file": file_value,
        }
        llbot_params: dict[str, Any] = {
            "group_id": api_group_id,
            "album_id": str(album_id),
            "files": [file_value],
        }
        if album_name:
            llbot_params["album_name"] = album_name

        candidates = [
            ("upload_image_to_qun_album", params),
            ("upload_group_album", params),
            ("upload_qun_album", params),
            ("upload_group_album", llbot_params),
        ]
        last_error = None

        for action, payload in candidates:
            try:
                await self.onebot.call_action(event, action, **payload)
                self._info(f"群相册上传成功: action={action}, group_id={group_id}, album_id={album_id}")
                return True, action
            except Exception as e:
                last_error = e
                self._debug(f"群相册上传接口 {action} 调用失败: {e}")

        return False, str(last_error) if last_error else "所有相册上传接口均调用失败"

    async def upload_image_to_group_album(
        self,
        event: Any,
        group_id: str,
        image_path: str,
        settings: AlbumSettings,
    ) -> tuple[bool, str]:
        if not self.onebot.is_aiocqhttp_event(event):
            return False, "当前平台不支持群相册上传"
        if not image_path or not os.path.exists(image_path):
            return False, "图片文件不存在"

        album_id, album_name, reason = await self.resolve_album_target(event, group_id, settings)
        if not album_id:
            return False, reason or "未找到目标相册"

        abs_path = os.path.abspath(image_path)
        ok, detail = await self.call_album_upload(event, group_id, album_id, album_name, abs_path)
        if ok:
            return True, detail

        if settings.base64_fallback:
            encoded = self.storage.read_file_as_base64(abs_path)
            if encoded:
                ok, detail = await self.call_album_upload(
                    event,
                    group_id,
                    album_id,
                    album_name,
                    encoded,
                )
                if ok:
                    return True, detail

        return False, detail

    async def result_suffix(self, event: Any, group_context: GroupContext, image_path: str) -> str:
        settings = self.get_effective_settings(
            group_context.admin_settings,
            group_context.group_id,
        )
        if not settings.enabled:
            return ""

        ok, detail = await self.upload_image_to_group_album(
            event,
            group_context.group_id,
            image_path,
            settings,
        )
        if not settings.show_result:
            return ""
        if ok:
            return "\n已上传到群相册"
        return f"\n群相册上传失败：{detail}"

    async def handle_command(self, event: Any, group_context: GroupContext, msg: str) -> str:
        args = msg[len("语录相册"):].strip()
        if args in {"", "状态"}:
            return format_album_upload_status(
                self.get_effective_settings(
                    group_context.admin_settings,
                    group_context.group_id,
                ),
            )

        if args in {"开启", "启用", "打开"}:
            group_context.admin_settings["album_upload_enabled"] = True
            self.storage.save_group_context(group_context)
            return "⭐群相册上传已开启"

        if args in {"关闭", "禁用", "关"}:
            group_context.admin_settings["album_upload_enabled"] = False
            self.storage.save_group_context(group_context)
            return "⭐群相册上传已关闭"

        if args in {"严格开启", "开启严格"}:
            group_context.admin_settings["album_upload_strict"] = True
            self.storage.save_group_context(group_context)
            return "⭐群相册严格匹配已开启"

        if args in {"严格关闭", "关闭严格"}:
            group_context.admin_settings["album_upload_strict"] = False
            self.storage.save_group_context(group_context)
            return "⭐群相册严格匹配已关闭"

        if args in {"重置", "清除"}:
            for key in ("album_upload_enabled", "album_name", "album_id", "album_upload_strict"):
                group_context.admin_settings.pop(key, None)
            self.storage.save_group_context(group_context)
            return "⭐群相册上传设置已恢复为插件配置"

        if args == "列表":
            albums = await self.get_group_album_list(event, group_context.group_id)
            if not albums:
                return "⭐未获取到群相册列表，请确认当前协议端支持 NapCat 群相册接口"
            lines = ["⭐群相册列表："]
            for album in albums[:20]:
                name = album_item_name(album) or "未命名相册"
                aid = album_item_id(album) or "无ID"
                lines.append(f"{name}：{aid}")
            if len(albums) > 20:
                lines.append(f"仅显示前20个，共{len(albums)}个")
            return "\n".join(lines)

        if args.startswith("名称"):
            album_name = args[len("名称"):].strip()
            if not album_name:
                return "⭐请输入相册名称，例如：语录相册 名称 黑历史"
            group_context.admin_settings["album_name"] = album_name
            self.storage.save_group_context(group_context)
            return f"⭐目标相册名称已设置为：{album_name}"

        upper_args = args.upper()
        if upper_args.startswith("ID"):
            album_id = args[2:].strip()
            if not album_id:
                return "⭐请输入相册ID，例如：语录相册 ID 123456"
            group_context.admin_settings["album_id"] = album_id
            self.storage.save_group_context(group_context)
            return f"⭐目标相册ID已设置为：{album_id}"

        return (
            "⭐语录相册命令：\n"
            "语录相册 状态\n"
            "语录相册 列表\n"
            "语录相册 开启/关闭\n"
            "语录相册 名称 相册名\n"
            "语录相册 ID 相册ID\n"
            "语录相册 严格开启/严格关闭\n"
            "语录相册 重置"
        )
