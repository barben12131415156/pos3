import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from cogs.ai_tools import POS_AI_TOOLS
from discord_capabilities import (
    EXTENDED_CAPABILITY_NAMES,
    execute_extended_capability,
)


class ExtendedDiscordToolContractTests(unittest.IsolatedAsyncioTestCase):
    def test_every_extended_executor_is_declared_to_the_model(self):
        declared = {tool["function"]["name"] for tool in POS_AI_TOOLS}
        self.assertLessEqual(EXTENDED_CAPABILITY_NAMES, declared)
        self.assertEqual(len(EXTENDED_CAPABILITY_NAMES), 16)

    def test_every_declared_tool_has_a_concrete_dispatch_path(self):
        source = Path(__file__).parents[1].joinpath("pos_ai.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        performer = next(
            node
            for node in module.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_perform_tool_action"
        )
        handled = set(EXTENDED_CAPABILITY_NAMES)
        for node in ast.walk(performer):
            if not isinstance(node, ast.Compare):
                continue
            if not isinstance(node.left, ast.Name) or node.left.id != "name":
                continue
            for operator, comparator in zip(node.ops, node.comparators):
                if isinstance(operator, ast.Eq) and isinstance(comparator, ast.Constant):
                    if isinstance(comparator.value, str):
                        handled.add(comparator.value)
                elif isinstance(operator, ast.In) and isinstance(comparator, (ast.Set, ast.Tuple, ast.List)):
                    handled.update(
                        item.value
                        for item in comparator.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    )

        declared = {tool["function"]["name"] for tool in POS_AI_TOOLS}
        self.assertEqual(declared - handled, set())

    async def test_manage_message_edits_the_real_pos_message(self):
        message_id = 123456789012345678
        channel_id = 223456789012345678
        bot_id = 323456789012345678
        target = Mock(spec=discord.Message)
        target.id = message_id
        target.author = SimpleNamespace(id=bot_id)
        target.edit = AsyncMock()

        channel = Mock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock(return_value=target)
        guild = SimpleNamespace(
            me=SimpleNamespace(id=bot_id),
            get_channel_or_thread=Mock(return_value=channel),
            channels=[channel],
            threads=[],
            emojis=[],
            stickers=[],
        )
        result = await execute_extended_capability(
            guild,
            SimpleNamespace(attachments=[]),
            "manage_message",
            {
                "action": "edit",
                "channel_id_or_name": str(channel_id),
                "message_id": str(message_id),
                "text": "Исправленный ответ",
            },
        )

        target.edit.assert_awaited_once()
        self.assertIn("выполнено", result)

    async def test_forum_post_uses_forum_create_thread_api(self):
        channel_id = 423456789012345678
        thread_id = 523456789012345678
        forum = Mock(spec=discord.ForumChannel)
        forum.id = channel_id
        forum.create_thread = AsyncMock(
            return_value=SimpleNamespace(
                thread=SimpleNamespace(id=thread_id, name="release-notes")
            )
        )
        guild = SimpleNamespace(
            get_channel_or_thread=Mock(return_value=forum),
            channels=[forum],
            threads=[],
            emojis=[],
            stickers=[],
        )
        result = await execute_extended_capability(
            guild,
            SimpleNamespace(attachments=[]),
            "create_forum_post",
            {
                "channel_id_or_name": str(channel_id),
                "name": "release-notes",
                "text": "Обновление готово.",
            },
        )

        forum.create_thread.assert_awaited_once()
        self.assertIn(str(thread_id), result)


if __name__ == "__main__":
    unittest.main()
