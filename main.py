import sys
from pathlib import Path

from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.api.all import *
from astrbot.api.event import filter

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from quote_collocter_plus.album import AlbumService
from quote_collocter_plus.commands import CommandHandler
from quote_collocter_plus.config import load_plugin_settings
from quote_collocter_plus.forward_parser import ForwardParser
from quote_collocter_plus.images import ImageService
from quote_collocter_plus.message_parser import MessageParser
from quote_collocter_plus.onebot import OneBotClient
from quote_collocter_plus.renderer import QuoteRenderer
from quote_collocter_plus.storage import QuoteStorage


@register(
    "astrbot_plugin_quote_collocter_plus",
    "ternurarl",
    "发送\"语录投稿+图片\"或\"入典+图片\"，也可回复图片发送\"语录投稿\"或\"入典\"来存储黑历史！发送\"/语录\"随机查看一条。bot会在被戳一戳时随机发送一张语录",
    "1.5.3",
)
class Quote_Plugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        try:
            global_config = context.get_config()
        except Exception:
            global_config = {}

        self.settings = load_plugin_settings(self.config, global_config)
        self.storage = QuoteStorage(self.settings, logger)
        self.parser = MessageParser()
        self.onebot = OneBotClient(logger)
        self.images = ImageService(self.storage, self.parser, self.onebot, logger)
        self.forward_parser = ForwardParser(
            self.parser,
            self.onebot,
            self.images.resolve_forward_image_src,
            logger,
        )
        self.renderer = QuoteRenderer(
            self.settings,
            self.storage,
            self.parser,
            self.html_render,
            logger,
        )
        self.album = AlbumService(self.settings, self.storage, self.onebot, logger)
        self.commands = CommandHandler(
            self.settings,
            self.storage,
            self.parser,
            self.forward_parser,
            self.renderer,
            self.album,
            self.images,
            logger,
        )

        if self.settings.admins:
            logger.info(f"获取到插件管理员ID列表: {self.settings.admins}")
        else:
            logger.warning("未找到任何管理员ID，某些需要管理员权限的命令可能无法使用")

    def _registered_command_text(self, event: AstrMessageEvent, command_name: str, args: str = "") -> str:
        message_text = (event.message_str or "").strip()
        try:
            raw_prefixes = self.context.get_config().get("wake_prefix", ["/"])
            prefixes = [raw_prefixes] if isinstance(raw_prefixes, str) else list(raw_prefixes)
        except Exception:
            prefixes = ["/"]

        for prefix in prefixes:
            if prefix and message_text.startswith(prefix):
                message_text = message_text[len(prefix) :].strip()
                break

        if message_text.startswith(command_name):
            return message_text
        return f"{command_name} {args}".strip()

    async def _handle_registered_command(
        self,
        event: AstrMessageEvent,
        command_name: str,
        args: str = "",
    ):
        msg = self._registered_command_text(event, command_name, args)
        async for result in self.commands.handle_registered_command(event, command_name, msg):
            yield result
        event.stop_event()

    @filter.command("入典", priority=1)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def submit_quote(self, event: AstrMessageEvent):
        """投稿图片、引用文字或合并聊天记录到本群语录库"""
        async for result in self._handle_registered_command(event, "入典"):
            yield result

    @filter.command("语录投稿", priority=1)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def submit_quote_alias(self, event: AstrMessageEvent):
        """投稿图片、引用文字或合并聊天记录到本群语录库"""
        async for result in self._handle_registered_command(event, "语录投稿"):
            yield result

    @filter.command("语录", priority=1)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def random_quote(self, event: AstrMessageEvent):
        """随机查看本群一条历史语录"""
        async for result in self._handle_registered_command(event, "语录"):
            yield result

    @filter.command("投稿权限", priority=1)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def permission_mode(self, event: AstrMessageEvent, args: str = ""):
        """设置投稿权限：0 关闭，1 仅管理员，2 全体成员"""
        async for result in self._handle_registered_command(event, "投稿权限", args):
            yield result

    @filter.command("语录相册", priority=1)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def quote_album(self, event: AstrMessageEvent, args: str = ""):
        """管理 NapCat 群相册上传：状态、列表、开启、关闭、名称、ID、重置"""
        async for result in self._handle_registered_command(event, "语录相册", args):
            yield result

    @filter.command("戳戳冷却", priority=1)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def poke_cooldown(self, event: AstrMessageEvent, args: str = ""):
        """设置 Bot 被戳一戳后触发语录回复的冷却秒数"""
        async for result in self._handle_registered_command(event, "戳戳冷却", args):
            yield result

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        async for result in self.commands.handle_group_message(event):
            yield result
