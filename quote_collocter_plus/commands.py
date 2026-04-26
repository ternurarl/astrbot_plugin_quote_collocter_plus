from __future__ import annotations

import os
import random
import re
import time
from typing import Any, AsyncIterator

from .album import AlbumService
from .forward_parser import ForwardParser
from .images import ImageService
from .message_parser import MessageParser
from .models import GroupContext, PluginSettings
from .renderer import QuoteRenderer
from .storage import QuoteStorage

try:
    from astrbot.core.message.components import At, Image, Plain, Reply
except Exception:  # pragma: no cover - only used outside an AstrBot runtime.
    At = Image = Plain = Reply = None


def _is_component(value: Any, component_type: Any) -> bool:
    return component_type is not None and isinstance(value, component_type)


class CommandHandler:
    def __init__(
        self,
        settings: PluginSettings,
        storage: QuoteStorage,
        parser: MessageParser,
        forward_parser: ForwardParser,
        renderer: QuoteRenderer,
        album: AlbumService,
        images: ImageService,
        logger: Any = None,
    ):
        self.settings = settings
        self.storage = storage
        self.parser = parser
        self.forward_parser = forward_parser
        self.renderer = renderer
        self.album = album
        self.images = images
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

    def is_admin(self, user_id: Any) -> bool:
        return str(user_id) in self.settings.admins

    def gain_mode(self, msg: str) -> str | None:
        if msg:
            match = re.search(r"[-+]?\d*\.?\d+", msg)
            if match:
                return match.group()
        return None

    async def handle_group_message(self, event: Any) -> AsyncIterator[Any]:
        group_id = str(event.message_obj.group_id)
        user_id = str(event.get_sender_id())
        message_obj = event.message_obj
        raw_message = message_obj.raw_message
        msg = event.message_str.strip()
        group_context = self.storage.load_group_context(group_id)

        if msg.startswith("投稿权限"):
            async for result in self._handle_permission_command(event, group_context, user_id, msg):
                yield result
            return

        if msg.startswith("语录相册"):
            async for result in self._handle_album_command(event, group_context, user_id, msg):
                yield result
            return

        if msg.startswith("戳戳冷却"):
            async for result in self._handle_cooldown_command(event, group_context, user_id, msg):
                yield result
            return

        if msg == "/语录" or msg == "语录":
            async for result in self._handle_random_quote(event, group_context):
                yield result
            return

        if msg.startswith("语录投稿") or msg.startswith("入典"):
            async for result in self._handle_submission(event, group_context, user_id):
                yield result
            return

        async for result in self._handle_poke(event, group_context, raw_message):
            yield result

    async def _handle_permission_command(
        self,
        event: Any,
        group_context: GroupContext,
        user_id: str,
        msg: str,
    ) -> AsyncIterator[Any]:
        if not self.is_admin(user_id):
            yield event.plain_result("权限不足，仅可由bot管理员设置")
            return
        set_mode = self.gain_mode(msg)
        if not set_mode:
            yield event.plain_result(
                f'⭐请输入"投稿权限+数字"来设置\n'
                f"  0：关闭投稿系统\n"
                f"  1：仅管理员可投稿\n"
                f"  2：全体成员均可投稿\n"
                f"当前群聊权限设置为："
                f"{group_context.admin_settings.get('mode', self.settings.default_permission_mode)}"
            )
            return
        if set_mode not in ["0", "1", "2"]:
            yield event.plain_result(
                "⭐模式数字范围出错！请输入正确的模式\n"
                "  0：关闭投稿系统\n"
                "  1：仅管理员可投稿\n"
                "  2：全体成员均可投稿"
            )
            return
        group_context.admin_settings["mode"] = int(set_mode)
        self.storage.save_group_context(group_context)
        texts = "⭐投稿权限设置成功，当前状态为："
        if group_context.admin_settings["mode"] == 0:
            texts += "\n  0：关闭投稿系统"
        elif group_context.admin_settings["mode"] == 1:
            texts += "\n  1：仅管理员可投稿"
        elif group_context.admin_settings["mode"] == 2:
            texts += "\n  2：全体成员均可投稿"
        yield event.plain_result(texts)

    async def _handle_album_command(
        self,
        event: Any,
        group_context: GroupContext,
        user_id: str,
        msg: str,
    ) -> AsyncIterator[Any]:
        if not self.is_admin(user_id):
            yield event.plain_result("权限不足，仅可由bot管理员设置")
            return
        result = await self.album.handle_command(event, group_context, msg)
        yield event.plain_result(result)

    async def _handle_cooldown_command(
        self,
        event: Any,
        group_context: GroupContext,
        user_id: str,
        msg: str,
    ) -> AsyncIterator[Any]:
        if not self.is_admin(user_id):
            yield event.plain_result("权限不足，仅可由bot管理员设置")
            return
        set_coldown = self.gain_mode(msg)
        if not set_coldown:
            yield event.plain_result('⭐请输入"戳戳冷却+数字"来设置，单位为秒\n')
            return
        group_context.admin_settings["coldown"] = max(0, int(float(set_coldown)))
        self.storage.save_group_context(group_context)
        yield event.plain_result(f"⭐戳戳冷却设置成功，当前值为：{group_context.admin_settings['coldown']}秒")

    async def _handle_random_quote(
        self,
        event: Any,
        group_context: GroupContext,
    ) -> AsyncIterator[Any]:
        selected_image_path = None
        if os.path.exists(group_context.group_folder_path):
            selected_image_path = self.storage.random_image_from_folder(group_context.group_folder_path)

        if selected_image_path:
            yield event.image_result(selected_image_path)
        else:
            yield event.plain_result('⭐本群还没有群友语录哦~\n请发送"语录投稿+图片"进行添加！')

    async def _handle_submission(
        self,
        event: Any,
        group_context: GroupContext,
        user_id: str,
    ) -> AsyncIterator[Any]:
        current_mode = group_context.admin_settings.get(
            "mode",
            self.settings.default_permission_mode,
        )
        if current_mode == 0:
            yield event.plain_result('⭐投稿系统未开启，请联系bot管理员发送"投稿权限"来设置')
            return
        if current_mode == 1 and not self.is_admin(user_id):
            yield event.plain_result(
                '⭐权限不足，当前权限设置为"仅bot管理员可投稿"\n'
                '可由bot管理员发送"投稿权限"来设置'
            )
            return

        file_id = None
        rendered_path = None

        messages = event.message_obj.message
        image_comp = next((item for item in messages if _is_component(item, Image)), None)

        if image_comp:
            file_id = image_comp.file
        else:
            reply_comp = next((item for item in messages if _is_component(item, Reply)), None)
            if reply_comp:
                try:
                    self._info(f"检测到引用回复，尝试获取消息ID: {reply_comp.id}")
                    reply_id = int(reply_comp.id) if str(reply_comp.id).isdigit() else reply_comp.id
                    reply_msg = None
                    try:
                        reply_msg = await self.forward_parser.onebot.get_msg(event, message_id=reply_id)
                    except Exception as e:
                        self._debug(f"通过 get_msg 获取引用消息失败，将尝试使用 Reply.chain: {e}")

                    chain = self.parser.message_chain_from_payload(reply_msg)
                    reply_chain = getattr(reply_comp, "chain", None)
                    if chain is None:
                        chain = reply_chain

                    file_id = self.parser.extract_first_image_file_id(chain)

                    if not file_id and self.settings.allow_text_quote_render:
                        forward_nodes = await self.forward_parser.extract_forward_render_nodes(
                            event,
                            chain,
                            group_context.group_id,
                        )
                        if not forward_nodes and chain is not reply_chain:
                            forward_nodes = await self.forward_parser.extract_forward_render_nodes(
                                event,
                                reply_chain,
                                group_context.group_id,
                            )

                        if forward_nodes:
                            rendered_path = await self.renderer.render_forward_image(
                                group_context.group_id,
                                forward_nodes,
                            )

                        if not rendered_path:
                            reply_text = self.parser.extract_reply_text(chain)
                            if not reply_text:
                                reply_text = str(getattr(reply_comp, "message_str", "") or "").strip()
                            if reply_text:
                                _, sender_name, sender_avatar = self.parser.reply_sender_meta(
                                    event,
                                    reply_msg,
                                    reply_comp,
                                )
                                rendered_path = await self.renderer.render_bubble_image(
                                    group_id=group_context.group_id,
                                    avatar=sender_avatar,
                                    name=sender_name,
                                    text=reply_text,
                                )

                except Exception as e:
                    self._error(f"获取引用消息失败: {e}")

        if not file_id and not rendered_path:
            chain = [
                At(qq=user_id),
                Plain(text="\n你是不是忘发图啦？\n请直接发送\"语录投稿+图片\"或\"入典+图片\"\n或者引用图片并发送\"语录投稿\"/\"入典\""),
            ]
            yield event.chain_result(chain)
            return

        try:
            self.storage.create_group_folder(group_context.group_id)
            try:
                if rendered_path:
                    file_path = rendered_path
                elif file_id:
                    file_path = await self.images.download_image(
                        event,
                        file_id,
                        group_context.group_id,
                    )
                else:
                    file_path = None
                msg_id = str(event.message_obj.message_id)

                if file_path and os.path.exists(file_path):
                    result_text = "⭐语录投稿成功！"
                    result_text += await self.album.result_suffix(event, group_context, file_path)
                    chain = [
                        Reply(id=msg_id),
                        Plain(text=result_text),
                    ]
                else:
                    chain = [
                        Reply(id=msg_id),
                        Plain(text="⭐语录投稿失败，图片下载失败"),
                    ]
                yield event.chain_result(chain)
            except Exception as e:
                self._error(f"投稿过程出错: {e}")
                yield event.plain_result(f"⭐投稿失败: {str(e)}")

        except Exception as e:
            yield event.make_result().message(f"\n错误信息：{str(e)}")

    async def _handle_poke(
        self,
        event: Any,
        group_context: GroupContext,
        raw_message: Any,
    ) -> AsyncIterator[Any]:
        if not self.settings.enable_poke_reply or not isinstance(raw_message, dict):
            return
        if not (
            raw_message.get("post_type") == "notice"
            and raw_message.get("notice_type") == "notify"
            and raw_message.get("sub_type") == "poke"
        ):
            return

        bot_id = raw_message.get("self_id")
        sender_id = raw_message.get("user_id")
        target_id = raw_message.get("target_id")
        if not (bot_id and sender_id and target_id):
            return

        cold_time = group_context.admin_settings.setdefault(
            "coldown",
            self.settings.default_poke_cooldown,
        )
        last_poke = group_context.admin_settings.setdefault("last_poke", 0)
        self.storage.save_group_context(group_context)

        if time.time() - last_poke > cold_time:
            group_context.admin_settings["last_poke"] = time.time()
            self.storage.save_group_context(group_context)
            if str(target_id) == str(bot_id):
                if random.random() < self.settings.poke_quote_probability:
                    selected_image_path = None
                    if os.path.exists(group_context.group_folder_path):
                        selected_image_path = self.storage.random_image_from_folder(
                            group_context.group_folder_path,
                        )

                    if not selected_image_path:
                        return

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
                        Plain(text=selected_text),
                    ]
                    yield event.chain_result(chain)
        else:
            remaining = cold_time - (time.time() - last_poke)
            self._info(f"爆典功能冷却中，剩余{remaining:.0f}秒")
