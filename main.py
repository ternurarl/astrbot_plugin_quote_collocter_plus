import os
import random
import time
import json
import yaml
import aiohttp
import re
import unicodedata
from astrbot import logger
from astrbot.core.message.components import Image, Reply, At, Plain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.all import *

QQBOX_DEFAULT_MAX_LINES = 18
QQBOX_DEFAULT_MAX_CHARS = 600
DEFAULT_BUBBLE_STYLE = "white_bubble"
DEFAULT_AVATAR_URL = "https://api.dicebear.com/7.x/bottts/svg?seed=astrbot"
MAX_SPEAKER_NAME_LENGTH = 30
RENDER_OUTPUT_SCHEMES = ("http://", "https://", "file://", "data:")

WHITE_BUBBLE_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      background: #eef2fc;
      font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      color: #222;
    }
    .wrap {
      width: 100%;
      max-width: 980px;
      margin: 0 auto;
    }
    .msg {
      display: flex;
      align-items: flex-start;
      gap: 14px;
    }
    .avatar {
      width: 58px;
      height: 58px;
      border-radius: 50%;
      object-fit: cover;
      flex: 0 0 auto;
      background: #dbe3f3;
      border: 1px solid #c7d2ea;
    }
    .content {
      max-width: 760px;
      min-width: 180px;
    }
    .name {
      font-size: 20px;
      color: #4a5a78;
      margin-bottom: 8px;
      line-height: 1.2;
    }
    .bubble {
      position: relative;
      display: inline-block;
      background: #fff;
      border: 1px solid #d4dde8;
      border-radius: 18px;
      padding: 14px 18px;
      font-size: 24px;
      line-height: 1.5;
      color: #222833;
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: 0 2px 8px rgba(120, 138, 170, 0.18);
    }
    .bubble::before {
      content: "";
      position: absolute;
      left: -10px;
      top: 18px;
      width: 14px;
      height: 14px;
      background: #fff;
      border-left: 1px solid #d4dde8;
      border-bottom: 1px solid #d4dde8;
      transform: rotate(45deg);
      border-bottom-left-radius: 3px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    {% for msg in messages %}
      <div class="msg">
        <img class="avatar" src="{{ msg.avatar }}" alt="avatar">
        <div class="content">
          <div class="name">{{ msg.name }}</div>
          <div class="bubble">{{ msg.text }}</div>
        </div>
      </div>
    {% endfor %}
  </div>
</body>
</html>
"""

@register("quote_collocter_plus", "ternurarl", '发送"语录投稿/入典+图片"或回复图片/文本发送"语录投稿"/"入典"来存储群友的黑历史！发送"/语录"随机查看一条。bot会在被戳一戳时随机发送一张语录', "1.0")
class Quote_Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        
        # 从 astrbot 配置文件中获取管理员ID列表
        bot_config = context.get_config()
        self.data_root_path = self._resolve_data_root(bot_config)
        self.quotes_data_path = os.path.join(self.data_root_path, "quotes_data")
        self.create_main_folder()
        self._check_storage_writable()

        admins = bot_config.get("admins_id", [])
        # 确保所有ID都是字符串格式
        self.admins = [str(admin) for admin in admins] if admins else []
        self.render_config = self._load_render_config(bot_config)
        
        if self.admins:
            logger.info(f'从 astrbot 配置中获取到管理员ID列表: {self.admins}')
        else:
            logger.warning('未找到任何管理员ID，某些需要管理员权限的命令可能无法使用')

    def _load_render_config(self, bot_config):
        def _get(*keys, default=None):
            for k in keys:
                v = bot_config.get(k)
                if v is not None:
                    return v
            return default

        def _as_int(v, default):
            try:
                return int(v)
            except Exception:
                return default

        def _as_bool(v, default=False):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                return v.strip().lower() in {"1", "true", "yes", "y", "on"}
            return default

        style = str(_get("quote_collector_plus_render_style", default=DEFAULT_BUBBLE_STYLE)).strip().lower() or DEFAULT_BUBBLE_STYLE
        max_lines = _as_int(_get("quote_collector_plus_render_max_lines", default=QQBOX_DEFAULT_MAX_LINES), QQBOX_DEFAULT_MAX_LINES)
        max_chars = _as_int(_get("quote_collector_plus_render_max_chars", default=QQBOX_DEFAULT_MAX_CHARS), QQBOX_DEFAULT_MAX_CHARS)
        max_lines = max(1, min(50, max_lines))
        max_chars = max(50, min(5000, max_chars))
        use_sender_avatar = _as_bool(
            _get("quote_collector_plus_render_use_sender_avatar", default=True),
            True
        )
        default_avatar = str(
            _get("quote_collector_plus_render_default_avatar", default=DEFAULT_AVATAR_URL)
        ).strip()
        if not default_avatar:
            default_avatar = DEFAULT_AVATAR_URL

        config = {
            "style": style,
            "max_lines": max_lines,
            "max_chars": max_chars,
            "use_sender_avatar": use_sender_avatar,
            "default_avatar": default_avatar,
        }
        logger.info(f"quote_collector_plus 渲染配置：{config}")
        return config
    
    def _resolve_data_root(self, bot_config):
        config_root = (
            bot_config.get("quote_collector_plus_data_root")
            or bot_config.get("quote_collocter_plus_data_root")
        )
        env_root = (
            os.environ.get("QUOTE_COLLECTOR_PLUS_DATA_ROOT")
            or os.environ.get("QUOTE_COLLOCTER_PLUS_DATA_ROOT")
        )
        if config_root or env_root:
            raw_root = config_root or env_root
        else:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            plugins_dir = os.path.dirname(plugin_dir)
            maybe_data_dir = os.path.dirname(plugins_dir)
            if os.path.basename(plugins_dir) == "plugins" and os.path.basename(maybe_data_dir) == "data":
                raw_root = maybe_data_dir
            else:
                raw_root = "data"
        data_root = os.path.abspath(os.path.expanduser(raw_root))
        logger.info(f"quote_collector_plus 数据根目录：{data_root}（配置优先，其次环境变量，然后自动识别，最后兜底默认值）")
        return data_root

    def _ensure_dir(self, path: str, desc: str = "目录"):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            logger.error(f"创建 {desc} 失败: {path}，错误: {type(e).__name__}: {e}")
            raise

    def _check_storage_writable(self):
        try:
            self._ensure_dir(self.quotes_data_path, "语录主目录")
            probe_file = os.path.join(self.quotes_data_path, ".write_probe")
            with open(probe_file, "wb") as f:
                f.write(b"ok")
            os.remove(probe_file)
        except Exception as e:
            logger.error(
                f"语录存储目录不可写：{self.quotes_data_path}，请检查 Windows 权限或 Docker 挂载读写权限。错误：{type(e).__name__}: {e}"
            )

    def _group_folder_path(self, group_id):
        return os.path.join(self.quotes_data_path, str(group_id))

    def _admin_settings_file_path(self, group_id):
        return os.path.join(self._group_folder_path(group_id), 'admin_settings.yml')

    def _new_quote_image_path(self, group_id, prefix: str = "image", ext: str = ".jpg"):
        filename = f"{prefix}_{int(time.time() * 1000)}_{random.randint(1000, 9999)}{ext}"
        return os.path.join(self._group_folder_path(group_id), filename)

    #region 数据管理
    def create_main_folder(self):
        self._ensure_dir(self.quotes_data_path, "语录主目录")

    def create_group_folder(self, group_id):
        group_id = str(group_id)
        self.create_main_folder()
        group_folder_path = self._group_folder_path(group_id)
        self._ensure_dir(group_folder_path, "群语录目录")
        
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

    #region 气泡语录生成
    def _sanitize_quote_text(self, text: str):
        src = (text or "").strip()
        if not src:
            return "（无文本内容）"
        cleaned = []
        for ch in src:
            if ch in ("\n", "\t"):
                cleaned.append(ch)
                continue
            if unicodedata.category(ch).startswith("C"):
                continue
            cleaned.append(ch)
        normalized = "".join(cleaned).replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized).strip()
        return normalized or "（无文本内容）"

    def _apply_text_limits(self, text: str):
        max_lines = int(self.render_config.get("max_lines", QQBOX_DEFAULT_MAX_LINES))
        max_chars = int(self.render_config.get("max_chars", QQBOX_DEFAULT_MAX_CHARS))
        lines = text.split("\n")
        total = 0
        out = []
        for ln in lines:
            if len(out) >= max_lines:
                break
            remain = max_chars - total
            if remain <= 0:
                break
            if len(ln) > remain:
                if remain <= 1:
                    out.append("…")
                else:
                    out.append(ln[: remain - 1] + "…")
                total = max_chars
                break
            out.append(ln)
            total += len(ln)
        if not out:
            return ["（无文本内容）"]
        if out and len(lines) > len(out):
            if len(out[-1]) > 1:
                out[-1] = out[-1][:-1] + "…"
            else:
                out[-1] = (out[-1] or "") + "…"
        return "\n".join(out)

    def _resolve_avatar_url(self, speaker_id: str):
        sid = (speaker_id or "").strip()
        if self.render_config.get("use_sender_avatar", True) and sid:
            return f"https://q1.qlogo.cn/g?b=qq&nk={sid}&s=640"
        return self.render_config.get("default_avatar") or DEFAULT_AVATAR_URL

    def _resolve_speaker_name(self, speaker_id: str, speaker_name: str):
        name = (speaker_name or "").strip()
        if name:
            return name[:MAX_SPEAKER_NAME_LENGTH]
        sid = (str(speaker_id) if speaker_id is not None else "").strip()
        if sid:
            return sid[:MAX_SPEAKER_NAME_LENGTH]
        return "群友"

    async def _render_bubble_quote_image(
        self,
        group_id: str,
        speaker_id: str,
        speaker_name: str,
        text: str
    ):
        try:
            style = (self.render_config.get("style") or DEFAULT_BUBBLE_STYLE).strip().lower()
            if style in {"off", "none", "disable", "disabled"}:
                logger.info("文本转图渲染已关闭")
                return None
            if style != DEFAULT_BUBBLE_STYLE:
                logger.warning(f"未知渲染风格 {style}，自动回退为 {DEFAULT_BUBBLE_STYLE}")

            normalized_text = self._sanitize_quote_text(text)
            final_text = self._apply_text_limits(normalized_text)
            render_data = {
                "messages": [
                    {
                        "name": self._resolve_speaker_name(speaker_id, speaker_name),
                        "avatar": self._resolve_avatar_url(str(speaker_id or "")),
                        "text": final_text,
                    }
                ]
            }
            return await self.html_render(WHITE_BUBBLE_TEMPLATE, render_data)
        except Exception as e:
            logger.error(f"生成气泡图失败: {e}")
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
                            file_path = self._new_quote_image_path(group_id, prefix="image", ext=".jpg")
                            self._ensure_dir(os.path.dirname(file_path), "图片保存目录")
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
                            save_path = self._new_quote_image_path(group_id, prefix="image", ext=".jpg")
                            self._ensure_dir(os.path.dirname(save_path), "图片保存目录")
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
                                    file_path = self._new_quote_image_path(group_id, prefix="image", ext=".jpg")
                                    self._ensure_dir(os.path.dirname(file_path), "图片保存目录")
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
        group_folder_path = self._group_folder_path(group_id)

        if not os.path.exists(group_folder_path):
            self.create_group_folder(group_id)
        self.admin_settings_path = self._admin_settings_file_path(group_id)
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
                yield event.plain_result(f'⭐请输入"戳戳冷却+数字"来设置，单位为秒\n')
                return
            if 'coldown' in self.admin_settings:
                self.admin_settings['coldown'] = int(set_coldown)
            else:
                self.admin_settings['coldown'] = 10
            self._save_admin_settings()
            yield event.plain_result(f"⭐戳戳冷却设置成功，当前值为：{self.admin_settings['coldown']}秒")
        
        # --- 随机语录指令 ---
        elif msg == "/语录" or msg == "语录":
            group_folder_path = self._group_folder_path(group_id)
            selected_image_path = None
            if os.path.exists(group_folder_path):
                selected_image_path = self.random_image_from_folder(group_folder_path)
            
            if selected_image_path:
                yield event.image_result(selected_image_path)
            else:
                yield event.plain_result('⭐本群还没有群友语录哦~\n请发送"语录投稿/入典+图片"进行添加！')
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
            reply_text = None
            reply_user_id = None
            reply_nickname = None

            # 1. 检查当前消息中是否有图片
            messages = event.message_obj.message
            image_comp = next((m for m in messages if isinstance(m, Image)), None)

            if image_comp:
                file_id = image_comp.file
            else:
                # 2. 如果当前消息没图片，检查是否引用了消息
                reply_comp = next((m for m in messages if isinstance(m, Reply)), None)
                if reply_comp:
                    try:
                        logger.info(f"检测到引用回复，尝试获取消息ID: {reply_comp.id}")
                        reply_id = int(reply_comp.id) if str(reply_comp.id).isdigit() else reply_comp.id
                        reply_msg = await event.bot.api.call_action('get_msg', message_id=reply_id)

                        if reply_msg and 'message' in reply_msg:
                            reply_user_id = str(reply_msg.get("sender", {}).get("user_id", ""))
                            reply_nickname = (
                                reply_msg.get("sender", {}).get("card")
                                or reply_msg.get("sender", {}).get("nickname")
                                or reply_user_id
                            )
                            chain = reply_msg['message']
                            if isinstance(chain, list):
                                for part in chain:
                                    if part.get('type') == 'image':
                                        file_id = part.get('data', {}).get('file')
                                        break
                                # 引用消息无图片时提取文本
                                if not file_id:
                                    texts = [
                                        part.get('data', {}).get('text', '')
                                        for part in chain
                                        if part.get('type') == 'text'
                                    ]
                                    reply_text = "".join(texts).strip()
                            elif isinstance(chain, str):
                                match = re.search(r'\[CQ:image,[^\]]*file=([^,\]]+)', chain)
                                if match:
                                    file_id = match.group(1)
                                else:
                                    reply_text = re.sub(r'\[CQ:[^\]]+\]', '', chain).strip()

                    except Exception as e:
                        logger.error(f"获取引用消息失败: {e}")

            # 3. 若无图片但有引用文本，自动生成气泡语录图
            if not file_id and reply_text:
                try:
                    self.create_group_folder(group_id)
                    bubble_path = await self._render_bubble_quote_image(
                        group_id=group_id,
                        speaker_id=reply_user_id or user_id,
                        speaker_name=reply_nickname or "群友",
                        text=reply_text
                    )
                    msg_id = str(event.message_obj.message_id)
                    bubble_path_text = bubble_path if isinstance(bubble_path, str) else (str(bubble_path) if bubble_path is not None else "")
                    bubble_ok = bool(bubble_path_text) and (
                        bubble_path_text.startswith(RENDER_OUTPUT_SCHEMES)
                        or os.path.exists(bubble_path_text)
                    )
                    if bubble_ok:
                        yield event.chain_result([Reply(id=msg_id), Plain(text="⭐入典成功（已生成气泡语录图）！")])
                    else:
                        if (self.render_config.get("style") or "").strip().lower() in {"off", "none", "disable", "disabled"}:
                            yield event.plain_result("⭐投稿失败：当前已关闭“引用文本转图”渲染，可在配置中开启渲染风格。")
                        else:
                            yield event.plain_result("⭐投稿失败：生成气泡语录图失败(请检查 html_render 是否可用、模板渲染配置是否完整)")
                except Exception as e:
                    logger.error(f"生成气泡语录图过程出错: {e}")
                    yield event.plain_result(f"⭐投稿失败: {str(e)}")
                return

            if not file_id:
                chain = [
                    At(qq=user_id),
                    Plain(text='\n你是不是忘发图啦？\n请直接"语录投稿/入典+图片"或者"引用图片并发送语录投稿/入典"，也可以引用文本消息自动生成气泡语录')
                ]
                yield event.chain_result(chain)
                return

            try:
                self.create_group_folder(group_id)
                # 下载并保存图片
                try:
                    file_path = await self.download_image(event, file_id, group_id)
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
                self.admin_settings_path = self._admin_settings_file_path(group_id)
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
                            group_folder_path = self._group_folder_path(group_id)
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
