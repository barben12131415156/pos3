import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.ai_chat import AIChatCog
from action_undo import derive_inverse, undo_exact_action
from config import POS_CREATOR_ID
from pos_ai import (
    _allowed_tool_names_for_text,
    _is_explicit_mutation_request,
    _perform_tool_action,
    execute_pos_tool,
)
from storage import close_all_connections, init_db
from vacation_mode import (
    VACATION_PING_REPLY,
    VacationModeState,
    get_owner_vacation_mode,
    handle_owner_vacation_ping,
    set_owner_vacation_mode,
)


class VacationModeStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "vacation.db")
        await init_db(self.db_path)

    async def asyncTearDown(self):
        await close_all_connections()
        self.tempdir.cleanup()

    async def test_state_is_persistent_idempotent_and_owner_only(self):
        self.assertFalse((await get_owner_vacation_mode(self.db_path)).enabled)

        with self.assertRaises(PermissionError):
            await set_owner_vacation_mode(
                True,
                actor_id=123,
                db_path=self.db_path,
            )

        enabled, changed = await set_owner_vacation_mode(
            True,
            actor_id=POS_CREATOR_ID,
            db_path=self.db_path,
        )
        self.assertTrue(changed)
        self.assertTrue(enabled.enabled)
        self.assertEqual(enabled.changed_by, POS_CREATOR_ID)
        self.assertTrue((await get_owner_vacation_mode(self.db_path)).enabled)

        repeated, changed = await set_owner_vacation_mode(
            True,
            actor_id=POS_CREATOR_ID,
            db_path=self.db_path,
        )
        self.assertFalse(changed)
        self.assertEqual(repeated, enabled)

        disabled, changed = await set_owner_vacation_mode(
            False,
            actor_id=POS_CREATOR_ID,
            db_path=self.db_path,
        )
        self.assertTrue(changed)
        self.assertFalse(disabled.enabled)


def _vacation_message(
    *,
    author_id: int = 100,
    direct_ping: bool = False,
    role_ping_id: int | None = None,
    creator_roles: tuple[int, ...] = (),
):
    roles = [
        SimpleNamespace(id=role_id, is_default=lambda: False)
        for role_id in creator_roles
    ]
    creator = SimpleNamespace(id=POS_CREATOR_ID, roles=roles)
    guild = SimpleNamespace(
        id=1,
        get_member=MagicMock(return_value=creator),
        fetch_member=AsyncMock(return_value=creator),
    )
    message = SimpleNamespace(
        id=50,
        guild=guild,
        channel=SimpleNamespace(id=2),
        author=SimpleNamespace(id=author_id, bot=False),
        mentions=[SimpleNamespace(id=POS_CREATOR_ID)] if direct_ping else [],
        raw_mentions=[POS_CREATOR_ID] if direct_ping else [],
        role_mentions=(
            [SimpleNamespace(id=role_ping_id)] if role_ping_id is not None else []
        ),
        raw_role_mentions=[role_ping_id] if role_ping_id is not None else [],
        reply=AsyncMock(),
    )
    return message


class VacationModePingTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_ping_gets_plain_safe_reply_when_active(self):
        message = _vacation_message(direct_ping=True)
        with patch(
            "vacation_mode.is_owner_vacation_mode_enabled",
            new=AsyncMock(return_value=True),
        ):
            handled = await handle_owner_vacation_ping(message)

        self.assertTrue(handled)
        message.reply.assert_awaited_once()
        args, kwargs = message.reply.await_args
        self.assertEqual(args[0], VACATION_PING_REPLY)
        self.assertFalse(kwargs["mention_author"])
        self.assertIsInstance(kwargs["allowed_mentions"], discord.AllowedMentions)
        self.assertFalse(kwargs["allowed_mentions"].everyone)
        self.assertFalse(kwargs["allowed_mentions"].users)
        self.assertFalse(kwargs["allowed_mentions"].roles)

    async def test_role_ping_only_matches_a_role_pumba_has(self):
        matched = _vacation_message(role_ping_id=77, creator_roles=(77, 88))
        unmatched = _vacation_message(role_ping_id=99, creator_roles=(77, 88))
        with patch(
            "vacation_mode.is_owner_vacation_mode_enabled",
            new=AsyncMock(return_value=True),
        ):
            self.assertTrue(await handle_owner_vacation_ping(matched))
            self.assertFalse(await handle_owner_vacation_ping(unmatched))

        matched.reply.assert_awaited_once()
        unmatched.reply.assert_not_awaited()

    async def test_inactive_mode_owner_and_unrelated_messages_do_not_reply(self):
        inactive = _vacation_message(direct_ping=True)
        owner = _vacation_message(author_id=POS_CREATOR_ID, direct_ping=True)
        unrelated = _vacation_message()
        with patch(
            "vacation_mode.is_owner_vacation_mode_enabled",
            new=AsyncMock(return_value=False),
        ) as state_check:
            self.assertFalse(await handle_owner_vacation_ping(inactive))
            self.assertFalse(await handle_owner_vacation_ping(owner))
            self.assertFalse(await handle_owner_vacation_ping(unrelated))

        inactive.reply.assert_not_awaited()
        owner.reply.assert_not_awaited()
        unrelated.reply.assert_not_awaited()
        state_check.assert_awaited_once()

    async def test_cog_handles_vacation_ping_after_moderation_before_ai_chat(self):
        message = _vacation_message(direct_ping=True)
        cog = AIChatCog(SimpleNamespace())
        moderation_gate = AsyncMock(return_value=False)
        vacation_handler = AsyncMock(return_value=True)
        ai_handler = AsyncMock(return_value=True)
        # discord.py unloads/reloads extension modules in an earlier integration
        # test. Patch the globals bound to this collected class so the test is
        # independent of the current sys.modules object.
        with patch.dict(
            AIChatCog.on_message.__globals__,
            {
                "wait_for_moderation": moderation_gate,
                "handle_owner_vacation_ping": vacation_handler,
                "handle_pos_ai": ai_handler,
            },
        ):
            await cog.on_message(message)

        moderation_gate.assert_awaited_once_with(message.id)
        vacation_handler.assert_awaited_once_with(message)
        ai_handler.assert_not_awaited()


class VacationModeToolTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_intent_surface_recognizes_all_vacation_actions(self):
        self.assertEqual(
            _allowed_tool_names_for_text("P.OS, активируй режим отпуска"),
            frozenset({"enable_vacation_mode"}),
        )
        self.assertEqual(
            _allowed_tool_names_for_text("P.OS, отключи режим отпуска"),
            frozenset({"disable_vacation_mode"}),
        )
        self.assertEqual(
            _allowed_tool_names_for_text("P.OS, режим отпуска сейчас включён?"),
            frozenset({"vacation_mode_status"}),
        )
        self.assertTrue(_is_explicit_mutation_request("P.OS, активируй режим отпуска"))

    async def test_tool_results_explain_mode_and_report_verified_status(self):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            author=SimpleNamespace(id=POS_CREATOR_ID),
        )
        bot = SimpleNamespace(guilds=[])
        with patch(
            "vacation_mode.set_owner_vacation_mode",
            new=AsyncMock(
                return_value=(
                    VacationModeState(True, 1, POS_CREATOR_ID),
                    True,
                )
            ),
        ) as setter:
            result = await _perform_tool_action(
                bot,
                message,
                "enable_vacation_mode",
                {},
                None,
            )
        self.assertIn("Режим отпуска активирован", result)
        self.assertIn("Telegram", result)
        setter.assert_awaited_once_with(True, actor_id=POS_CREATOR_ID)

        with patch(
            "vacation_mode.get_owner_vacation_mode",
            new=AsyncMock(return_value=VacationModeState(True, 1, POS_CREATOR_ID)),
        ):
            status = await _perform_tool_action(
                bot,
                message,
                "vacation_mode_status",
                {},
                None,
            )
        self.assertIn("активен", status)

    async def test_non_owner_cannot_call_vacation_tools(self):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            author=SimpleNamespace(id=123, bot=False),
        )
        result = await execute_pos_tool(
            SimpleNamespace(),
            message,
            {
                "function": {
                    "name": "enable_vacation_mode",
                    "arguments": "{}",
                }
            },
            allowed_tool_names=frozenset({"enable_vacation_mode"}),
        )
        self.assertIn("только по команде Пумбы", result)

    async def test_vacation_action_has_exact_reversible_state(self):
        operation, args = derive_inverse(
            "enable_vacation_mode",
            {},
            None,
            "Режим отпуска активирован.",
            {"target_guild_id": 1, "vacation_mode_enabled": False},
        )
        self.assertEqual(operation, "restore_vacation_mode")
        self.assertFalse(args["enabled"])

        action = {
            "target_guild_id": 1,
            "inverse_operation": operation,
            "inverse_args": args,
        }
        bot = SimpleNamespace(get_guild=MagicMock(return_value=SimpleNamespace(id=1)))
        with patch(
            "action_undo.set_owner_vacation_mode",
            new=AsyncMock(return_value=(VacationModeState(), True)),
        ) as setter:
            success, result = await undo_exact_action(bot, action)

        self.assertTrue(success)
        self.assertIn("снова выключен", result)
        setter.assert_awaited_once_with(False, actor_id=POS_CREATOR_ID)
