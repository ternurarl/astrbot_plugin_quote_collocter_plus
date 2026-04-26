from __future__ import annotations

import base64
import os
import random
import uuid
from typing import Any

import yaml

from .models import GroupContext, PluginSettings


class QuoteStorage:
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}

    def __init__(self, settings: PluginSettings, logger: Any = None):
        self.settings = settings
        self.logger = logger

    @property
    def data_path(self) -> str:
        return self.settings.data_path

    def _error(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "error"):
            self.logger.error(message)

    def _info(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "info"):
            self.logger.info(message)

    def create_main_folder(self) -> None:
        os.makedirs(self.data_path, exist_ok=True)

    def group_folder_path(self, group_id: str) -> str:
        return os.path.join(self.data_path, str(group_id))

    def create_group_folder(self, group_id: str) -> str:
        self.create_main_folder()
        group_folder_path = self.group_folder_path(group_id)
        os.makedirs(group_folder_path, exist_ok=True)
        return group_folder_path

    def random_image_from_folder(self, folder_path: str) -> str | None:
        if not os.path.exists(folder_path):
            return None
        files = os.listdir(folder_path)
        images = [
            file
            for file in files
            if os.path.splitext(file)[1].lower() in self.IMAGE_EXTENSIONS
        ]
        if not images:
            return None
        return os.path.join(folder_path, random.choice(images))

    def random_image_from_group(self, group_id: str) -> str | None:
        return self.random_image_from_folder(self.group_folder_path(group_id))

    def admin_settings_path(self, group_id: str) -> str:
        return os.path.join(self.group_folder_path(group_id), "admin_settings.yml")

    def default_admin_settings(self) -> dict[str, Any]:
        return {
            "mode": self.settings.default_permission_mode,
            "coldown": self.settings.default_poke_cooldown,
        }

    def create_admin_settings_file(self, path: str) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(self.default_admin_settings(), f)
        except Exception as e:
            self._error(f"创建模式文件失败: {str(e)}")

    def load_admin_settings(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self._error(f"加载模式数据失败: {str(e)}")
            return {}

    def save_admin_settings(self, path: str, settings: dict[str, Any]) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(settings, f, allow_unicode=True)
        except Exception as e:
            self._error(f"保存模式数据失败: {str(e)}")

    def load_group_context(self, group_id: str) -> GroupContext:
        group_id = str(group_id)
        group_folder_path = self.create_group_folder(group_id)
        admin_settings_path = self.admin_settings_path(group_id)
        if not os.path.exists(admin_settings_path):
            self.create_admin_settings_file(admin_settings_path)
        return GroupContext(
            group_id=group_id,
            group_folder_path=group_folder_path,
            admin_settings_path=admin_settings_path,
            admin_settings=self.load_admin_settings(admin_settings_path),
        )

    def save_group_context(self, group_context: GroupContext) -> None:
        self.save_admin_settings(
            group_context.admin_settings_path,
            group_context.admin_settings,
        )

    def image_extension_from_bytes(self, data: bytes) -> str:
        if data.startswith(b"\x89PNG"):
            return ".png"
        if data.startswith(b"GIF8"):
            return ".gif"
        if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
            return ".webp"
        if data.startswith(b"BM"):
            return ".bmp"
        return ".jpg"

    def save_image_bytes(self, data: bytes, group_id: str) -> str | None:
        if not data:
            return None
        filename = f"image_{uuid.uuid4().hex}{self.image_extension_from_bytes(data)}"
        save_path = os.path.join(self.create_group_folder(group_id), filename)
        with open(save_path, "wb") as f:
            f.write(data)
        self._info(f"图片已保存到 {save_path}")
        return save_path

    def read_file_as_base64(self, file_path: str) -> str | None:
        try:
            if not os.path.exists(file_path):
                return None
            with open(file_path, "rb") as f:
                return f"base64://{base64.b64encode(f.read()).decode('utf-8')}"
        except Exception as e:
            self._error(f"读取图片并转换 Base64 失败: {e}")
            return None
