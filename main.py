import os
import random
import time
import json
import base64
import yaml
import aiohttp
import re
import uuid
import html
import unicodedata
from PIL import Image as PILImage
from urllib.parse import urlparse
from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.core.message.components import Image, Reply, At, Plain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.all import *

@register("astrbot_plugin_quote_collocter_plus", "ternurarl", "发送\"语录投稿+图片\"或\"入典+图片\"，也可回复图片发送\"语录投稿\"或\"入典\"来存储黑历史！发送\"/语录\"随机查看一条。bot会在被戳一戳时随机发送一张语录", "1.4.1")
class Quote_Plugin(Star):
    BUBBLE_MIN_WIDTH = 140
    BUBBLE_MAX_WIDTH = 640
    BUBBLE_TEXT_MAX_LENGTH = 3000
    BUBBLE_FONT_SIZE = 16
    BUBBLE_LINE_HEIGHT = 1.6
    BUBBLE_BASE_PADDING = 56
    BUBBLE_MIN_WEIGHTED_CHARS = 6.0
    BUBBLE_MAX_WEIGHTED_CHARS = 120.0
    BUBBLE_CHAR_WIDTH_PX = 8.0
    BUBBLE_LINE_BONUS_PX = 16
    BUBBLE_MAX_LINE_BONUS_PX = 120
    BUBBLE_CONTAINER_EXTRA_WIDTH = 90
    BUBBLE_RENDER_SCALE = 1.5

    TMPL = '''
<style>html { margin: 0; padding: 0; background: transparent; width: fit-content; height: fit-content; } body { margin: 0; padding: 0; display: inline-block; background: transparent; width: fit-content; height: fit-content; overflow: hidden; }</style>
<div id="quote-card" style="display:inline-flex;align-items:flex-start;gap:10px;padding:12px;background:transparent;width:fit-content;max-width:{{ container_max_width }}px;box-sizing:border-box;zoom:{{ render_scale }};">
  <img src="{{ avatar }}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;" />
  <div style="display:flex;flex-direction:column;align-items:flex-start;max-width:{{ text_container_max_width }}px;">
    <div style="font-size:14px;color:#8c8c8c;line-height:1.4;margin-bottom:6px;">{{- name -}}</div>
    <div style="display:inline-block;background:#ffffff;border-radius:0 16px 16px 16px;padding:{{ bubble_padding }};color:#111111;font-size:{{ font_size }}px;line-height:{{ line_height }};white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;box-shadow:0 1px 2px rgba(0,0,0,0.06);width:fit-content;min-width:{{ min_width }}px;max-width:{{ max_width }}px;box-sizing:border-box;">{{- text -}}</div>
  </div>
</div>
'''

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        self.quotes_data_path = self._get_config_str("data_path", os.path.join("data", "quotes_data"))
        self.default_permission_mode = self._get_config_int("default_permission_mode", 0, min_value=0, max_value=2)
        self.default_poke_cooldown = self._get_config_int("default_poke_cooldown", 10, min_value=0)
        self.poke_quote_probability = self._get_config_float("poke_quote_probability", 0.85, min_value=0.0, max_value=1.0)
        self.enable_poke_reply = self._get_config_bool("enable_poke_reply", True)
        self.allow_text_quote_render = self._get_config_bool("allow_text_quote_render", True)
        self.BUBBLE_TEXT_MAX_LENGTH = self._get_config_int("text_quote_max_length", self.BUBBLE_TEXT_MAX_LENGTH, min_value=1)
        self.enable_album_upload = self._get_config_bool("enable_album_upload", False)
        self.album_name = self._get_config_str("album_name", "")
        self.album_id = self._get_config_str("album_id", "")
        self.album_upload_strict = self._get_config_bool("album_upload_strict", False)
        self.album_upload_use_base64_fallback = self._get_config_bool("album_upload_use_base64_fallback", True)
        self.album_upload_show_result = self._get_config_bool("album_upload_show_result", True)

        plugin_admins = self._normalize_admin_ids(self.config.get("admin_ids", []))
        global_admins = []
        if self._get_config_bool("use_global_admins", True):
            bot_config = context.get_config()
            global_admins = self._normalize_admin_ids(bot_config.get("admins_id", []))
        self.admins = sorted(set(plugin_admins + global_admins))
        
        if self.admins:
            logger.info(f'获取到插件管理员ID列表: {self.admins}')
        else:
            logger.warning('未找到任何管理员ID，某些需要管理员权限的命令可能无法使用')

    def _get_config_str(self, key, default):
        value = self.config.get(key, default)
        if value is None:
            return default
        value = str(value).strip()
        return value or default

    def _get_config_bool(self, key, default):
        value = self.config.get(key, default)
        return self._coerce_bool(value, default)

    def _coerce_bool(self, value, default=False):
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

    def _get_config_int(self, key, default, min_value=None, max_value=None):
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    def _get_config_float(self, key, default, min_value=None, max_value=None):
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    def _normalize_admin_ids(self, admins):
        if not admins:
            return []
        if isinstance(admins, (str, int)):
            admins = [admins]
        return [str(admin).strip() for admin in admins if str(admin).strip()]

    #region 数据管理
    def create_main_folder(self):
        target_folder = self.quotes_data_path
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)

    def create_group_folder(self, group_id):
        group_id = str(group_id)
        if not os.path.exists(self.quotes_data_path):
            self.create_main_folder()
        group_folder_path = os.path.join(self.quotes_data_path, group_id)
        if not os.path.exists(group_folder_path):
            os.makedirs(group_folder_path)
        
    def random_image_from_folder(self, folder_path):
        if not os.path.exists(folder_path): # 增加判断文件夹是否存在的逻辑
            return None
        files = os.listdir(folder_path)
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']
        images = [file for file in files if os.path.splitext(file)[1].lower() in image_extensions]
        if not images:
            return None
        random_image = random.choice(images)
        return os.path.join(folder_path, random_image)

    #region 权限管理
    def is_admin(self, user_id):
        return str(user_id) in self.admins

    def _create_admin_settings_file(self):
        try:
            default_data = {
                'mode': self.default_permission_mode,
                'coldown': self.default_poke_cooldown
            }
            with open(self.admin_settings_path, 'w', encoding='utf-8') as f:
                yaml.dump(default_data, f)
        except Exception as e:
            self.context.logger.error(f"创建模式文件失败: {str(e)}")

    def _load_admin_settings(self):
        try:
            with open(self.admin_settings_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            return data
        except Exception as e:
            self.context.logger.error(f"加载模式数据失败: {str(e)}")
            return {}

    def _save_admin_settings(self):
        try:
            with open(self.admin_settings_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.admin_settings, f, allow_unicode=True)
        except Exception as e:
            self.context.logger.error(f"保存模式数据失败: {str(e)}")

    def gain_mode(self, event):
        value = None
        msg = event.message_str.strip()
        if msg:
            match = re.search(r"[-+]?\d*\.?\d+", msg)
            if match:
                value = match.group()    
        return value

    def _extract_reply_text(self, chain):
        if isinstance(chain, list):
            texts = []
            for part in chain:
                if part.get('type') == 'text':
                    text = part.get('data', {}).get('text', '')
                    if text:
                        texts.append(text)
            return ''.join(texts).strip()

        if isinstance(chain, str):
            plain_text = re.sub(r'\[CQ:[^\]]+\]', '', chain)
            return plain_text.strip()

        return ''

    def _weighted_line_length(self, line: str) -> float:
        total = 0.0
        for ch in line:
            if ch == "\t":
                total += 2.0
            elif ch.isspace():
                total += 0.6
            elif unicodedata.east_asian_width(ch) in {"W", "F"}:
                total += 2.0
            else:
                total += 1.0
        return total

    def _prepare_render_text(self, value: str | None, *, fallback: str) -> str:
        value = "" if value is None else str(value)
        if len(value) > self.BUBBLE_TEXT_MAX_LENGTH:
            value = value[: self.BUBBLE_TEXT_MAX_LENGTH] + "…"
        if not value.strip():
            value = fallback
        return value

    def _calc_bubble_width(self, text: str) -> tuple[int, int]:
        lines = text.splitlines()
        if not lines:
            lines = [text]
        longest = max((self._weighted_line_length(line) for line in lines), default=0.0)
        line_count = max(len(lines), 1)
        clamped_longest = max(
            self.BUBBLE_MIN_WEIGHTED_CHARS,
            min(longest, self.BUBBLE_MAX_WEIGHTED_CHARS),
        )

        base_width = self.BUBBLE_BASE_PADDING + int(
            clamped_longest * self.BUBBLE_CHAR_WIDTH_PX
        )
        line_bonus = min((line_count - 1) * self.BUBBLE_LINE_BONUS_PX, self.BUBBLE_MAX_LINE_BONUS_PX)
        preferred_width = base_width + line_bonus

        max_width = max(self.BUBBLE_MIN_WIDTH, min(preferred_width, self.BUBBLE_MAX_WIDTH))
        min_width = min(self.BUBBLE_MIN_WIDTH, max_width)
        return min_width, max_width

    def _find_render_bbox(self, rgba: PILImage.Image) -> tuple[tuple[int, int, int, int] | None, int]:
        alpha_bbox = rgba.getchannel("A").getbbox()
        full_bbox = (0, 0, rgba.width, rgba.height)
        if alpha_bbox and alpha_bbox != full_bbox:
            return alpha_bbox, 8

        rgb = rgba.convert("RGB")
        background_colors = {
            rgb.getpixel((0, 0)),
            rgb.getpixel((rgba.width - 1, 0)),
            rgb.getpixel((0, rgba.height - 1)),
            rgb.getpixel((rgba.width - 1, rgba.height - 1)),
        }

        def is_background(pixel):
            return any(
                abs(pixel[0] - bg[0]) + abs(pixel[1] - bg[1]) + abs(pixel[2] - bg[2]) <= 48
                for bg in background_colors
            )

        min_x, min_y = rgba.width, rgba.height
        max_x, max_y = -1, -1
        pixels = rgb.load()
        for y in range(rgba.height):
            for x in range(rgba.width):
                if not is_background(pixels[x, y]):
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        if max_x >= min_x and max_y >= min_y:
            return (min_x, min_y, max_x + 1, max_y + 1), 24
        return alpha_bbox, 8

    async def _render_bubble_image(self, group_id, avatar, name, text):
        safe_name = html.escape(self._prepare_render_text(name, fallback="未知用户"))
        normalized_text = self._prepare_render_text(text, fallback="（空白内容）")
        safe_text = html.escape(normalized_text)
        min_width, max_width = self._calc_bubble_width(normalized_text)

        render_data = {
            "avatar": avatar,
            "name": safe_name,
            "text": safe_text,
            "min_width": min_width,
            "max_width": max_width,
            "container_max_width": max_width + self.BUBBLE_CONTAINER_EXTRA_WIDTH,
            "text_container_max_width": max_width,
            "bubble_padding": "10px 14px",
            "font_size": self.BUBBLE_FONT_SIZE,
            "line_height": self.BUBBLE_LINE_HEIGHT,
            "render_scale": self.BUBBLE_RENDER_SCALE,
        }
        render_options = {
            "full_page": True,
            "type": "png",
            "omit_background": True,
            "animations": "disabled",
            "caret": "hide"
        }
        image_url = await self.html_render(self.TMPL, render_data, return_url=False, options=render_options)
        if not image_url:
            return None

        filename = f"image_{uuid.uuid4().hex}.png"
        save_path = os.path.join(self.quotes_data_path, group_id, filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        try:
            is_saved = False
            # 1. 统一处理本地或远程的图片获取
            if os.path.exists(image_url):
                with open(image_url, "rb") as src, open(save_path, "wb") as dst:
                    dst.write(src.read())
                is_saved = True
            else:
                parsed = urlparse(image_url)
                if parsed.scheme == "file" and os.path.exists(parsed.path):
                    with open(parsed.path, "rb") as src, open(save_path, "wb") as dst:
                        dst.write(src.read())
                    is_saved = True
                elif image_url.startswith("http://") or image_url.startswith("https://"):
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url) as response:
                            if response.status == 200:
                                with open(save_path, "wb") as f:
                                    f.write(await response.read())
                                is_saved = True

            # 2. 图片获取成功后，执行精准裁剪
            if is_saved:
                with PILImage.open(save_path) as img:
                    rgba = img.convert("RGBA")
                    bbox, pad = self._find_render_bbox(rgba)

                    if bbox:
                        crop_box = (
                            max(0, bbox[0] - pad), 
                            max(0, bbox[1] - pad),
                            min(rgba.width, bbox[2] + pad), 
                            min(rgba.height, bbox[3] + pad)
                        )
                        cropped = rgba.crop(crop_box)

                        # 使用 PNG 保存，避免 JPEG 压缩让小字号文字和头像发糊
                        bg = PILImage.new("RGB", cropped.size, (255, 255, 255))
                        bg.paste(cropped, mask=cropped.getchannel("A"))
                        bg.save(save_path, "PNG", optimize=True)
                    else:
                        # 兜底转换
                        rgba.convert("RGB").save(save_path, "PNG", optimize=True)
                
                return save_path

        except Exception as e:
            logger.error(f"保存或裁剪渲染图片失败: {e}, image_url={image_url}")
        return None

    #region 群相册上传
    def _format_group_id_for_api(self, group_id):
        try:
            return int(group_id)
        except (TypeError, ValueError):
            return group_id

    async def _call_onebot_action(self, event: AstrMessageEvent, action: str, **payload):
        bot = getattr(event, "bot", None)
        api = getattr(bot, "api", None)
        if api and hasattr(api, "call_action"):
            return await api.call_action(action, **payload)
        if bot and hasattr(bot, "call_action"):
            return await bot.call_action(action, **payload)
        raise RuntimeError("当前平台不支持 OneBot API 调用")

    def _extract_album_list(self, payload):
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []

        candidates = [payload]
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

    def _album_item_id(self, album):
        value = album.get("album_id") or album.get("id")
        return str(value).strip() if value is not None else ""

    def _album_item_name(self, album):
        value = album.get("album_name") or album.get("name")
        return str(value).strip() if value is not None else ""

    async def _get_group_album_list(self, event: AstrMessageEvent, group_id):
        if not isinstance(event, AiocqhttpMessageEvent):
            logger.info("当前平台不是 aiocqhttp，无法获取群相册列表")
            return []

        api_group_id = self._format_group_id_for_api(group_id)
        actions = [
            ("get_qun_album_list", {"group_id": api_group_id, "attach_info": ""}),
            ("get_group_album_list", {"group_id": api_group_id}),
            ("get_group_albums", {"group_id": api_group_id}),
            ("get_group_root_album_list", {"group_id": api_group_id}),
        ]

        for action, payload in actions:
            try:
                result = await self._call_onebot_action(event, action, **payload)
                albums = self._extract_album_list(result)
                if albums:
                    logger.debug(f"通过 {action} 获取到 {len(albums)} 个群相册")
                    return albums
            except Exception as e:
                logger.debug(f"获取群相册列表接口 {action} 调用失败: {e}")
        return []

    def _get_effective_album_upload_settings(self):
        group_settings = getattr(self, "admin_settings", {}) or {}

        def get_bool(key, default):
            if key in group_settings:
                return self._coerce_bool(group_settings.get(key), default)
            return default

        def get_str(key, default):
            value = group_settings.get(key, default)
            if value is None:
                return ""
            return str(value).strip()

        return {
            "enabled": get_bool("album_upload_enabled", self.enable_album_upload),
            "album_name": get_str("album_name", self.album_name),
            "album_id": get_str("album_id", self.album_id),
            "strict": get_bool("album_upload_strict", self.album_upload_strict),
            "base64_fallback": get_bool("album_upload_use_base64_fallback", self.album_upload_use_base64_fallback),
            "show_result": get_bool("album_upload_show_result", self.album_upload_show_result),
        }

    async def _resolve_album_target(self, event: AstrMessageEvent, group_id, settings):
        album_id = settings["album_id"]
        album_name = settings["album_name"]
        albums = []

        if album_name and not album_id:
            albums = await self._get_group_album_list(event, group_id)
            for album in albums:
                if self._album_item_name(album) == album_name:
                    album_id = self._album_item_id(album)
                    if album_id:
                        return album_id, album_name, ""

            message = f"未找到名为“{album_name}”的群相册"
            if settings["strict"]:
                logger.info(message)
            return "", "", message

        if album_id and not album_name:
            albums = await self._get_group_album_list(event, group_id)
            for album in albums:
                if self._album_item_id(album) == album_id:
                    album_name = self._album_item_name(album)
                    break

        if not album_id:
            return "", "", "未配置目标相册 ID 或名称"

        return album_id, album_name, ""

    def _read_file_as_base64(self, file_path):
        try:
            if not os.path.exists(file_path):
                return None
            with open(file_path, "rb") as f:
                return f"base64://{base64.b64encode(f.read()).decode('utf-8')}"
        except Exception as e:
            logger.error(f"读取图片并转换 Base64 失败: {e}")
            return None

    async def _call_album_upload(self, event: AstrMessageEvent, group_id, album_id, album_name, file_value):
        api_group_id = self._format_group_id_for_api(group_id)
        params = {
            "group_id": api_group_id,
            "album_id": str(album_id),
            "album_name": album_name or "",
            "file": file_value,
        }
        llbot_params = {
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
                await self._call_onebot_action(event, action, **payload)
                logger.info(f"群相册上传成功: action={action}, group_id={group_id}, album_id={album_id}")
                return True, action
            except Exception as e:
                last_error = e
                logger.debug(f"群相册上传接口 {action} 调用失败: {e}")

        return False, str(last_error) if last_error else "所有相册上传接口均调用失败"

    async def _upload_image_to_group_album(self, event: AstrMessageEvent, group_id, image_path, settings):
        if not isinstance(event, AiocqhttpMessageEvent):
            return False, "当前平台不支持群相册上传"
        if not image_path or not os.path.exists(image_path):
            return False, "图片文件不存在"

        album_id, album_name, reason = await self._resolve_album_target(event, group_id, settings)
        if not album_id:
            return False, reason or "未找到目标相册"

        abs_path = os.path.abspath(image_path)
        ok, detail = await self._call_album_upload(event, group_id, album_id, album_name, abs_path)
        if ok:
            return True, detail

        if settings["base64_fallback"]:
            encoded = self._read_file_as_base64(abs_path)
            if encoded:
                ok, detail = await self._call_album_upload(event, group_id, album_id, album_name, encoded)
                if ok:
                    return True, detail

        return False, detail

    async def _album_upload_result_suffix(self, event: AstrMessageEvent, group_id, image_path):
        settings = self._get_effective_album_upload_settings()
        if not settings["enabled"]:
            return ""

        ok, detail = await self._upload_image_to_group_album(event, group_id, image_path, settings)
        if not settings["show_result"]:
            return ""
        if ok:
            return "\n已上传到群相册"
        return f"\n群相册上传失败：{detail}"

    def _format_album_upload_status(self):
        settings = self._get_effective_album_upload_settings()
        enabled_text = "开启" if settings["enabled"] else "关闭"
        strict_text = "开启" if settings["strict"] else "关闭"
        fallback_text = "开启" if settings["base64_fallback"] else "关闭"
        album_name = settings["album_name"] or "未配置"
        album_id = settings["album_id"] or "未配置"
        return (
            f"⭐群相册上传：{enabled_text}\n"
            f"目标相册名称：{album_name}\n"
            f"目标相册ID：{album_id}\n"
            f"严格匹配：{strict_text}\n"
            f"Base64兜底：{fallback_text}"
        )

    async def _handle_album_command(self, event: AstrMessageEvent, group_id, msg):
        args = msg[len("语录相册"):].strip()
        if args in {"", "状态"}:
            return self._format_album_upload_status()

        if args in {"开启", "启用", "打开"}:
            self.admin_settings["album_upload_enabled"] = True
            self._save_admin_settings()
            return "⭐群相册上传已开启"

        if args in {"关闭", "禁用", "关"}:
            self.admin_settings["album_upload_enabled"] = False
            self._save_admin_settings()
            return "⭐群相册上传已关闭"

        if args in {"严格开启", "开启严格"}:
            self.admin_settings["album_upload_strict"] = True
            self._save_admin_settings()
            return "⭐群相册严格匹配已开启"

        if args in {"严格关闭", "关闭严格"}:
            self.admin_settings["album_upload_strict"] = False
            self._save_admin_settings()
            return "⭐群相册严格匹配已关闭"

        if args in {"重置", "清除"}:
            for key in ("album_upload_enabled", "album_name", "album_id", "album_upload_strict"):
                self.admin_settings.pop(key, None)
            self._save_admin_settings()
            return "⭐群相册上传设置已恢复为插件配置"

        if args == "列表":
            albums = await self._get_group_album_list(event, group_id)
            if not albums:
                return "⭐未获取到群相册列表，请确认当前协议端支持 NapCat 群相册接口"
            lines = ["⭐群相册列表："]
            for album in albums[:20]:
                name = self._album_item_name(album) or "未命名相册"
                aid = self._album_item_id(album) or "无ID"
                lines.append(f"{name}：{aid}")
            if len(albums) > 20:
                lines.append(f"仅显示前20个，共{len(albums)}个")
            return "\n".join(lines)

        if args.startswith("名称"):
            album_name = args[len("名称"):].strip()
            if not album_name:
                return "⭐请输入相册名称，例如：语录相册 名称 黑历史"
            self.admin_settings["album_name"] = album_name
            self._save_admin_settings()
            return f"⭐目标相册名称已设置为：{album_name}"

        upper_args = args.upper()
        if upper_args.startswith("ID"):
            album_id = args[2:].strip()
            if not album_id:
                return "⭐请输入相册ID，例如：语录相册 ID 123456"
            self.admin_settings["album_id"] = album_id
            self._save_admin_settings()
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

    #region 下载语录图片
    async def download_image(self, event: AstrMessageEvent, file_id: str, group_id) -> bytes:
        try:
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot

            payloads = {
                "file_id": file_id
            }
            download_by_api_failed = 0
            download_by_file_failed = 0

            message_obj = event.message_obj
            image_obj = None
            
            # 尝试从当前消息中找到 Image 对象
            for i in message_obj.message:
                if isinstance(i, Image):
                    image_obj = i
                    break
            
            if image_obj:
                file_path = await image_obj.convert_to_file_path()
                if file_path:
                    logger.info(f"尝试从本地缓存{file_path}读取图片")
                    try:
                        with open(file_path, 'rb') as f:
                            data = f.read()
                            filename = f"image_{int(time.time() * 1000)}.jpg"
                            file_path = os.path.join(self.quotes_data_path, group_id, filename)
                            os.makedirs(os.path.dirname(file_path), exist_ok=True)
                            with open(file_path, 'wb') as f:
                                f.write(data)
                                logger.info(f"图片已保存到 {file_path}")
                                return file_path
                    except Exception as e:
                        download_by_file_failed = 1
                        logger.error(f"在读取本地缓存时遇到问题: {str(e)}")
                else:
                    download_by_file_failed = 1
            else:
                download_by_file_failed = 1

            if download_by_file_failed == 1 :
                result = await client.api.call_action('get_image', **payloads)
                
                file_path = result.get('file')
                if file_path and os.path.exists(file_path):
                    logger.info(f"尝试从协议端api返回的路径{file_path}读取图片")
                    try:
                        with open(file_path, 'rb') as f:
                            data = f.read()
                            filename = f"image_{int(time.time() * 1000)}.jpg"
                            save_path = os.path.join(self.quotes_data_path, group_id, filename)
                            os.makedirs(os.path.dirname(save_path), exist_ok=True)
                            with open(save_path, 'wb') as f:
                                f.write(data)
                                logger.info(f"图片已保存到 {save_path}")
                        return save_path
                    except Exception as e:
                        download_by_api_failed = 1
                        logger.error(f"在通过api下载图片时遇到问题: {str(e)}")
                else:
                    download_by_api_failed = 1

            if download_by_api_failed == 1 and download_by_file_failed == 1 :
                url = result.get('url')
                if url:
                    logger.info(f"尝试从URL下载图片: {url}")
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(url) as response:
                                if response.status == 200:
                                    data = await response.read()
                                    filename = f"image_{int(time.time() * 1000)}.jpg"
                                    file_path = os.path.join(self.quotes_data_path, group_id, filename)
                                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                                    with open(file_path, 'wb') as f:
                                        f.write(data)
                                        logger.info(f"图片已保存到 {file_path}")
                                    return file_path
                                else:
                                    logger.error(f"从URL下载图片失败: HTTP {response.status}")
                    except Exception as e:
                        logger.error(f"从URL下载出错: {str(e)}")
                else:
                    logger.error("API返回结果中没有URL，无法下载")
        except Exception as e:
            raise Exception(f"{str(e)}")

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        group_id = str(event.message_obj.group_id)
        user_id = str(event.get_sender_id())
        message_obj = event.message_obj
        raw_message = message_obj.raw_message
        msg = event.message_str.strip()
        group_folder_path = os.path.join(self.quotes_data_path, group_id)

        if not os.path.exists(group_folder_path):
            self.create_group_folder(group_id)
        self.admin_settings_path = os.path.join(group_folder_path, 'admin_settings.yml') 
        if not os.path.exists(self.admin_settings_path):
            self._create_admin_settings_file()
        self.admin_settings = self._load_admin_settings()

        # region 投稿系统
        if msg.startswith("投稿权限"):
            if not self.is_admin(user_id):
                yield event.plain_result("权限不足，仅可由bot管理员设置")
                return
            set_mode = self.gain_mode(event)
            if not set_mode:
                yield event.plain_result(f'⭐请输入"投稿权限+数字"来设置\n  0：关闭投稿系统\n  1：仅管理员可投稿\n  2：全体成员均可投稿\n当前群聊权限设置为：{self.admin_settings.get("mode", self.default_permission_mode)}')
            else:
                if set_mode not in ["0", "1", "2"]:
                    yield event.plain_result("⭐模式数字范围出错！请输入正确的模式\n  0：关闭投稿系统\n  1：仅管理员可投稿\n  2：全体成员均可投稿")
                    return
                self.admin_settings['mode'] = int(set_mode)
                self._save_admin_settings()
                texts = f"⭐投稿权限设置成功，当前状态为："
                if self.admin_settings['mode'] == 0:
                    texts += "\n  0：关闭投稿系统"
                elif self.admin_settings['mode'] == 1:
                    texts += "\n  1：仅管理员可投稿"
                elif self.admin_settings['mode'] == 2:
                    texts += "\n  2：全体成员均可投稿"
                yield event.plain_result(texts)

        elif msg.startswith("语录相册"):
            if not self.is_admin(user_id):
                yield event.plain_result("权限不足，仅可由bot管理员设置")
                return
            result = await self._handle_album_command(event, group_id, msg)
            yield event.plain_result(result)

        elif msg.startswith("戳戳冷却"):
            if not self.is_admin(user_id):
                yield event.plain_result("权限不足，仅可由bot管理员设置")
                return
            set_coldown = self.gain_mode(event)
            if not set_coldown:
                yield event.plain_result('⭐请输入"戳戳冷却+数字"来设置，单位为秒\n')
                return
            self.admin_settings['coldown'] = max(0, int(float(set_coldown)))
            self._save_admin_settings()
            yield event.plain_result(f"⭐戳戳冷却设置成功，当前值为：{self.admin_settings['coldown']}秒")
        
        # --- 随机语录指令 ---
        elif msg == "/语录" or msg == "语录":
            group_folder_path = os.path.join(self.quotes_data_path, group_id)
            selected_image_path = None
            if os.path.exists(group_folder_path):
                selected_image_path = self.random_image_from_folder(group_folder_path)
            
            if selected_image_path:
                yield event.image_result(selected_image_path)
            else:
                yield event.plain_result('⭐本群还没有群友语录哦~\n请发送"语录投稿+图片"进行添加！')
        # --------------------

        elif msg.startswith("语录投稿") or msg.startswith("入典"):
            current_mode = self.admin_settings.get('mode', self.default_permission_mode)
            if current_mode == 0:
                yield event.plain_result('⭐投稿系统未开启，请联系bot管理员发送"投稿权限"来设置')
                return
            if current_mode == 1:
                if not self.is_admin(user_id):
                    yield event.plain_result('⭐权限不足，当前权限设置为"仅bot管理员可投稿"\n可由bot管理员发送"投稿权限"来设置')
                    return
            
            file_id = None
            rendered_path = None
            
            # 1. 检查当前消息中是否有图片
            messages = event.message_obj.message
            image_comp = next((msg for msg in messages if isinstance(msg, Image)), None)
            
            if image_comp:
                file_id = image_comp.file
            else:
                # 2. 如果当前消息没图片，检查是否引用了消息
                reply_comp = next((msg for msg in messages if isinstance(msg, Reply)), None)
                if reply_comp:
                    try:
                        logger.info(f"检测到引用回复，尝试获取消息ID: {reply_comp.id}")
                        reply_id = int(reply_comp.id) if str(reply_comp.id).isdigit() else reply_comp.id
                        reply_msg = await event.bot.api.call_action('get_msg', message_id=reply_id)
                        
                        if reply_msg and 'message' in reply_msg:
                            chain = reply_msg['message']
                            if isinstance(chain, list):
                                for part in chain:
                                    if part.get('type') == 'image':
                                        file_id = part.get('data', {}).get('file')
                                        break
                            elif isinstance(chain, str):
                                match = re.search(r'\[CQ:image,[^\]]*file=([^,\]]+)', chain)
                                if match:
                                    file_id = match.group(1)

                            if not file_id and self.allow_text_quote_render:
                                reply_text = self._extract_reply_text(chain)
                                if reply_text:
                                    sender = reply_msg.get("sender", {}) if isinstance(reply_msg, dict) else {}
                                    sender_id = sender.get("user_id")
                                    sender_card = sender.get("card")
                                    sender_nickname = sender.get("nickname")
                                    sender_name = sender_card or sender_nickname or (str(sender_id) if sender_id is not None else "未知用户")
                                    sender_avatar = f"https://q1.qlogo.cn/g?b=qq&nk={sender_id}&s=640" if sender_id else event.get_sender_avatar()
                                    rendered_path = await self._render_bubble_image(
                                        group_id=group_id,
                                        avatar=sender_avatar,
                                        name=sender_name,
                                        text=reply_text
                                    )

                    except Exception as e:
                        logger.error(f"获取引用消息失败: {e}")

            if not file_id and not rendered_path:
                chain = [
                    At(qq=user_id),
                    Plain(text="\n你是不是忘发图啦？\n请直接发送\"语录投稿+图片\"或\"入典+图片\"\n或者引用图片并发送\"语录投稿\"/\"入典\"")
                ]
                yield event.chain_result(chain)
                return
                            
            try:
                self.create_group_folder(group_id)
                # 下载并保存图片
                try:
                    if rendered_path:
                        file_path = rendered_path
                    elif file_id:
                        file_path = await self.download_image(event, file_id, group_id)
                    else:
                        file_path = None
                    msg_id = str(event.message_obj.message_id)
                    
                    if file_path and os.path.exists(file_path):
                        result_text = "⭐语录投稿成功！"
                        result_text += await self._album_upload_result_suffix(event, group_id, file_path)
                        chain = [
                            Reply(id=msg_id),
                            Plain(text=result_text)
                        ]
                    else:
                        chain = [
                            Reply(id=msg_id),
                            Plain(text="⭐语录投稿失败，图片下载失败")
                        ]
                    yield event.chain_result(chain)
                except Exception as e:
                    logger.error(f"投稿过程出错: {e}")
                    yield event.plain_result(f"⭐投稿失败: {str(e)}")

            except Exception as e:
                yield (event.make_result().message(f"\n错误信息：{str(e)}"))

        #region 戳一戳检测
        if self.enable_poke_reply and \
                raw_message.get('post_type') == 'notice' and \
                raw_message.get('notice_type') == 'notify' and \
                raw_message.get('sub_type') == 'poke':
            bot_id = raw_message.get('self_id')
            sender_id = raw_message.get('user_id')
            target_id = raw_message.get('target_id')
            if bot_id and sender_id and target_id:

                if not os.path.exists(group_folder_path):
                    self.create_group_folder(group_id)
                self.admin_settings_path = os.path.join(group_folder_path, 'admin_settings.yml') 
                if not os.path.exists(self.admin_settings_path):
                    self._create_admin_settings_file()
                self.admin_settings = self._load_admin_settings()
                cold_time = self.admin_settings.setdefault('coldown', self.default_poke_cooldown)
                last_poke = self.admin_settings.setdefault('last_poke', 0)
                self._save_admin_settings()

                if time.time() - last_poke > cold_time:
                    self.admin_settings['last_poke'] = time.time()
                    self._save_admin_settings()
                    if str(target_id) == str(bot_id):
                        if random.random() < self.poke_quote_probability:
                            group_folder_path = os.path.join(self.quotes_data_path, group_id)
                            selected_image_path = None
                            if os.path.exists(group_folder_path):
                                selected_image_path = self.random_image_from_folder(group_folder_path)
                            
                            if not selected_image_path:
                                return # 无语录时静默
                            
                            yield event.image_result(selected_image_path)
                        else:                   
                            texts = [
                                "\n再戳的话......说不定下一张就是你的！",
                                "\n我会一直一直看着你👀",
                                "\n给我出列！",
                            ]
                            selected_text = random.choice(texts)
                            chain = [
                                At(qq=sender_id),
                                Plain(text=selected_text)
                            ]
                            yield event.chain_result(chain)
                else:
                    remaining = cold_time - (time.time() - last_poke)
                    logger.info(f"爆典功能冷却中，剩余{remaining:.0f}秒")
