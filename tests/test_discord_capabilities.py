import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord_capabilities


class ExtendedCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_listing_never_exposes_token(self):
        webhook = SimpleNamespace(
            id=123456789012345678,
            name="audit",
            channel_id=42,
            type="incoming",
            user=SimpleNamespace(id=99),
            token="never-show-this",
        )
        guild = SimpleNamespace(
            name="Test",
            webhooks=AsyncMock(return_value=[webhook]),
        )

        result = await discord_capabilities.execute_extended_capability(
            guild,
            SimpleNamespace(),
            "list_webhooks",
            {},
        )

        self.assertIn("audit", result)
        self.assertIn("123456789012345678", result)
        self.assertNotIn("never-show-this", result)

    async def test_native_server_safety_is_applied_through_guild_edit(self):
        guild = SimpleNamespace(
            name="Test",
            edit=AsyncMock(),
        )

        result = await discord_capabilities.execute_extended_capability(
            guild,
            SimpleNamespace(),
            "set_server_safety",
            {
                "invites_disabled": "true",
                "dms_disabled_minutes": "30",
                "raid_alerts_enabled": "true",
            },
        )

        guild.edit.assert_awaited_once()
        kwargs = guild.edit.await_args.kwargs
        self.assertTrue(kwargs["invites_disabled"])
        self.assertFalse(kwargs["raid_alerts_disabled"])
        self.assertIn("dms_disabled_until", kwargs)
        self.assertIn("обновлены", result)

    async def test_invalid_server_safety_boolean_is_rejected(self):
        guild = SimpleNamespace(name="Test", edit=AsyncMock())

        result = await discord_capabilities.execute_extended_capability(
            guild,
            SimpleNamespace(),
            "set_server_safety",
            {"invites_disabled": "maybe"},
        )

        self.assertIn("true или false", result)
        guild.edit.assert_not_awaited()

    async def test_keyword_automod_rule_is_created_enabled(self):
        created_rule = SimpleNamespace(
            id=123456789012345678,
            name="Scam links",
        )
        guild = SimpleNamespace(
            name="Test",
            create_automod_rule=AsyncMock(return_value=created_rule),
        )

        result = await discord_capabilities.execute_extended_capability(
            guild,
            SimpleNamespace(),
            "manage_automod_rule",
            {
                "action": "create_keyword",
                "name": "Scam links",
                "keywords": "free nitro, wallet connect",
                "enabled": "true",
            },
        )

        guild.create_automod_rule.assert_awaited_once()
        kwargs = guild.create_automod_rule.await_args.kwargs
        self.assertTrue(kwargs["enabled"])
        self.assertEqual(
            kwargs["trigger"].keyword_filter,
            ["free nitro", "wallet connect"],
        )
        self.assertIn("создано", result)

    async def test_invalid_automod_enabled_value_is_rejected(self):
        guild = SimpleNamespace(
            name="Test",
            create_automod_rule=AsyncMock(),
        )

        result = await discord_capabilities.execute_extended_capability(
            guild,
            SimpleNamespace(),
            "manage_automod_rule",
            {
                "action": "create_keyword",
                "name": "Scam links",
                "keywords": "free nitro",
                "enabled": "sometimes",
            },
        )

        self.assertIn("true или false", result)
        guild.create_automod_rule.assert_not_awaited()

    async def test_unknown_scheduled_event_type_never_falls_back_to_voice(self):
        guild = SimpleNamespace(
            name="Test",
            create_scheduled_event=AsyncMock(),
        )

        result = await discord_capabilities.execute_extended_capability(
            guild,
            SimpleNamespace(),
            "manage_scheduled_event",
            {
                "action": "create",
                "name": "Test",
                "start_time": "2030-01-01T10:00:00Z",
                "event_type": "unknown",
            },
        )

        self.assertIn("external, stage или voice", result)
        guild.create_scheduled_event.assert_not_awaited()

    async def test_message_edit_refuses_non_pos_message(self):
        target = SimpleNamespace(
            id=123456789012345678,
            author=SimpleNamespace(id=10),
            edit=AsyncMock(),
        )
        guild = SimpleNamespace(me=SimpleNamespace(id=20))

        with patch.object(
            discord_capabilities,
            "_fetch_message",
            new=AsyncMock(return_value=(target, None)),
        ):
            result = await discord_capabilities._manage_message(
                guild,
                {"action": "edit", "text": "new"},
            )

        self.assertIn("только собственные", result)
        target.edit.assert_not_awaited()

    async def test_unknown_extended_tool_returns_none(self):
        result = await discord_capabilities.execute_extended_capability(
            SimpleNamespace(),
            SimpleNamespace(),
            "unknown_tool",
            {},
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
