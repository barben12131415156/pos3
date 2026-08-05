import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

with patch("storage.add_entry"), \
     patch("storage.get_ai_context"), \
     patch("storage.update_ai_context"):
    import pos_ai
    from pos_ai import (
        _parse_bool, _summarize_tool_call,
        _MUTATING_TOOLS, _OWNER_CONFIRMATION_TOOLS,
        _OWNER_ONLY_TOOLS, _OWNER_INFO_TOOLS, _PUBLIC_ACTION_TOOLS, _READ_ONLY_TOOLS,
        _TOOL_ACTION_LABELS,
        _perform_shutdown, _prepare_mutating_tool_action, _resolve_member_smart,
        _resolve_category_smart, _resolve_guild, _split_user_identifiers,
    )

from cogs.ai_tools import POS_AI_TOOLS


class ToolSchemaTests(unittest.TestCase):
    def test_all_new_tools_registered(self):
        names = {t["function"]["name"] for t in POS_AI_TOOLS}
        for expected in [
            "edit_role", "create_channel", "delete_channel", "edit_channel",
            "set_channel_permission", "kick_user", "set_nickname", "create_invite",
            "edit_server", "lock_channel", "unlock_channel", "create_thread",
            "archive_thread", "voice_action", "security_scan", "set_security_preset",
            "list_members", "user_info", "read_messages", "search_logs", "search_pings",
            "bulk_user_action", "list_channels", "list_roles", "read_audit_log",
            "research_web", "read_web_page", "runtime_status",
            "manage_message", "manage_reaction", "list_invites", "revoke_invite",
            "list_webhooks", "delete_webhook", "list_automod_rules",
            "manage_automod_rule", "list_scheduled_events",
            "manage_scheduled_event", "create_forum_post", "set_server_safety",
            "list_emojis", "manage_emoji", "list_stickers", "manage_sticker",
            "remember_fact", "list_memory_entries", "delete_memory_entry",
            "refresh_server_memory", "undo_recent_actions",
            "contact_pumba_telegram",
            "enable_vacation_mode", "disable_vacation_mode",
            "vacation_mode_status",
        ]:
            self.assertIn(expected, names, f"tool {expected} отсутствует в схеме")

    def test_management_tools_are_owner_only(self):
        # Все новые управляющие инструменты должны требовать прав владельца.
        for name in ["edit_role", "create_channel", "delete_channel", "edit_channel",
                     "set_channel_permission", "kick_user", "set_nickname", "create_invite",
                     "edit_server", "lock_channel", "unlock_channel", "create_thread",
                     "archive_thread", "voice_action", "security_scan", "set_security_preset",
                     "list_members", "user_info", "read_messages", "search_logs", "search_pings",
                     "bulk_user_action", "research_web", "read_web_page", "runtime_status"]:
            self.assertIn(name, _OWNER_ONLY_TOOLS)

    def test_every_ai_tool_is_explicitly_scoped(self):
        names = {tool["function"]["name"] for tool in POS_AI_TOOLS}
        self.assertEqual(names, _OWNER_ONLY_TOOLS | _PUBLIC_ACTION_TOOLS)
        self.assertEqual(_PUBLIC_ACTION_TOOLS, frozenset({"contact_pumba_telegram"}))

    def test_every_owner_tool_has_label(self):
        for name in _OWNER_ONLY_TOOLS:
            self.assertIn(name, _TOOL_ACTION_LABELS, f"нет человекочитаемой метки для {name}")

    def test_schema_shapes_valid(self):
        for t in POS_AI_TOOLS:
            self.assertEqual(t["type"], "function")
            fn = t["function"]
            self.assertIn("name", fn)
            self.assertIn("description", fn)
            self.assertIn("parameters", fn)
            self.assertEqual(fn["parameters"]["type"], "object")

    def test_list_servers_registered_and_owner_only(self):
        names = {t["function"]["name"] for t in POS_AI_TOOLS}
        self.assertIn("list_servers", names)
        self.assertIn("list_servers", _OWNER_ONLY_TOOLS)
        # list_servers — read-only owner info: для не-владельца отказ без подтверждения.
        self.assertIn("list_servers", _OWNER_INFO_TOOLS)

    def test_create_invite_supports_cross_server(self):
        ci = next(t for t in POS_AI_TOOLS if t["function"]["name"] == "create_invite")
        props = ci["function"]["parameters"]["properties"]
        self.assertIn("server_id_or_name", props)

    def test_messages_and_settings_support_cross_server(self):
        for name in [
            "send_message",
            "dm_user",
            "get_settings",
            "update_settings",
            "mute_ai_for_user",
            "unmute_ai_for_user",
        ]:
            tool = next(t for t in POS_AI_TOOLS if t["function"]["name"] == name)
            self.assertIn("server_id_or_name", tool["function"]["parameters"]["properties"])

    def test_user_target_tools_accept_username_identifier(self):
        for name in ["ban_user", "add_role", "timeout_user", "ping_user", "voice_action"]:
            tool = next(t for t in POS_AI_TOOLS if t["function"]["name"] == name)
            props = tool["function"]["parameters"]["properties"]
            self.assertIn("user_identifier", props)
            self.assertNotIn("user_id", tool["function"]["parameters"].get("required", []))

    def test_new_info_tools_are_owner_info(self):
        for name in [
            "list_members",
            "user_info",
            "read_messages",
            "search_logs",
            "search_pings",
            "list_channels",
            "list_roles",
            "read_audit_log",
            "research_web",
            "read_web_page",
            "runtime_status",
            "vacation_mode_status",
        ]:
            self.assertIn(name, _OWNER_INFO_TOOLS)

    def test_owner_discord_mutations_execute_without_confirmation(self):
        direct_owner_actions = {
            "add_role",
            "remove_role",
            "edit_role",
            "unban_user",
            "untimeout_user",
            "lift_restrictions",
            "deactivate_raid_mode",
        }
        self.assertTrue(direct_owner_actions.issubset(_MUTATING_TOOLS))
        self.assertTrue(direct_owner_actions.isdisjoint(_OWNER_CONFIRMATION_TOOLS))

    def test_only_process_shutdown_keeps_owner_confirmation(self):
        self.assertEqual(_OWNER_ONLY_TOOLS - _READ_ONLY_TOOLS, _MUTATING_TOOLS)
        self.assertEqual(_OWNER_CONFIRMATION_TOOLS, frozenset({"shutdown_bot"}))

    def test_runtime_status_intent_is_narrow_and_read_only(self):
        self.assertEqual(
            pos_ai._allowed_tool_names_for_text("P.OS, какая версия сейчас запущена?"),
            frozenset({"runtime_status"}),
        )
        self.assertEqual(
            pos_ai._allowed_tool_names_for_text("Покажи active commit P.OS"),
            frozenset({"runtime_status"}),
        )
        self.assertEqual(
            pos_ai._allowed_tool_names_for_text("Расскажи про разные версии Discord"),
            frozenset(),
        )

    def test_extended_discord_intents_are_narrowly_exposed(self):
        cases = {
            "P.OS закрепи сообщение 123456789012345678 в канале general": {
                "manage_message"
            },
            "P.OS отзови приглашение abc": {"revoke_invite"},
            "P.OS создай правило AutoMod против mention spam": {
                "manage_automod_rule"
            },
            "P.OS покажи все webhook": {"list_webhooks"},
            "P.OS создай событие Тест завтра": {"manage_scheduled_event"},
            "P.OS создай эмодзи из вложения": {"manage_emoji"},
            "P.OS запомни Протокол: тест": {"remember_fact"},
            "P.OS обнови контекст сервера": {"refresh_server_memory"},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    pos_ai._allowed_tool_names_for_text(text),
                    frozenset(expected),
                )


class ChannelResolverTests(unittest.TestCase):
    def setUp(self):
        self.text_category = MagicMock(spec=discord.CategoryChannel)
        self.text_category.id = 101
        self.text_category.name = "Текстовые каналы"
        self.voice_category = MagicMock(spec=discord.CategoryChannel)
        self.voice_category.id = 102
        self.voice_category.name = "Голосовые каналы"
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.categories = [self.text_category, self.voice_category]
        self.guild.get_channel.side_effect = lambda channel_id: {
            101: self.text_category,
            102: self.voice_category,
        }.get(channel_id)

    def test_resolves_exact_category_name_and_id(self):
        self.assertIs(
            _resolve_category_smart(self.guild, "Текстовые каналы"),
            self.text_category,
        )
        self.assertIs(_resolve_category_smart(self.guild, "101"), self.text_category)

    def test_recovers_short_model_value_from_current_message(self):
        resolved = _resolve_category_smart(
            self.guild,
            "каналы",
            current_message_text=(
                "Создай канал в категории «Текстовые каналы» с временной темой."
            ),
        )
        self.assertIs(resolved, self.text_category)

    def test_does_not_guess_when_current_message_mentions_two_categories(self):
        resolved = _resolve_category_smart(
            self.guild,
            "каналы",
            current_message_text=(
                "Сравни категории Текстовые каналы и Голосовые каналы."
            ),
        )
        self.assertIsNone(resolved)


class UserResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_exact_username_before_display_name(self):
        target = SimpleNamespace(id=1, name="real_login", display_name="Other", global_name=None)
        decoy = SimpleNamespace(id=2, name="other_login", display_name="real_login", global_name=None)
        guild = SimpleNamespace(
            id=10,
            name="Test",
            members=[decoy, target],
            get_member=lambda uid: target if uid == 1 else decoy if uid == 2 else None,
        )

        member, error = await _resolve_member_smart(guild, "real_login")
        self.assertIs(member, target)
        self.assertIsNone(error)

    async def test_ambiguous_partial_requires_id(self):
        first = SimpleNamespace(id=1, name="alpha_one", display_name="First", global_name=None)
        second = SimpleNamespace(id=2, name="alpha_two", display_name="Second", global_name=None)
        guild = SimpleNamespace(
            id=10,
            name="Test",
            members=[first, second],
            get_member=lambda uid: None,
        )

        member, error = await _resolve_member_smart(guild, "alpha")
        self.assertIsNone(member)
        self.assertIn("точный username", error)

    async def test_display_name_is_not_a_mutation_target(self):
        member = SimpleNamespace(id=1, name="safe_login", display_name="Target", global_name="Target")
        guild = SimpleNamespace(id=10, name="Test", members=[member], get_member=lambda uid: None)

        resolved, error = await _resolve_member_smart(guild, "Target")

        self.assertIsNone(resolved)
        self.assertIn("точный username", error)

    async def test_read_only_mode_can_resolve_unique_display_name(self):
        member = SimpleNamespace(id=1, name="safe_login", display_name="Target", global_name="Target")
        guild = SimpleNamespace(id=10, name="Test", members=[member], get_member=lambda uid: None)

        resolved, error = await _resolve_member_smart(
            guild,
            "Target",
            allow_display_names=True,
            allow_partial=True,
        )

        self.assertIs(resolved, member)
        self.assertIsNone(error)

    def test_splits_user_identifier_lists(self):
        self.assertEqual(_split_user_identifiers("one, two\nthree"), ["one", "two", "three"])


class LegacyGuildResolverTests(unittest.TestCase):
    def setUp(self):
        self.current = SimpleNamespace(id=11111111111111111, name="Home")
        self.other = SimpleNamespace(id=22222222222222222, name="Juniper")
        self.bot = SimpleNamespace(
            guilds=[self.current, self.other],
            get_guild=lambda guild_id: {
                self.current.id: self.current,
                self.other.id: self.other,
            }.get(guild_id),
        )
        self.message = SimpleNamespace(guild=self.current)

    def test_unqualified_guild_name_in_user_text_does_not_reroute_action(self):
        resolved = _resolve_guild(
            self.bot,
            self.message,
            "забань пользователя Juniper за спам",
        )
        self.assertIs(resolved, self.current)

    def test_explicit_named_cross_server_target_is_resolved(self):
        resolved = _resolve_guild(
            self.bot,
            self.message,
            "забань user на сервере Juniper",
        )
        self.assertIs(resolved, self.other)

    def test_unknown_explicit_server_never_falls_back_to_current(self):
        resolved = _resolve_guild(
            self.bot,
            self.message,
            "забань user на сервере Missing",
        )
        self.assertIsNone(resolved)


class MutatingToolPreflightTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _guild(guild_id: int, name: str, *, can_kick: bool = True):
        bot_role = SimpleNamespace(position=10)
        bot_member = SimpleNamespace(
            id=9999,
            top_role=bot_role,
            guild_permissions=SimpleNamespace(kick_members=can_kick),
        )
        target = SimpleNamespace(
            id=123,
            name="exact_login",
            display_name="Display",
            global_name=None,
            top_role=SimpleNamespace(position=1),
        )
        guild = SimpleNamespace(
            id=guild_id,
            name=name,
            me=bot_member,
            owner=SimpleNamespace(id=777),
            members=[target],
            get_member=lambda user_id: target if user_id == target.id else None,
        )
        return guild, target

    async def test_cross_server_target_is_canonicalized_before_confirmation(self):
        source, _ = self._guild(1, "Source")
        target_guild, target_member = self._guild(2, "Target")
        bot = SimpleNamespace(
            guilds=[source, target_guild],
            user=SimpleNamespace(id=9999),
            get_guild=lambda guild_id: target_guild if guild_id == 2 else source if guild_id == 1 else None,
        )
        message = SimpleNamespace(guild=source)

        args, user_id, resolved_guild, labels, error = await _prepare_mutating_tool_action(
            bot,
            message,
            "kick_user",
            {"server_id_or_name": "Target", "user_identifier": "exact_login"},
            None,
        )

        self.assertIsNone(error)
        self.assertIs(resolved_guild, target_guild)
        self.assertEqual(user_id, target_member.id)
        self.assertEqual(args["server_id_or_name"], "2")
        self.assertEqual(args["user_id"], "123")
        self.assertTrue(any("Target" in label and "`2`" in label for label in labels))

    async def test_preflight_rejects_missing_bot_permission(self):
        guild, _ = self._guild(1, "Target", can_kick=False)
        bot = SimpleNamespace(
            guilds=[guild],
            user=SimpleNamespace(id=9999),
            get_guild=lambda guild_id: guild if guild_id == 1 else None,
        )
        message = SimpleNamespace(guild=guild)

        _args, _user_id, _guild, _labels, error = await _prepare_mutating_tool_action(
            bot,
            message,
            "kick_user",
            {"user_identifier": "exact_login"},
            None,
        )

        self.assertIn("kick_members", error)

    def test_equal_position_newer_role_is_below_bot_role(self):
        bot_role = SimpleNamespace(id=100, position=1)
        target_role = SimpleNamespace(
            id=200,
            name="Created by P.OS",
            position=1,
            managed=False,
            is_default=lambda: False,
        )
        guild = SimpleNamespace(me=SimpleNamespace(top_role=bot_role))

        self.assertIsNone(pos_ai._role_hierarchy_error(guild, target_role))

    def test_equal_position_older_role_is_not_manageable(self):
        bot_role = SimpleNamespace(id=200, position=1)
        target_role = SimpleNamespace(
            id=100,
            name="Above P.OS",
            position=1,
            managed=False,
            is_default=lambda: False,
        )
        guild = SimpleNamespace(me=SimpleNamespace(top_role=bot_role))

        error = pos_ai._role_hierarchy_error(guild, target_role)

        self.assertIn("не ниже роли P.OS", error)


class ToolExecutionPolicyTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _kick_call():
        return {
            "id": "kick-juniper",
            "function": {
                "name": "kick_user",
                "arguments": '{"user_id":"1351879409832951893","reason":"По приказу владельца"}',
            },
        }

    async def test_owner_action_executes_immediately_without_dm_confirmation(self):
        guild = SimpleNamespace(id=1, name="Test")
        message = SimpleNamespace(
            guild=guild,
            author=SimpleNamespace(id=968698192411652176),
            content="кикни бота джунипера с сервера",
        )
        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        prepared_args = {
            "user_id": "1351879409832951893",
            "server_id_or_name": "1",
            "reason": "По приказу владельца",
        }
        prepare = AsyncMock(
            return_value=(prepared_args, 1351879409832951893, guild, ["сервер: Test (`1`)"], None)
        )
        perform = AsyncMock(return_value="JuniperBot кикнут с сервера.")
        persist = AsyncMock(return_value=True)
        creator = AsyncMock()

        with patch.object(pos_ai, "_prepare_mutating_tool_action", new=prepare), \
             patch.object(pos_ai, "_perform_tool_action", new=perform), \
             patch.object(pos_ai, "_log_pos_tool_result", new=persist), \
             patch.object(pos_ai, "_get_creator_user", new=creator):
            result = await pos_ai.execute_pos_tool(
                bot,
                message,
                self._kick_call(),
                allowed_tool_names=frozenset({"kick_user"}),
            )

        self.assertEqual(result, "JuniperBot кикнут с сервера.")
        perform.assert_awaited_once()
        persist.assert_awaited_once()
        creator.assert_not_awaited()

    async def test_owner_ban_uses_mentioned_target_and_code_level_reason(self):
        target_id = 1351879409832951893
        guild = SimpleNamespace(id=1, name="Test")
        message = SimpleNamespace(
            guild=guild,
            channel=SimpleNamespace(id=10),
            author=SimpleNamespace(id=968698192411652176),
            content=f"забань <@{target_id}>",
            mentions=[SimpleNamespace(id=target_id)],
            raw_mentions=[target_id],
            role_mentions=[],
            channel_mentions=[],
            reference=None,
        )
        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        prepare = AsyncMock(
            return_value=(
                {
                    "user_id": str(target_id),
                    "server_id_or_name": "1",
                    "reason": "По распоряжению Пумбы",
                },
                target_id,
                guild,
                ["сервер: Test (`1`)"],
                None,
            )
        )
        perform = AsyncMock(return_value="Пользователь успешно забанен.")

        with patch.object(pos_ai, "_prepare_mutating_tool_action", new=prepare), patch.object(
            pos_ai,
            "_perform_tool_action",
            new=perform,
        ), patch.object(pos_ai, "_log_pos_tool_result", new=AsyncMock(return_value=True)):
            result = await pos_ai.execute_pos_tool(
                bot,
                message,
                {
                    "id": "ban-without-reason",
                    "function": {
                        "name": "ban_user",
                        "arguments": json.dumps(
                            {"user_id": "111111111111111111"}
                        ),
                    },
                },
                allowed_tool_names=frozenset({"ban_user"}),
            )

        self.assertIn("успешно забанен", result)
        prepared_args = prepare.await_args.args[3]
        self.assertEqual(prepared_args["user_id"], str(target_id))
        self.assertEqual(prepared_args["reason"], "По распоряжению Пумбы")

    async def test_outsider_action_is_sent_to_owner_without_execution(self):
        pos_ai._owner_approval_last_requested.clear()
        guild = SimpleNamespace(id=1, name="Test")
        message = SimpleNamespace(
            guild=guild,
            author=SimpleNamespace(id=123, name="guest", display_name="Guest"),
            content="кикни бота джунипера с сервера",
            jump_url="https://discord.test/messages/1",
        )
        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        prepared_args = {
            "user_id": "1351879409832951893",
            "server_id_or_name": "1",
            "reason": "просьба участника",
        }
        prepare = AsyncMock(
            return_value=(prepared_args, 1351879409832951893, guild, ["сервер: Test (`1`)"], None)
        )
        perform = AsyncMock(return_value="не должно выполниться")
        owner_message = SimpleNamespace()
        owner = SimpleNamespace(send=AsyncMock(return_value=owner_message))
        view = MagicMock()

        with patch.object(pos_ai, "_prepare_mutating_tool_action", new=prepare), \
             patch.object(pos_ai, "_perform_tool_action", new=perform), \
             patch.object(pos_ai, "_get_creator_user", new=AsyncMock(return_value=owner)), \
             patch("forms.PosActionConfirmView", return_value=view):
            result = await pos_ai.execute_pos_tool(
                bot,
                message,
                self._kick_call(),
                allowed_tool_names=frozenset({"kick_user"}),
            )

        self.assertIn("отправлен Пумбе на подтверждение", result)
        owner.send.assert_awaited_once()
        view.bind_message.assert_called_once_with(owner_message)
        perform.assert_not_awaited()

        with patch.object(pos_ai, "_prepare_mutating_tool_action", new=prepare), \
             patch.object(pos_ai, "_perform_tool_action", new=perform), \
             patch.object(pos_ai, "_get_creator_user", new=AsyncMock(return_value=owner)), \
             patch("forms.PosActionConfirmView", return_value=view):
            repeated = await pos_ai.execute_pos_tool(
                bot,
                message,
                self._kick_call(),
                allowed_tool_names=frozenset({"kick_user"}),
            )

        self.assertIn("Предыдущий запрос", repeated)
        owner.send.assert_awaited_once()
        pos_ai._owner_approval_last_requested.clear()

    async def test_edit_role_can_grant_and_revoke_permissions(self):
        original_permissions = discord.Permissions.none()
        original_permissions.manage_messages = True
        role = SimpleNamespace(
            id=10,
            name="Moderator",
            permissions=original_permissions,
            is_default=lambda: False,
            managed=False,
            edit=AsyncMock(),
        )
        guild = SimpleNamespace(id=1, name="Test")
        message = SimpleNamespace(guild=guild)
        bot = SimpleNamespace(user=SimpleNamespace(id=9999), guilds=[guild])

        with patch.object(pos_ai, "resolve_role_smart", return_value=role):
            result = await pos_ai._perform_tool_action(
                bot,
                message,
                "edit_role",
                {
                    "role_id_or_name": "Moderator",
                    "grant_permissions": "kick_members",
                    "revoke_permissions": "manage_messages",
                },
                None,
            )

        permissions = role.edit.await_args.kwargs["permissions"]
        self.assertFalse(permissions.manage_messages)
        self.assertTrue(permissions.kick_members)
        self.assertIn("обновлена", result)
        self.assertIn("права", result)
        self.assertNotIn("permissions", result)

    async def test_list_servers_hides_internal_cache_name(self):
        current_guild = SimpleNamespace(id=1, name="Test", member_count=3)
        message = SimpleNamespace(guild=current_guild)
        bot = SimpleNamespace(guilds=[current_guild], user=None)

        result = await pos_ai._perform_tool_action(
            bot,
            message,
            "list_servers",
            {},
            None,
        )

        self.assertIn("Фактические серверы", result)
        self.assertNotIn("bot.guilds", result)

    async def test_runtime_status_reports_only_verified_deploy_facts(self):
        bot = SimpleNamespace(guilds=[object(), object()])
        message = SimpleNamespace(guild=None)
        environment = {
            "RAILWAY_GIT_COMMIT_SHA": "bcdf04f1234567890abcdef",
            "SECRET_API_KEY": "must-not-leak",
        }

        with patch.dict(pos_ai.os.environ, environment, clear=True), \
             patch.object(pos_ai, "ai_has_configured_provider", return_value=True), \
             patch.object(pos_ai, "ai_has_configured_media_provider", return_value=True), \
             patch.object(pos_ai, "BRAVE_SEARCH_API_KEY", "configured"):
            result = await pos_ai._perform_tool_action(
                bot,
                message,
                "runtime_status",
                {},
                None,
            )

        self.assertIn("bcdf04f12345", result)
        self.assertIn("подключено серверов: 2", result)
        self.assertIn("нативный анализ аудио/видео: настроен", result)
        self.assertNotIn("must-not-leak", result)

    async def test_runtime_status_does_not_invent_missing_commit(self):
        bot = SimpleNamespace(guilds=[])
        message = SimpleNamespace(guild=None)

        with patch.dict(pos_ai.os.environ, {}, clear=True), \
             patch.object(pos_ai, "ai_has_configured_provider", return_value=False), \
             patch.object(pos_ai, "ai_has_configured_media_provider", return_value=False), \
             patch.object(pos_ai, "BRAVE_SEARCH_API_KEY", None):
            result = await pos_ai._perform_tool_action(
                bot,
                message,
                "runtime_status",
                {},
                None,
            )

        self.assertIn("SHA подтвердить нельзя", result)
        self.assertIn("основной AI: не настроен", result)
        self.assertIn("Wikipedia-поиск", result)


class ShutdownPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_preparation_flushes_memory_without_closing_early(self):
        bot = SimpleNamespace(close=AsyncMock())
        flush = AsyncMock()

        with patch.object(pos_ai, "flush_ai_memory", new=flush):
            result = await _perform_shutdown(bot, {"reason": "обновление"})

        flush.assert_awaited_once_with()
        bot.close.assert_not_awaited()
        self.assertIn("подготовлен", result)

    async def test_shutdown_preparation_aborts_when_memory_flush_fails(self):
        bot = SimpleNamespace(close=AsyncMock())
        flush = AsyncMock(side_effect=RuntimeError("db unavailable"))

        with patch.object(pos_ai, "flush_ai_memory", new=flush):
            result = await _perform_shutdown(bot, {})

        bot.close.assert_not_awaited()
        self.assertIn("Остановка отменена", result)


class InviteBugRegressionTests(unittest.TestCase):
    """Баг: 'создай роль X' уходил в ветку инвайта, т.к. INVITE_PATTERN ловил 'создай'."""

    def test_conflicting_patterns_removed(self):
        # Эти паттерны были источником конфликта и должны быть удалены.
        for attr in ["INVITE_PATTERN", "ADD_ROLE_PATTERN", "REMOVE_ROLE_PATTERN"]:
            self.assertFalse(hasattr(pos_ai, attr), f"{attr} должен быть удалён, чтобы не перехватывать 'создай'")

    def test_critical_ban_patterns_kept(self):
        # Критичные бан/разбан остаются детерминированными ради надёжности.
        self.assertTrue(hasattr(pos_ai, "BAN_PATTERN"))
        self.assertTrue(hasattr(pos_ai, "UNBAN_PATTERN"))


class ParseBoolTests(unittest.TestCase):
    def test_truthy(self):
        for v in ["true", "1", "да", "yes", "on", "вкл", "True", "ДА"]:
            self.assertTrue(_parse_bool(v))

    def test_falsy(self):
        for v in ["false", "0", "нет", "no", ""]:
            self.assertFalse(_parse_bool(v))

    def test_default(self):
        self.assertTrue(_parse_bool(None, default=True))
        self.assertFalse(_parse_bool("", default=False))


class SummaryTests(unittest.TestCase):
    def test_summary_includes_label_and_details(self):
        s = _summarize_tool_call("create_role", {"name": "Ветеран", "color": "ff0000"}, None)
        self.assertIn("создание роли", s)
        self.assertIn("Ветеран", s)

    def test_summary_with_user(self):
        s = _summarize_tool_call("kick_user", {"reason": "спам"}, 123456789012345678)
        self.assertIn("кик", s)
        self.assertIn("123456789012345678", s)

    def test_summary_unknown_tool_falls_back_to_name(self):
        s = _summarize_tool_call("some_future_tool", {}, None)
        self.assertIn("some_future_tool", s)

    def test_summary_uses_human_readable_argument_labels(self):
        summary = _summarize_tool_call(
            "delete_channel",
            {
                "server_id_or_name": "123",
                "channel_id_or_name": "456",
            },
            None,
        )

        self.assertIn("сервер=123", summary)
        self.assertIn("канал=456", summary)
        self.assertNotIn("server_id_or_name", summary)
        self.assertNotIn("channel_id_or_name", summary)

    def test_event_formatter_hides_legacy_tool_names(self):
        event = {
            "id": 1,
            "ts": 1,
            "event_type": "pos_tool",
            "summary": "P.OS tool `delete_channel`: raw",
            "details": json.dumps({
                "tool": "delete_channel",
                "args": {
                    "server_id_or_name": "123",
                    "channel_id_or_name": "456",
                },
                "result": "Канал удалён.",
            }),
            "actor_name": "Pumba",
        }

        line = pos_ai._format_event_line(event)

        self.assertIn("удаление канала", line)
        self.assertIn("канал=456", line)
        self.assertNotIn("tool", line.lower())
        self.assertNotIn("delete_channel", line)
        self.assertNotIn("channel_id_or_name", line)

    def test_event_formatter_hides_legacy_discord_log_embed(self):
        event = {
            "id": 2,
            "ts": 1,
            "event_type": "message",
            "summary": (
                "P.OS tool action: Инструмент: `create_channel`; "
                "server_id_or_name=123, name=test"
            ),
        }

        line = pos_ai._format_event_line(event)

        self.assertIn("создание канала", line)
        self.assertIn("сервер=123", line)
        self.assertNotIn("tool", line.lower())
        self.assertNotIn("create_channel", line)
        self.assertNotIn("server_id_or_name", line)


if __name__ == "__main__":
    unittest.main()
