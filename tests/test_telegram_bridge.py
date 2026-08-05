import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from storage import (
    claim_telegram_contact_response,
    close_all_connections,
    complete_telegram_contact_response,
    get_telegram_contact_by_message,
    init_db,
    mark_telegram_contact_sent,
    reserve_telegram_contact_request,
)
from telegram_bridge import TelegramOwnerBridge


class TelegramStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "telegram.db")
        await init_db(self.db_path)

    async def asyncTearDown(self):
        await close_all_connections()
        self.tempdir.cleanup()

    async def _reserve(self, **overrides):
        values = {
            "guild_id": 1,
            "channel_id": 2,
            "discord_message_id": 3,
            "discord_user_id": 4,
            "discord_username": "member (@member)",
            "message_text": "Передай Пумбе точный текст",
            "urgency": "normal",
            "urgency_reason": "обычный запрос",
            "min_interval_seconds": 300,
            "daily_limit": 5,
            "global_hourly_limit": 20,
            "max_pending_per_user": 2,
            "now": 1_800_000_000,
            "db_path": self.db_path,
        }
        values.update(overrides)
        return await reserve_telegram_contact_request(**values)

    async def test_deduplicates_message_and_content_and_enforces_cooldown(self):
        request, reason = await self._reserve()
        self.assertIsNotNone(request)
        self.assertIsNone(reason)

        duplicate, reason = await self._reserve()
        self.assertIsNone(duplicate)
        self.assertEqual(reason, "already_processed")

        cooldown, reason = await self._reserve(
            discord_message_id=5,
            message_text="Другой текст",
            now=1_800_000_100,
        )
        self.assertIsNone(cooldown)
        self.assertTrue(reason.startswith("cooldown:"))

        same_content, reason = await self._reserve(
            discord_message_id=6,
            now=1_800_000_400,
        )
        self.assertIsNone(same_content)
        self.assertEqual(reason, "duplicate_content")

    async def test_owner_reply_is_claimed_once_and_bound_to_telegram_message(self):
        request, _ = await self._reserve()
        await mark_telegram_contact_sent(request["id"], 900, self.db_path)
        stored = await get_telegram_contact_by_message(900, self.db_path)
        self.assertEqual(stored["discord_user_id"], 4)
        self.assertTrue(
            await claim_telegram_contact_response(
                request["id"],
                response_text="Ответ Пумбы",
                db_path=self.db_path,
            )
        )
        self.assertFalse(
            await claim_telegram_contact_response(
                request["id"],
                response_text="Дубликат",
                db_path=self.db_path,
            )
        )
        self.assertTrue(
            await complete_telegram_contact_response(
                request["id"],
                response_text="Ответ Пумбы",
                delivery_target="dm",
                db_path=self.db_path,
            )
        )


class TelegramBridgePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthorized_telegram_sender_is_ignored(self):
        bridge = TelegramOwnerBridge(SimpleNamespace())
        bridge._send_telegram = AsyncMock()
        with patch("telegram_bridge.TELEGRAM_OWNER_USER_ID", 100), patch(
            "telegram_bridge.TELEGRAM_OWNER_CHAT_ID", 200
        ):
            await bridge._handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "from": {"id": 999},
                        "chat": {"id": 200},
                        "text": "чужой ответ",
                    }
                }
            )
        bridge._send_telegram.assert_not_awaited()

    async def test_forward_uses_exact_current_discord_message(self):
        bot = SimpleNamespace()
        bridge = TelegramOwnerBridge(bot)
        bridge._session = SimpleNamespace(closed=False)
        bridge._send_telegram = AsyncMock(return_value=777)
        message = SimpleNamespace(
            id=30,
            content="напиши Пумбе в телеграм: релиз готов",
            author=SimpleNamespace(id=40, display_name="Member", name="member"),
            guild=SimpleNamespace(id=50, name="Test"),
            channel=SimpleNamespace(id=60, name="general"),
            jump_url="https://discord.com/channels/50/60/30",
        )
        reserved = {
            "id": 1,
            "message_text": message.content,
        }
        reserve = AsyncMock(return_value=(reserved, None))
        with patch("telegram_bridge.TELEGRAM_BOT_TOKEN", "token"), patch(
            "telegram_bridge.TELEGRAM_OWNER_USER_ID", 100
        ), patch("telegram_bridge.TELEGRAM_OWNER_CHAT_ID", 200), patch(
            "telegram_bridge.classify_contact_urgency",
            new=AsyncMock(return_value=("normal", "обычный запрос")),
        ), patch("telegram_bridge.reserve_telegram_contact_request", new=reserve), patch(
            "telegram_bridge.update_telegram_contact_urgency",
            new=AsyncMock(),
        ), patch(
            "telegram_bridge.mark_telegram_contact_sent",
            new=AsyncMock(),
        ):
            result = await bridge.forward_contact(message)

        self.assertEqual(
            reserve.await_args.kwargs["message_text"],
            "напиши Пумбе в телеграм: релиз готов",
        )
        self.assertNotIn("100", result)
        self.assertNotIn("200", result)
        self.assertIn("передано Пумбе", result)

    async def test_rate_limited_request_does_not_spend_urgency_ai_call(self):
        bridge = TelegramOwnerBridge(SimpleNamespace())
        bridge._session = SimpleNamespace(closed=False)
        message = SimpleNamespace(
            id=31,
            content="напиши Пумбе ещё раз",
            author=SimpleNamespace(id=40, display_name="Member", name="member"),
            guild=SimpleNamespace(id=50, name="Test"),
            channel=SimpleNamespace(id=60, name="general"),
        )
        classify = AsyncMock(return_value=("normal", "обычный запрос"))
        with patch("telegram_bridge.TELEGRAM_BOT_TOKEN", "token"), patch(
            "telegram_bridge.TELEGRAM_OWNER_USER_ID", 100
        ), patch("telegram_bridge.TELEGRAM_OWNER_CHAT_ID", 200), patch(
            "telegram_bridge.reserve_telegram_contact_request",
            new=AsyncMock(return_value=(None, "cooldown:120")),
        ), patch("telegram_bridge.classify_contact_urgency", new=classify):
            result = await bridge.forward_contact(message)

        self.assertIn("120", result)
        classify.assert_not_awaited()
