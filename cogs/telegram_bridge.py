"""Lifecycle integration for the private P.OS Telegram owner bridge."""
from __future__ import annotations

from discord.ext import commands

from telegram_bridge import TelegramOwnerBridge


class TelegramBridgeCog(commands.Cog, name="TelegramBridge"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bridge = TelegramOwnerBridge(bot)

    async def cog_load(self) -> None:
        await self.bridge.start()

    async def cog_unload(self) -> None:
        await self.bridge.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TelegramBridgeCog(bot))
