import discord
from discord.ext import commands
import logging

from pos_ai import handle_pos_ai
from message_gate import wait_for_moderation
from vacation_mode import handle_owner_vacation_ping

logger = logging.getLogger(__name__)

class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        try:
            moderation_result = await wait_for_moderation(message.id)
            if moderation_result is not False:
                if moderation_result is None:
                    logger.error("Moderation gate timed out for message %s; AI reply suppressed.", message.id)
                return
            if await handle_owner_vacation_ping(message):
                return
            if await handle_pos_ai(message, self.bot):
                return
        except Exception as e:
            logger.error(f"Error in handle_pos_ai: {e}", exc_info=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
