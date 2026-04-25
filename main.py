import os
import random
import time
import json
import yaml
import aiohttp
import re
import uuid
import html
import unicodedata
from PIL import Image as PILImage
from urllib.parse import urlparse
from astrbot import logger
from astrbot.core.message.components import Image, Reply, At, Plain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.all import *

@register("quote_collocter_plus", "ternurarl", "发送\"语录投稿+图片\"或\"入典+图片\"，也可回复图片发送\"语录投稿\"或\"入典\"来存储黑历史！发送\"/语录\"随机查看一条。bot会在被戳一戳时随机发送一张语录", "1.0")
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

    def __init__(self, context: Context):
        super().__init__(context)
        self.quotes_data_path = os.path.join('data', "quotes_data")
        
        # 从 astrbot 配置文件中获取管理员ID列表
        bot_config = context.get_config()
        admins = bot_config.get("admins_id", [])
        # 确保所有ID都是字符串格式
        self.admins = [str(admin) for admin in admins] if admins else []
        
        if self.admins:
            logger.info(f'从 astrbot 配置中获取到管理员ID列表: {self.admins}')
        else:
            logger.warning('未找到任何管理员ID，某些需要管理员权限的命令可能无法使用')

    #region 数据管理
    def create_main_folder(self):
        target_folder = os.path.join('data', "quotes_data")
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
            default_data = {'mode': 0}
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
        save_path = os.path.join("data", "quotes_data", group_id, filename)
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
                            file_path = os.path.join("data", "quotes_data", group_id, filename)
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
                            save_path = os.path.join("data", "quotes_data", group_id, filename)
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
                                    file_path = os.path.join("data", "quotes_data", group_id, filename)
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
                yield event.plain_result(f'⭐请输入"投稿权限+数字"来设置\n  0：关闭投稿系统\n  1：仅管理员可投稿\n  2：全体成员均可投稿\n当前群聊权限设置为：{self.admin_settings.get("mode", 0)}')
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

        elif msg.startswith("戳戳冷却"):
            if not self.is_admin(user_id):
                yield event.plain_result("权限不足，仅可由bot管理员设置")
                return
            set_coldown = self.gain_mode(event)
            if not set_coldown:
                yield event.plain_result('⭐请输入"戳戳冷却+数字"来设置，单位为秒\n')
                return
            if 'coldown' in self.admin_settings:
                self.admin_settings['coldown'] = int(set_coldown)
            else:
                self.admin_settings['coldown'] = 10
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
            current_mode = self.admin_settings.get('mode', 0)
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

                            if not file_id:
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
                        chain = [
                            Reply(id=msg_id),
                            Plain(text="⭐语录投稿成功！")
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
        if raw_message.get('post_type') == 'notice' and \
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
                cold_time = self.admin_settings.setdefault('coldown', 10)
                last_poke = self.admin_settings.setdefault('last_poke', 0)
                self._save_admin_settings()

                if time.time() - last_poke > cold_time:
                    self.admin_settings['last_poke'] = time.time()
                    self._save_admin_settings()
                    if str(target_id) == str(bot_id):
                        if random.random() < 0.85:
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
