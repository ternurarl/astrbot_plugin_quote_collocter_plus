import os
import random
import time
import json
import yaml
import aiohttp
import re
import uuid
from urllib.parse import urlparse
from astrbot import logger
from astrbot.core.message.components import Image, Reply, At, Plain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.all import *

@register("quote_collocter_plus", "ternurarl", '发送"语录投稿+图片"或回复图片发送"语录投稿"来存储群友的黑历史！发送"/语录"随机查看一条。bot会在被戳一戳时随机发送一张语录', "1.0")
class Quote_Plugin(Star):
    TMPL = '''
<div style="display:flex;align-items:flex-start;gap:10px;padding:12px;background:#f5f5f5;">
  <img src="{{ avatar }}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;" />
  <div style="max-width:560px;">
    <div style="font-size:14px;color:#8c8c8c;line-height:1.4;margin-bottom:6px;">{{ name }}</div>
    <div style="background:#ffffff;border-radius:0 16px 16px 16px;padding:10px 14px;color:#111111;font-size:16px;line-height:1.6;white-space:pre-wrap;word-break:break-word;box-shadow:0 1px 2px rgba(0,0,0,0.06);">
      {{ text }}
    </div>
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

    async def _render_bubble_image(self, group_id, avatar, name, text):
        render_data = {
            "avatar": avatar,
            "name": name,
            "text": text
        }
        image_url = await self.html_render(self.TMPL, render_data)
        if not image_url:
            return None

        filename = f"image_{int(time.time() * 1000)}_{uuid.uuid4().hex}.jpg"
        save_path = os.path.join("data", "quotes_data", group_id, filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        try:
            if os.path.exists(image_url):
                with open(image_url, "rb") as src, open(save_path, "wb") as dst:
                    dst.write(src.read())
                return save_path

            parsed = urlparse(image_url)
            if parsed.scheme == "file":
                local_path = parsed.path
                if os.path.exists(local_path):
                    with open(local_path, "rb") as src, open(save_path, "wb") as dst:
                        dst.write(src.read())
                    return save_path

            if image_url.startswith("http://") or image_url.startswith("https://"):
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as response:
                        if response.status == 200:
                            data = await response.read()
                            with open(save_path, "wb") as f:
                                f.write(data)
                            return save_path
                        logger.error(f"下载渲染图片失败: HTTP {response.status}, image_url={image_url}, save_path={save_path}")

        except Exception as e:
            logger.error(f"保存渲染图片失败: {e}, image_url={image_url}, save_path={save_path}")
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

        elif msg.startswith("语录投稿"):
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
                                    sender_name = sender.get("card") or sender.get("nickname") or (str(sender_id) if sender_id is not None else "未知用户")
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
                    Plain(text='\n你是不是忘发图啦？\n请直接"语录投稿+图片"或者"引用图片并发送语录投稿/引用文本并发送语录投稿"')
                ]
                yield event.chain_result(chain)
                return
                            
            try:
                self.create_group_folder(group_id)
                # 下载并保存图片
                try:
                    file_path = rendered_path or await self.download_image(event, file_id, group_id)
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
