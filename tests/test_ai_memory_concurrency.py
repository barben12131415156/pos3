import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pos_ai


class AIMemoryConcurrencyTests(IsolatedAsyncioTestCase):
    def setUp(self):
        pos_ai.reset_ai_runtime_caches_after_restore()

    async def test_concurrent_cold_guild_load_uses_one_shared_list(self):
        async def delayed_load(_user_id, _guild_id):
            await asyncio.sleep(0.01)
            return "[]"

        loader = AsyncMock(side_effect=delayed_load)
        with patch.object(pos_ai, "get_ai_context", loader):
            first, second = await asyncio.gather(
                pos_ai._load_guild_memory(123),
                pos_ai._load_guild_memory(123),
            )

        self.assertIs(first, second)
        loader.assert_awaited_once_with(0, 123)

    async def test_concurrent_cold_user_load_uses_one_shared_list(self):
        async def delayed_load(_user_id, _guild_id):
            await asyncio.sleep(0.01)
            return "[]"

        loader = AsyncMock(side_effect=delayed_load)
        with patch.object(pos_ai, "get_ai_context", loader):
            first, second = await asyncio.gather(
                pos_ai._load_user_ctx(77, 123),
                pos_ai._load_user_ctx(77, 123),
            )

        self.assertIs(first, second)
        loader.assert_awaited_once_with(77, 123)

    def _message(self, message_id=1001, content="P.OS, запомни этот контекст"):
        guild = SimpleNamespace(id=123, get_member=lambda _value: None, get_role=lambda _value: None, get_channel=lambda _value: None)
        channel = SimpleNamespace(id=456, name="general")
        author = SimpleNamespace(
            id=77,
            name="tester",
            display_name="Tester",
            bot=False,
        )
        return SimpleNamespace(
            id=message_id,
            content=content,
            guild=guild,
            channel=channel,
            author=author,
            attachments=[],
            mentions=[],
            role_mentions=[],
            channel_mentions=[],
            reference=None,
        )

    async def test_direct_pos_address_is_saved_and_edit_replaces_it(self):
        guild_memory = []
        user_memory = []
        original = self._message()
        edited = self._message(content="P.OS, исправленный контекст")

        with (
            patch.object(pos_ai, "is_log_channel", return_value=False),
            patch.object(
                pos_ai,
                "_load_guild_memory",
                new=AsyncMock(return_value=guild_memory),
            ),
            patch.object(
                pos_ai,
                "_load_user_ctx",
                new=AsyncMock(return_value=user_memory),
            ),
            patch.object(pos_ai, "flush_ai_memory", new=AsyncMock()),
        ):
            await pos_ai.remember_server_message(original)
            await pos_ai.remember_server_message(edited)

        self.assertEqual(len(guild_memory), 1)
        self.assertEqual(guild_memory[0]["message_id"], original.id)
        self.assertIn("исправленный", guild_memory[0]["content"])
        self.assertEqual(len(user_memory), 1)
        self.assertIn("исправленный", user_memory[0]["content"])

    async def test_author_profile_reads_persisted_context_after_restart(self):
        message = self._message(message_id=2002, content="Новый вопрос")
        persisted = [
            {
                "ts": 10,
                "message_id": 1001,
                "channel_id": 456,
                "content": "Старый факт из SQLite",
            }
        ]

        with patch.object(
            pos_ai,
            "_load_user_ctx",
            new=AsyncMock(return_value=persisted),
        ):
            profile = await pos_ai._format_author_profile(message)

        self.assertIn("Старый факт из SQLite", profile)
        self.assertIn("долговременной памяти", profile)

    async def test_author_profile_does_not_leak_text_from_another_channel(self):
        message = self._message(message_id=2002, content="Новый вопрос")
        persisted = [
            {
                "ts": 10,
                "message_id": 1001,
                "channel_id": 999,
                "content": "Секрет из закрытого другого канала",
            },
            {
                "ts": 11,
                "message_id": 1002,
                "channel_id": 456,
                "content": "Контекст текущего канала",
            },
        ]

        with patch.object(
            pos_ai,
            "_load_user_ctx",
            new=AsyncMock(return_value=persisted),
        ):
            profile = await pos_ai._format_author_profile(message)

        self.assertIn("Контекст текущего канала", profile)
        self.assertNotIn("Секрет из закрытого", profile)

    async def test_deleted_message_is_removed_from_guild_and_user_memory(self):
        guild_memory = [
            {
                "ts": 10,
                "message_id": 1001,
                "channel_id": 456,
                "author_id": 77,
                "content": "Удалённая реплика",
            }
        ]
        user_memory = [
            {
                "ts": 10,
                "message_id": 1001,
                "channel_id": 456,
                "content": "Удалённая реплика",
            }
        ]

        async def load_user(user_id, guild_id):
            self.assertEqual((user_id, guild_id), (77, 123))
            return user_memory

        with (
            patch.object(
                pos_ai,
                "_load_guild_memory",
                new=AsyncMock(return_value=guild_memory),
            ),
            patch.object(pos_ai, "_load_user_ctx", side_effect=load_user),
        ):
            removed = await pos_ai.forget_server_messages(123, {1001})

        self.assertEqual(removed, 1)
        self.assertEqual(guild_memory, [])
        self.assertEqual(user_memory, [])

    def test_pruning_preserves_recent_history_per_channel(self):
        memory = []
        for index in range(pos_ai.AI_MEMORY_PER_CHANNEL_MESSAGES + 20):
            memory.append(
                {
                    "message_id": index + 1,
                    "channel_id": 1,
                    "content": f"first-{index}",
                }
            )
        for index in range(30):
            memory.append(
                {
                    "message_id": 10_000 + index,
                    "channel_id": 2,
                    "content": f"second-{index}",
                }
            )

        pos_ai._prune_guild_memory(memory)

        first_count = sum(item["channel_id"] == 1 for item in memory)
        second_count = sum(item["channel_id"] == 2 for item in memory)
        self.assertEqual(first_count, pos_ai.AI_MEMORY_PER_CHANNEL_MESSAGES)
        self.assertEqual(second_count, 30)
