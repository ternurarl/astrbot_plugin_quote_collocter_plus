from __future__ import annotations

import ast
import os
from typing import Any

from .models import PluginSettings


BUBBLE_TEXT_MAX_LENGTH = 3000


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if not value:
            return default
        if value in {"1", "true", "yes", "on", "启用", "开启", "打开"}:
            return True
        if value in {"0", "false", "no", "off", "禁用", "关闭", "关"}:
            return False
    return bool(value)


def get_config_str(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key, default)
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def get_config_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    return coerce_bool(config.get(key, default), default)


def get_config_int(
    config: dict[str, Any],
    key: str,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def get_config_float(
    config: dict[str, Any],
    key: str,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    try:
        value = float(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def normalize_admin_ids(admins: Any) -> list[str]:
    if not admins:
        return []
    if isinstance(admins, (str, int)):
        admins = [admins]
    return [str(admin).strip() for admin in admins if str(admin).strip()]


def normalize_album_name_map(value: Any) -> dict[str, str]:
    if not value:
        return {}

    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("[", "{")):
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, (list, dict)):
                return normalize_album_name_map(parsed)

    if isinstance(value, dict):
        entries = value.items()
    else:
        if isinstance(value, (str, int)):
            text = str(value).strip()
            if text and ":" not in text and "：" not in text:
                return {"*": text}
            value = [value]
        entries = []
        parsed_entries: list[tuple[Any, Any]] = []
        for item in value:
            if isinstance(item, dict):
                group_id = (
                    item.get("group_id")
                    or item.get("group")
                    or item.get("群号")
                    or item.get("qq_group")
                )
                album_name = (
                    item.get("album_name")
                    or item.get("name")
                    or item.get("相册名")
                    or item.get("群相册名")
                )
                parsed_entries.append((group_id, album_name))
                continue

            text = str(item).strip()
            if not text:
                continue
            separator = "：" if "：" in text else ":"
            if separator not in text:
                continue
            group_id, album_name = text.split(separator, 1)
            parsed_entries.append((group_id, album_name))
        entries = parsed_entries

    album_names: dict[str, str] = {}
    for group_id, album_name in entries:
        group = str(group_id).strip() if group_id is not None else ""
        name = str(album_name).strip() if album_name is not None else ""
        if group and name:
            album_names[group] = name
    return album_names


def load_plugin_settings(
    config: dict[str, Any] | None,
    global_config: dict[str, Any] | None = None,
) -> PluginSettings:
    config = config or {}
    global_config = global_config or {}

    plugin_admins = normalize_admin_ids(config.get("admin_ids", []))
    global_admins: list[str] = []
    if get_config_bool(config, "use_global_admins", True):
        global_admins = normalize_admin_ids(global_config.get("admins_id", []))

    return PluginSettings(
        data_path=get_config_str(config, "data_path", os.path.join("data", "quotes_data")),
        default_permission_mode=get_config_int(
            config,
            "default_permission_mode",
            0,
            min_value=0,
            max_value=2,
        ),
        default_poke_cooldown=get_config_int(
            config,
            "default_poke_cooldown",
            10,
            min_value=0,
        ),
        poke_quote_probability=get_config_float(
            config,
            "poke_quote_probability",
            0.85,
            min_value=0.0,
            max_value=1.0,
        ),
        enable_poke_reply=get_config_bool(config, "enable_poke_reply", True),
        allow_text_quote_render=get_config_bool(config, "allow_text_quote_render", True),
        text_quote_max_length=get_config_int(
            config,
            "text_quote_max_length",
            BUBBLE_TEXT_MAX_LENGTH,
            min_value=1,
        ),
        enable_album_upload=get_config_bool(config, "enable_album_upload", False),
        album_name=normalize_album_name_map(config.get("album_name", [])),
        album_id=get_config_str(config, "album_id", ""),
        album_upload_strict=get_config_bool(config, "album_upload_strict", False),
        album_upload_use_base64_fallback=get_config_bool(
            config,
            "album_upload_use_base64_fallback",
            True,
        ),
        album_upload_show_result=get_config_bool(config, "album_upload_show_result", True),
        admins=sorted(set(plugin_admins + global_admins)),
    )
