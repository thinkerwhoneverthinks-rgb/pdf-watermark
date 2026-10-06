"""Entry point: runs the aiogram bot and the aiohttp health server together."""

import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats

import config
from handlers import fsm_entry, sync_callbacks, vision_entry
from storage import TelegramStorage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dtt-bot")


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="Daily Target Tracker bot is running OK")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def run_web_server() -> None:
    """Lightweight health-check server required by Render's free web service."""
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("Health-check server listening on port %s", config.PORT)
    await asyncio.Event().wait()  # serve forever


async def setup_bot_commands(bot: Bot) -> None:
    """Register slash commands for autocomplete menu in Telegram UI."""
    private_commands = [
        BotCommand(command="start", description="🚀 Open main menu & WebApp"),
        BotCommand(command="target", description="⚡ Quick targets (e.g. /target phy L2 Q50)"),
        BotCommand(command="q", description="⚡ Short alias for /target"),
        BotCommand(command="summary", description="📊 View recent study progress & streak"),
        BotCommand(command="export", description="📄 Download interactive HTML study dashboard"),
        BotCommand(command="set", description="ℹ️ View or configure your linked group topic"),
        BotCommand(command="delete", description="🗑️ Delete targets for today or a date"),
        BotCommand(command="help", description="📖 Interactive help menu"),
    ]
    group_commands = [
        BotCommand(command="set", description="🔗 Link this topic for your daily targets"),
        BotCommand(command="summary", description="📊 View study progress (reply to a friend)"),
        BotCommand(command="help", description="📖 Interactive help menu"),
    ]
    try:
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
        log.info("Bot commands autocomplete menu registered successfully")
    except Exception as exc:
        log.warning("Could not set bot commands menu: %s", exc)


async def main() -> None:
    bot = Bot(token=config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)

    storage = TelegramStorage(bot)
    await storage.init()
    log.info("Multi-user Telegram-as-a-database storage ready")

    await setup_bot_commands(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp["storage"] = storage  # injected into every handler as a kwarg
    dp.include_routers(sync_callbacks.router, fsm_entry.router, vision_entry.router)

    await asyncio.gather(
        dp.start_polling(bot),
        run_web_server(),
    )


if __name__ == "__main__":
    asyncio.run(main())
