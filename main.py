import asyncio
import logging
import os
import signal
import sys


class _BelowErrorFilter(logging.Filter):
    """Keep Railway stream severity aligned with the Python log level."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.INFO)
_stdout_handler.addFilter(_BelowErrorFilter())

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[_stdout_handler, _stderr_handler],
)

import discord  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from discord.ext import commands  # noqa: E402

# Config modules read env vars at import time, so local .env must be loaded
# before importing config/storage.
load_dotenv()

from ai_client import ai_provider_runtime_summary  # noqa: E402
from config import BOT_COMMAND_PREFIX  # noqa: E402
from storage import close_all_connections, init_db  # noqa: E402
from utils import sanitize_discord_token  # noqa: E402

logger = logging.getLogger(__name__)

# Cogs to load in order. Each must expose an async setup(bot) function.
COGS = [
    "cogs.general",
    "cogs.forms",
    "cogs.security",
    "cogs.logging_events",
    "cogs.mod",
    "cogs.telegram_bridge",
    "cogs.ai_chat",
]


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    intents.presences = False
    intents.typing = False
    bot = commands.Bot(
        command_prefix=BOT_COMMAND_PREFIX,
        intents=intents,
        case_insensitive=True,
        help_command=None,
    )
    return bot


async def run_bot() -> None:
    raw_token = os.getenv("DISCORD_TOKEN")
    token = sanitize_discord_token(raw_token)
    if not token:
        raise RuntimeError("DISCORD_TOKEN не найден в переменных окружения Railway")

    bot = create_bot()
    loop = asyncio.get_running_loop()
    shutdown_task: asyncio.Task | None = None
    shutdown_lock = asyncio.Lock()
    shutdown_complete = False
    db_initialized = False
    persistent_state_trusted = False

    async def _shutdown(*, persist: bool) -> None:
        """Stop exactly once and never upload an untrusted startup database."""
        nonlocal shutdown_complete
        async with shutdown_lock:
            if shutdown_complete:
                return
            logger.info("Получен запрос завершения работы P.OS.")

            if persist and persistent_state_trusted and db_initialized:
                try:
                    from pos_ai import flush_ai_memory

                    await flush_ai_memory()
                except Exception:
                    logger.exception("Не удалось сбросить память P.OS перед остановкой.")
                try:
                    from storage import backup_db_to_discord

                    await backup_db_to_discord(bot)
                except Exception:
                    logger.exception("Не удалось сохранить резервную копию перед остановкой.")

            if not bot.is_closed():
                try:
                    await bot.close()
                except Exception:
                    logger.exception("Ошибка закрытия Discord-клиента.")
            if db_initialized:
                try:
                    await close_all_connections()
                except Exception:
                    logger.exception("Ошибка закрытия соединений с БД.")
            shutdown_complete = True

    def _on_signal() -> None:
        nonlocal shutdown_task
        if shutdown_task is None or shutdown_task.done():
            shutdown_task = asyncio.create_task(
                _shutdown(persist=persistent_state_trusted),
                name="pos-graceful-shutdown",
            )

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows не поддерживает add_signal_handler — молча игнорируем
            pass

    try:
        await init_db()
        db_initialized = True

        # Загружаем все коги до старта бота. Любая ошибка является фатальной:
        # частично загруженный P.OS не должен подключаться к серверам.
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                logger.info("Cog loaded: %s", cog)
            except Exception as exc:
                logger.exception("Failed to load required cog %s.", cog)
                raise RuntimeError(f"Required cog failed to load: {cog}") from exc

        logger.info(
            "Запуск P.OS: AI routes=%s",
            ai_provider_runtime_summary(),
        )
        # Login authenticates the HTTP client without opening the gateway. This
        # lets us restore persistent state before Discord starts dispatching
        # messages, joins, moderation and AI events to cogs.
        await bot.login(token)

        from storage import restore_db_from_discord

        restore_result: bool | None = None
        for attempt, delay in enumerate((0.0, 2.0, 5.0), start=1):
            if delay:
                await asyncio.sleep(delay)
            restore_result = await restore_db_from_discord(bot)
            if restore_result is not None:
                break
            logger.warning("Database restore attempt %s/3 failed safely.", attempt)

        if restore_result is None:
            raise RuntimeError(
                "Не удалось безопасно проверить/восстановить БД после трёх попыток; "
                "gateway не запущен, чтобы не работать поверх неверного состояния"
            )
        persistent_state_trusted = True
        if restore_result:
            from guild_config import invalidate
            from pos_ai import reset_ai_runtime_caches_after_restore

            invalidate()
            reset_ai_runtime_caches_after_restore()
            logger.info("Database restored and runtime caches invalidated before gateway start.")

        import antiraid
        from storage import get_active_raid_states

        restored_raid_modes = antiraid.restore_raid_modes(await get_active_raid_states())
        if restored_raid_modes:
            logger.warning(
                "Restored %s active anti-raid mode(s) before gateway start.",
                restored_raid_modes,
            )

        if not bot.is_closed():
            await bot.connect(reconnect=True)
    except discord.errors.LoginFailure:
        logger.critical("Неверный DISCORD_TOKEN.")
        raise
    except asyncio.CancelledError:
        logger.info("P.OS остановлен корректно.")
        raise
    except Exception as e:
        logger.critical("Критическая ошибка при запуске: %s", e, exc_info=True)
        raise
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError):
                pass

        if shutdown_task is not None:
            try:
                await shutdown_task
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка задачи graceful shutdown.")
        await _shutdown(
            persist=persistent_state_trusted and not bot.is_closed(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
