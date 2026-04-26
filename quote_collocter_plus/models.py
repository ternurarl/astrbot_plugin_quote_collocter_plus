from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PluginSettings:
    data_path: str
    default_permission_mode: int
    default_poke_cooldown: int
    poke_quote_probability: float
    enable_poke_reply: bool
    allow_text_quote_render: bool
    text_quote_max_length: int
    enable_album_upload: bool
    album_name: str
    album_id: str
    album_upload_strict: bool
    album_upload_use_base64_fallback: bool
    album_upload_show_result: bool
    admins: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AlbumSettings:
    enabled: bool
    album_name: str
    album_id: str
    strict: bool
    base64_fallback: bool
    show_result: bool


@dataclass(slots=True)
class GroupContext:
    group_id: str
    group_folder_path: str
    admin_settings_path: str
    admin_settings: dict[str, Any]


@dataclass(slots=True)
class RenderNode:
    name: str
    avatar: str
    text: str = ""
    images: list[str] = field(default_factory=list)

