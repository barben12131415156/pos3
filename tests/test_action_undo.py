import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import storage
from action_undo import derive_inverse, undo_recent_action_group
from pos_ai import _build_tool_reference_context
from storage import (
    close_all_connections,
    init_db,
    list_recent_pos_tool_actions,
    record_pos_tool_action,
)


class ActionJournalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "actions.db")
        await init_db(self.db_path)

    async def asyncTearDown(self):
        await close_all_connections()
        self.tempdir.cleanup()

    async def test_kick_and_ban_are_claimed_in_reverse_execution_order(self):
        common = {
            "source_guild_id": 1352394387362939003,
            "source_channel_id": 1352394388449267897,
            "source_message_id": 200,
            "actor_id": 968698192411652176,
            "target_guild_id": 1352394387362939003,
            "success": True,
            "ts": 1_800_000_000,
            "db_path": self.db_path,
        }
        await record_pos_tool_action(
            **common,
            operation="kick_user",
            args={"user_id": "1351879409832951893"},
            result="Кик выполнен.",
            inverse_operation="restore_kick_user",
            inverse_args={"target_guild_id": common["target_guild_id"], "user_id": 1351879409832951893},
        )
        await record_pos_tool_action(
            **common,
            operation="ban_user",
            args={"user_id": "1351879409832951893"},
            result="Бан выполнен.",
            inverse_operation="unban_user",
            inverse_args={"target_guild_id": common["target_guild_id"], "user_id": 1351879409832951893},
        )

        message = SimpleNamespace(
            author=SimpleNamespace(id=common["actor_id"]),
            guild=SimpleNamespace(id=common["source_guild_id"]),
            channel=SimpleNamespace(id=common["source_channel_id"]),
        )
        undo = AsyncMock(side_effect=[(True, "бан снят"), (True, "возврат подготовлен")])
        async def claim_with_path(**kwargs):
            return await storage.claim_recent_pos_action_group(
                **kwargs,
                db_path=self.db_path,
            )

        with patch("action_undo.undo_exact_action", new=undo), patch(
            "action_undo.claim_recent_pos_action_group",
            new=AsyncMock(side_effect=claim_with_path),
        ):
            with patch("action_undo.finish_pos_action_undo") as finish:
                async def finish_with_path(action_id, **kwargs):
                    return await storage.finish_pos_action_undo(
                        action_id,
                        **kwargs,
                        db_path=self.db_path,
                    )

                finish.side_effect = finish_with_path
                result = await undo_recent_action_group(
                    SimpleNamespace(),
                    message,
                    {"within_minutes": "1440"},
                    {"ban_user": "бан", "kick_user": "кик"},
                )

        operations = [call.args[1]["inverse_operation"] for call in undo.await_args_list]
        self.assertEqual(operations, ["unban_user", "restore_kick_user"])
        self.assertIn("полностью отменена", result)
        rows = await list_recent_pos_tool_actions(
            actor_id=common["actor_id"],
            source_guild_id=common["source_guild_id"],
            source_channel_id=common["source_channel_id"],
            db_path=self.db_path,
        )
        self.assertEqual({row["undo_status"] for row in rows}, {"undone"})

    async def test_transient_failed_inverse_can_be_claimed_again(self):
        action_id = await record_pos_tool_action(
            source_guild_id=1352394387362939003,
            source_channel_id=1352394388449267897,
            source_message_id=201,
            actor_id=968698192411652176,
            target_guild_id=1352394387362939003,
            operation="create_role",
            args={"name": "temporary"},
            result="Роль создана (ID 1352394388449267899).",
            success=True,
            inverse_operation="delete_role",
            inverse_args={
                "target_guild_id": 1352394387362939003,
                "role_id": 1352394388449267899,
            },
            ts=1_800_000_000,
            db_path=self.db_path,
        )
        first = await storage.claim_recent_pos_action_group(
            actor_id=968698192411652176,
            source_guild_id=1352394387362939003,
            source_channel_id=1352394388449267897,
            within_seconds=86400,
            db_path=self.db_path,
        )
        self.assertEqual([item["id"] for item in first], [action_id])
        await storage.finish_pos_action_undo(
            action_id,
            status="failed",
            result="temporary Discord failure",
            db_path=self.db_path,
        )
        second = await storage.claim_recent_pos_action_group(
            actor_id=968698192411652176,
            source_guild_id=1352394387362939003,
            source_channel_id=1352394388449267897,
            within_seconds=86400,
            db_path=self.db_path,
        )
        self.assertEqual([item["id"] for item in second], [action_id])

    def test_inverse_never_reuses_a_reply_author_id(self):
        operation, args = derive_inverse(
            "ban_user",
            {"server_id_or_name": "1352394387362939003"},
            1351879409832951893,
            "Пользователь успешно забанен.",
            {"target_guild_id": 1352394387362939003},
        )
        self.assertEqual(operation, "unban_user")
        self.assertEqual(args["user_id"], 1351879409832951893)

    def test_reaction_inverse_preserves_preexisting_pos_reaction(self):
        operation, args = derive_inverse(
            "manage_reaction",
            {
                "action": "add",
                "channel_id_or_name": "1352394388449267897",
                "message_id": "1352394388449267898",
                "emoji": "✅",
            },
            None,
            "Реакция добавлена.",
            {
                "target_guild_id": 1352394387362939003,
                "pos_had_reaction": True,
            },
        )
        self.assertIsNone(operation)
        self.assertIsNone(args)


class ToolReferenceContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_to_pos_is_not_a_user_target(self):
        bot_author = SimpleNamespace(
            id=1393592093137440838,
            name="P.OS",
            display_name="P.OS",
        )
        owner = SimpleNamespace(
            id=968698192411652176,
            name="pumba",
            display_name="Pumba",
        )
        referenced = SimpleNamespace(
            id=10,
            author=bot_author,
            content="Операция выполнена для пользователя 1351879409832951893.",
            mentions=[],
            role_mentions=[],
            channel_mentions=[],
            guild=None,
        )

        class EmptyHistory:
            def history(self, **_kwargs):
                async def iterator():
                    if False:
                        yield None

                return iterator()

        message = SimpleNamespace(
            id=11,
            content="не, верни всё обратно",
            author=owner,
            channel=EmptyHistory(),
            mentions=[],
            role_mentions=[],
            channel_mentions=[],
            guild=None,
        )
        context = await _build_tool_reference_context(
            message,
            SimpleNamespace(user=bot_author),
            referenced,
        )
        self.assertNotIn("reply-target: P.OS", context)
        self.assertIn("never a user target", context)
        self.assertNotIn("1351879409832951893", context)
