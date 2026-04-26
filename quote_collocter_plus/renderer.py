from __future__ import annotations

import html
import os
import unicodedata
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import aiohttp
from PIL import Image as PILImage

from .message_parser import MessageParser
from .models import PluginSettings, RenderNode
from .storage import QuoteStorage


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

FORWARD_TMPL = '''
<style>html { margin: 0; padding: 0; background: transparent; width: fit-content; height: fit-content; } body { margin: 0; padding: 0; display: inline-block; background: transparent; width: fit-content; height: fit-content; overflow: hidden; }</style>
<div id="forward-card" style="display:flex;flex-direction:column;gap:14px;padding:12px;background:transparent;width:fit-content;max-width:{{ container_max_width }}px;box-sizing:border-box;zoom:{{ render_scale }};">
{% for node in nodes %}
  <div style="display:flex;align-items:flex-start;gap:10px;width:fit-content;max-width:{{ container_max_width }}px;">
    <img src="{{ node.avatar }}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;flex:0 0 40px;" />
    <div style="display:flex;flex-direction:column;align-items:flex-start;gap:8px;max-width:{{ content_max_width }}px;">
      <div style="font-size:14px;color:#8c8c8c;line-height:1.4;">{{- node.name -}}</div>
      {% if node.text %}
      <div style="display:inline-block;background:#ffffff;border-radius:0 16px 16px 16px;padding:10px 14px;color:#111111;font-size:{{ font_size }}px;line-height:{{ line_height }};white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;box-shadow:0 1px 2px rgba(0,0,0,0.06);width:fit-content;min-width:{{ min_width }}px;max-width:{{ text_max_width }}px;box-sizing:border-box;">{{- node.text -}}</div>
      {% endif %}
      {% for image in node.images %}
      <img src="{{ image.src }}" style="display:block;max-width:{{ image_max_width }}px;max-height:520px;border-radius:8px;object-fit:contain;box-shadow:0 1px 2px rgba(0,0,0,0.06);" />
      {% endfor %}
    </div>
  </div>
{% endfor %}
</div>
'''


class QuoteRenderer:
    BUBBLE_MIN_WIDTH = 140
    BUBBLE_MAX_WIDTH = 640
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
    FORWARD_CONTAINER_WIDTH = 720
    FORWARD_TEXT_MAX_WIDTH = 560
    FORWARD_IMAGE_MAX_WIDTH = 420

    def __init__(
        self,
        settings: PluginSettings,
        storage: QuoteStorage | None = None,
        parser: MessageParser | None = None,
        html_render: Callable[..., Awaitable[str]] | None = None,
        logger: Any = None,
    ):
        self.settings = settings
        self.storage = storage
        self.parser = parser or MessageParser()
        self.html_render = html_render
        self.logger = logger

    @property
    def text_max_length(self) -> int:
        return self.settings.text_quote_max_length

    def _error(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "error"):
            self.logger.error(message)

    def prepare_forward_render_nodes(self, nodes: list[RenderNode | dict[str, Any]]) -> list[dict[str, Any]]:
        prepared = []
        remaining = self.text_max_length

        for node in nodes:
            if isinstance(node, RenderNode):
                name = node.name
                avatar = node.avatar
                text_value = node.text
                image_values = node.images
            else:
                name = node.get("name")
                avatar = node.get("avatar")
                text_value = node.get("text")
                image_values = node.get("images", [])

            text = "" if text_value is None else str(text_value).strip()
            if text:
                if remaining <= 0:
                    text = ""
                elif len(text) > remaining:
                    text = text[:remaining] + "…"
                    remaining = 0
                else:
                    remaining -= len(text)

            images = [
                {"src": html.escape(src, quote=True)}
                for src in self.parser.dedupe_strings(image_values)
            ]
            if not text and not images:
                continue

            prepared.append({
                "name": html.escape(self.prepare_render_text(name, fallback="未知用户")),
                "avatar": html.escape(str(avatar or ""), quote=True),
                "text": html.escape(text) if text else "",
                "images": images,
            })

        return prepared

    async def render_forward_image(self, group_id: str, nodes: list[RenderNode | dict[str, Any]]) -> str | None:
        if not self.html_render:
            return None
        render_nodes = self.prepare_forward_render_nodes(nodes)
        if not render_nodes:
            return None

        render_data = {
            "nodes": render_nodes,
            "container_max_width": self.FORWARD_CONTAINER_WIDTH,
            "content_max_width": max(self.FORWARD_TEXT_MAX_WIDTH, self.FORWARD_IMAGE_MAX_WIDTH),
            "text_max_width": self.FORWARD_TEXT_MAX_WIDTH,
            "image_max_width": self.FORWARD_IMAGE_MAX_WIDTH,
            "min_width": self.BUBBLE_MIN_WIDTH,
            "font_size": self.BUBBLE_FONT_SIZE,
            "line_height": self.BUBBLE_LINE_HEIGHT,
            "render_scale": self.BUBBLE_RENDER_SCALE,
        }
        render_options = {
            "full_page": True,
            "type": "png",
            "omit_background": True,
            "animations": "disabled",
            "caret": "hide",
        }
        image_url = await self.html_render(
            FORWARD_TMPL,
            render_data,
            return_url=False,
            options=render_options,
        )
        if not image_url:
            return None
        return await self.save_rendered_image(group_id, image_url)

    def weighted_line_length(self, line: str) -> float:
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

    def prepare_render_text(self, value: str | None, *, fallback: str) -> str:
        value = "" if value is None else str(value)
        if len(value) > self.text_max_length:
            value = value[: self.text_max_length] + "…"
        if not value.strip():
            value = fallback
        return value

    def calc_bubble_width(self, text: str) -> tuple[int, int]:
        lines = text.splitlines()
        if not lines:
            lines = [text]
        longest = max((self.weighted_line_length(line) for line in lines), default=0.0)
        line_count = max(len(lines), 1)
        clamped_longest = max(
            self.BUBBLE_MIN_WEIGHTED_CHARS,
            min(longest, self.BUBBLE_MAX_WEIGHTED_CHARS),
        )

        base_width = self.BUBBLE_BASE_PADDING + int(
            clamped_longest * self.BUBBLE_CHAR_WIDTH_PX
        )
        line_bonus = min(
            (line_count - 1) * self.BUBBLE_LINE_BONUS_PX,
            self.BUBBLE_MAX_LINE_BONUS_PX,
        )
        preferred_width = base_width + line_bonus

        max_width = max(self.BUBBLE_MIN_WIDTH, min(preferred_width, self.BUBBLE_MAX_WIDTH))
        min_width = min(self.BUBBLE_MIN_WIDTH, max_width)
        return min_width, max_width

    def find_render_bbox(
        self,
        rgba: PILImage.Image,
    ) -> tuple[tuple[int, int, int, int] | None, int]:
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

        def is_background(pixel: tuple[int, int, int]) -> bool:
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

    async def save_rendered_image(self, group_id: str, image_url: str) -> str | None:
        if not self.storage:
            return None
        filename = f"image_{os.urandom(16).hex()}.png"
        save_path = os.path.join(self.storage.create_group_folder(group_id), filename)

        try:
            is_saved = False
            if os.path.exists(image_url):
                with open(image_url, "rb") as src, open(save_path, "wb") as dst:
                    dst.write(src.read())
                is_saved = True
            else:
                parsed = urlparse(image_url)
                if parsed.scheme == "file":
                    local_path = self.parser.path_from_file_uri(image_url)
                    if os.path.exists(local_path):
                        with open(local_path, "rb") as src, open(save_path, "wb") as dst:
                            dst.write(src.read())
                        is_saved = True
                elif image_url.startswith(("http://", "https://")):
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url) as response:
                            if response.status == 200:
                                with open(save_path, "wb") as f:
                                    f.write(await response.read())
                                is_saved = True

            if is_saved:
                with PILImage.open(save_path) as img:
                    rgba = img.convert("RGBA")
                    bbox, pad = self.find_render_bbox(rgba)

                    if bbox:
                        crop_box = (
                            max(0, bbox[0] - pad),
                            max(0, bbox[1] - pad),
                            min(rgba.width, bbox[2] + pad),
                            min(rgba.height, bbox[3] + pad),
                        )
                        cropped = rgba.crop(crop_box)

                        bg = PILImage.new("RGB", cropped.size, (255, 255, 255))
                        bg.paste(cropped, mask=cropped.getchannel("A"))
                        bg.save(save_path, "PNG", optimize=True)
                    else:
                        rgba.convert("RGB").save(save_path, "PNG", optimize=True)

                return save_path

        except Exception as e:
            self._error(f"保存或裁剪渲染图片失败: {e}, image_url={image_url}")
        return None

    async def render_bubble_image(self, group_id: str, avatar: str, name: str, text: str) -> str | None:
        if not self.html_render:
            return None
        safe_name = html.escape(self.prepare_render_text(name, fallback="未知用户"))
        normalized_text = self.prepare_render_text(text, fallback="（空白内容）")
        safe_text = html.escape(normalized_text)
        min_width, max_width = self.calc_bubble_width(normalized_text)

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
            "caret": "hide",
        }
        image_url = await self.html_render(
            TMPL,
            render_data,
            return_url=False,
            options=render_options,
        )
        if not image_url:
            return None

        return await self.save_rendered_image(group_id, image_url)
