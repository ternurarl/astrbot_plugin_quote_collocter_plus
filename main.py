import sys
from pathlib import Path

from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.api.all import *

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
    "1.5.0",
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

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        async for result in self.commands.handle_group_message(event):
            yield result
