import asyncio
import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import cogs.logging_events as logging_events
import storage
from message_gate import begin_moderation, finish_moderation, wait_for_moderation
from moderation import extract_urls
from pos_ai import (
    _allowed_user_mentions_for_text,
    _extract_textual_tool_calls,
    _message_target_user_id,
    _normalize_reply_user_mentions,
    _send_plain_response,
    execute_pos_tool,
    request_pos_reply,
)
from storage import close_all_connections, restore_db_from_discord


class MessageGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiter_can_arrive_before_moderation_listener(self):
        message_id = 987654321
        waiter = asyncio.create_task(wait_for_moderation(message_id, timeout=1.0))
        await asyncio.sleep(0)
        begin_moderation(message_id)
        finish_moderation(message_id, True)
        self.assertTrue(await waiter)


class UrlExtractionTests(unittest.TestCase):
    def test_extracts_bare_domains_but_not_common_filename(self):
        self.assertEqual(
            extract_urls("open suspicious-site.xyz/path and report.pdf"),
            ["suspicious-site.xyz/path"],
        )


class ToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    def test_textual_tool_parser_rejects_code_and_unapproved_tools(self):
        self.assertEqual(
            _extract_textual_tool_calls(
                "tool_call: kick_user(user_id=__import__('os').getuid())",
                frozenset({"kick_user"}),
            ),
            [],
        )
        self.assertEqual(
            _extract_textual_tool_calls(
                "tool_call: kick_user(user_id='123')",
                frozenset({"ban_user"}),
            ),
            [],
        )

    def test_textual_tool_parser_normalizes_provider_formats(self):
        samples = [
            (
                "tool_call:\n```json\n"
                '{"name":"kick_user","arguments":{"user_id":"1351879409832951893"}}'
                "\n```"
            ),
            (
                "<tool_call>"
                '{"name":"kick_user","arguments":{"user_id":"1351879409832951893"}}'
                "</tool_call>"
            ),
            (
                "assistant to=functions.kick_user\n"
                '{"user_id":"1351879409832951893"}'
            ),
            (
                '{"tool_call":{"name":"kick_user","arguments":'
                '{"user_id":"1351879409832951893"}}}'
            ),
            "kick_user(user_id='1351879409832951893')",
            "action = kick_user(user_id='1351879409832951893')",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                calls = _extract_textual_tool_calls(
                    sample,
                    frozenset({"kick_user"}),
                    allow_bare=True,
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["function"]["name"], "kick_user")
                self.assertEqual(
                    json.loads(calls[0]["function"]["arguments"])["user_id"],
                    "1351879409832951893",
                )

        self.assertEqual(
            _extract_textual_tool_calls(
                "kick_user(user_id='1351879409832951893')",
                frozenset({"kick_user"}),
            ),
            [],
        )

    async def test_only_intended_schema_is_exposed_and_duplicate_call_is_skipped(self):
        tool_call = {
            "id": "call-1",
            "function": {
                "name": "ban_user",
                "arguments": json.dumps({"user_id": "123", "reason": "spam"}),
            },
        }
        response = {"role": "assistant", "tool_calls": [tool_call, dict(tool_call)]}
        message = SimpleNamespace(
            content="P.OS, забань пользователя test за спам",
            author=SimpleNamespace(id=968698192411652176),
        )
        state = {"tools_executed": False}

        chat = AsyncMock(return_value=response)
        execute = AsyncMock(return_value="Пользователь забанен.")
        with patch("pos_ai.pos_chat_completion", new=chat), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [], state=state)

        schemas = chat.await_args.kwargs["tools"]
        self.assertEqual([schema["function"]["name"] for schema in schemas], ["ban_user"])
        self.assertEqual(chat.await_args.kwargs["tool_choice"], "required")
        self.assertEqual(chat.await_count, 1)
        self.assertEqual(execute.await_count, 1)
        self.assertTrue(state["tools_executed"])
        self.assertIn("Повторный идентичный вызов пропущен", result)

    async def test_non_owner_gets_only_mutating_schema_for_owner_approval(self):
        tool_call = {
            "id": "call-approval",
            "function": {
                "name": "ban_user",
                "arguments": json.dumps({"user_identifier": "test", "reason": "request"}),
            },
        }
        message = SimpleNamespace(
            content="P.OS, забань пользователя test",
            author=SimpleNamespace(id=123),
        )
        chat = AsyncMock(return_value={"role": "assistant", "tool_calls": [tool_call]})
        execute = AsyncMock(return_value="Запрос отправлен Пумбе на подтверждение.")

        with patch("pos_ai.pos_chat_completion", new=chat), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [])

        self.assertEqual(result, "Запрос отправлен Пумбе на подтверждение.")
        schemas = chat.await_args.kwargs["tools"]
        self.assertEqual([schema["function"]["name"] for schema in schemas], ["ban_user"])
        self.assertEqual(chat.await_args.kwargs["tool_choice"], "required")

    async def test_non_owner_cannot_create_ignore_request_or_owner_dm(self):
        target_id = 1351879409832951893
        message = SimpleNamespace(
            content=f"P.OS, не отвечай пользователю <@{target_id}>",
            author=SimpleNamespace(id=111111111111111111),
            guild=SimpleNamespace(id=1352394387362939003),
        )
        tool_call = {
            "function": {
                "name": "mute_ai_for_user",
                "arguments": json.dumps({"user_id": str(target_id)}),
            }
        }
        creator_lookup = AsyncMock()

        with patch("pos_ai._get_creator_user", new=creator_lookup):
            result = await execute_pos_tool(
                SimpleNamespace(),
                message,
                tool_call,
                allowed_tool_names=frozenset({"mute_ai_for_user"}),
            )

        self.assertIn("только Пумба", result)
        creator_lookup.assert_not_awaited()

    async def test_unstructured_action_response_is_retried_then_rejected_truthfully(self):
        message = SimpleNamespace(
            content="P.OS, кикни пользователя test",
            author=SimpleNamespace(id=968698192411652176),
        )
        chat = AsyncMock(
            side_effect=[
                {"role": "assistant", "content": "Принято. Запускаю p.kick test"},
                {"role": "assistant", "content": "Выполняю команду p.kick test"},
            ]
        )
        execute = AsyncMock()

        with patch("pos_ai.pos_chat_completion", new=chat), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [])

        self.assertIn("Никакая команда не запускалась", result)
        self.assertNotIn("p.kick", result)
        self.assertEqual(chat.await_count, 2)
        self.assertTrue(all(
            await_call.kwargs["tool_choice"] == "required"
            for await_call in chat.await_args_list
        ))
        execute.assert_not_awaited()

    async def test_unstructured_ban_with_verified_mention_uses_real_fallback_call(self):
        target_id = 1351879409832951893
        guild = SimpleNamespace(id=1)
        message = SimpleNamespace(
            id=77,
            content=f"P.OS, забань <@{target_id}>",
            author=SimpleNamespace(id=968698192411652176),
            guild=guild,
            channel=SimpleNamespace(id=10),
            mentions=[SimpleNamespace(id=target_id)],
            raw_mentions=[target_id],
            role_mentions=[],
            channel_mentions=[],
            reference=None,
        )
        chat = AsyncMock(
            side_effect=[
                {"role": "assistant", "content": "Сейчас забаню."},
                {"role": "assistant", "content": "Выполняю инструмент."},
            ]
        )
        execute = AsyncMock(return_value=f"Пользователь {target_id} успешно забанен.")
        state = {"tools_executed": False}

        with patch("pos_ai.pos_chat_completion", new=chat), patch(
            "pos_ai.execute_pos_tool",
            new=execute,
        ):
            result = await request_pos_reply(SimpleNamespace(user=SimpleNamespace(id=999)), message, [], state=state)

        self.assertIn("успешно забанен", result)
        self.assertTrue(state["tools_executed"])
        execute.assert_awaited_once()
        fallback_call = execute.await_args.args[2]
        fallback_args = json.loads(fallback_call["function"]["arguments"])
        self.assertEqual(fallback_call["function"]["name"], "ban_user")
        self.assertEqual(fallback_args["user_id"], str(target_id))
        self.assertEqual(fallback_args["reason"], "По распоряжению Пумбы")

    async def test_simulated_action_is_rejected_without_calling_model(self):
        message = SimpleNamespace(
            content=(
                "P.OS, создай роль POS-SIMULATION-NO-EXEC, "
                "но только напиши команду и ничего не выполняй"
            ),
            author=SimpleNamespace(id=968698192411652176),
        )
        chat = AsyncMock()
        execute = AsyncMock()

        with patch("pos_ai.pos_chat_completion", new=chat), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [])

        self.assertIn("Ничего не выполнял", result)
        self.assertNotIn("инструмент", result.lower())
        self.assertNotIn("tool", result.lower())
        chat.assert_not_awaited()
        execute.assert_not_awaited()

    async def test_json_tool_envelope_from_provider_is_executed(self):
        response = {
            "role": "assistant",
            "content": (
                "tool_call:\n```json\n"
                '{"name":"kick_user","arguments":{"user_id":"1351879409832951893",'
                '"reason":"По приказу владельца"}}\n```'
            ),
        }
        message = SimpleNamespace(
            content="кикни бота джунипера с сервера",
            author=SimpleNamespace(id=968698192411652176),
        )
        execute = AsyncMock(return_value="JuniperBot кикнут с сервера.")

        with patch("pos_ai.pos_chat_completion", new=AsyncMock(return_value=response)), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [])

        self.assertEqual(result, "JuniperBot кикнут с сервера.")
        execute.assert_awaited_once()

    async def test_malformed_native_tool_call_is_safely_rejected(self):
        response = {
            "role": "assistant",
            "tool_calls": [{"id": "broken", "function": "not-an-object"}],
        }
        message = SimpleNamespace(
            content="P.OS, кикни пользователя test",
            author=SimpleNamespace(id=968698192411652176),
        )
        execute = AsyncMock(return_value="Отказано: получена неизвестная управляющая операция.")

        with patch("pos_ai.pos_chat_completion", new=AsyncMock(return_value=response)), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [])

        self.assertEqual(result, "Отказано: получена неизвестная управляющая операция.")
        normalized_call = execute.await_args.args[2]
        self.assertEqual(normalized_call["function"]["name"], "")
        self.assertEqual(normalized_call["function"]["arguments"], "{}")

    async def test_textual_tool_call_from_provider_is_executed(self):
        response = {
            "role": "assistant",
            "content": (
                "Принято. Выполняю устранение JuniperBot (`1351879409832951893`) с сервера.\n\n"
                "tool_call: kick_user(user_id='1351879409832951893', "
                "reason='По приказу владельца')"
            ),
        }
        message = SimpleNamespace(
            content="кикни бота джунипера с сервера",
            author=SimpleNamespace(id=968698192411652176),
        )
        state = {"tools_executed": False}
        chat = AsyncMock(return_value=response)
        execute = AsyncMock(return_value="JuniperBot кикнут с сервера.")

        with patch("pos_ai.pos_chat_completion", new=chat), \
             patch("pos_ai.execute_pos_tool", new=execute):
            result = await request_pos_reply(SimpleNamespace(), message, [], state=state)

        self.assertEqual(result, "JuniperBot кикнут с сервера.")
        self.assertTrue(state["tools_executed"])
        call = execute.await_args.args[2]
        self.assertEqual(call["function"]["name"], "kick_user")
        self.assertEqual(
            json.loads(call["function"]["arguments"])["user_id"],
            "1351879409832951893",
        )

    async def test_reported_kick_phrase_executes_assigned_provider_call(self):
        target_id = 1351879409832951893
        response = {
            "role": "assistant",
            "content": f"action = kick_user(user_id='{target_id}')",
        }
        message = SimpleNamespace(
            content=f"P.OS, выкинь с сервера <@{target_id}>",
            author=SimpleNamespace(id=968698192411652176),
        )
        execute = AsyncMock(return_value=f"Пользователь {target_id} кикнут с сервера.")

        with patch("pos_ai.pos_chat_completion", new=AsyncMock(return_value=response)), patch(
            "pos_ai.execute_pos_tool",
            new=execute,
        ):
            result = await request_pos_reply(SimpleNamespace(), message, [])

        self.assertIn("кикнут с сервера", result)
        execute.assert_awaited_once()
        call = execute.await_args.args[2]
        self.assertEqual(call["function"]["name"], "kick_user")


class PlainReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_login_becomes_one_safe_real_user_mention(self):
        member = SimpleNamespace(id=1351879409832951893, name="juniperbot")
        guild = SimpleNamespace(
            members=[member],
            get_member=lambda user_id: member if user_id == member.id else None,
        )
        normalized = _normalize_reply_user_mentions("Позвал @juniperbot, но не @everyone.", guild)
        self.assertIn(f"<@{member.id}>", normalized)
        self.assertIn("@everyone", normalized)

        allowed = _allowed_user_mentions_for_text(normalized, guild)
        self.assertEqual(allowed.to_dict(), {"users": [member.id], "parse": []})

    async def test_model_decorated_mentions_become_one_real_ping_without_raw_id(self):
        member = SimpleNamespace(
            id=1351879409832951893,
            name="juniperbot",
            display_name="Juniper Bot",
            global_name="Juniper Bot",
        )
        guild = SimpleNamespace(
            members=[member],
            get_member=lambda user_id: member if user_id == member.id else None,
        )
        samples = (
            f"Позови @Juniper Bot(ID:{member.id}).",
            f"Позови @(Juniper Bot) ID: {member.id}.",
            f"Позови @juniperbot {member.id}.",
            "Позови @(Juniper Bot).",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                normalized = _normalize_reply_user_mentions(sample, guild)
                self.assertEqual(normalized.count(f"<@{member.id}>"), 1)
                self.assertNotIn(str(member.id), normalized.replace(f"<@{member.id}>", ""))

    async def test_mismatched_decorated_name_does_not_ping_id(self):
        member = SimpleNamespace(
            id=1351879409832951893,
            name="juniperbot",
            display_name="Juniper Bot",
            global_name="Juniper Bot",
        )
        guild = SimpleNamespace(
            members=[member],
            get_member=lambda user_id: member if user_id == member.id else None,
        )
        raw = f"@(Другой человек) ID: {member.id}"
        self.assertEqual(_normalize_reply_user_mentions(raw, guild), raw)

    async def test_normal_response_sends_text_without_embed(self):
        member = SimpleNamespace(id=1351879409832951893, name="juniperbot")
        guild = SimpleNamespace(
            members=[member],
            get_member=lambda user_id: member if user_id == member.id else None,
        )
        message = SimpleNamespace(
            guild=guild,
            reply=AsyncMock(),
            channel=SimpleNamespace(send=AsyncMock()),
        )

        sent = await _send_plain_response(message, "Готово, @juniperbot уведомлён.")

        self.assertTrue(sent)
        message.reply.assert_awaited_once()
        args, kwargs = message.reply.await_args
        self.assertIn(f"<@{member.id}>", args[0])
        self.assertNotIn("embed", kwargs)
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"users": [member.id], "parse": []})


class CurrentMessageTargetTests(unittest.TestCase):
    def test_bot_mention_after_action_is_a_protected_target_not_silently_dropped(self):
        bot_id = 1393592093137440838
        bot = SimpleNamespace(user=SimpleNamespace(id=bot_id))
        target = SimpleNamespace(id=bot_id)
        message = SimpleNamespace(
            content=f"P.OS, выкинь с сервера <@{bot_id}>",
            guild=SimpleNamespace(id=1352394387362939003),
            channel=SimpleNamespace(id=1352394388449267897),
            mentions=[target],
            raw_mentions=[bot_id],
            reference=None,
        )
        self.assertEqual(_message_target_user_id(message, bot), bot_id)

    def test_leading_bot_mention_is_only_the_addressee(self):
        bot_id = 1393592093137440838
        bot = SimpleNamespace(user=SimpleNamespace(id=bot_id))
        message = SimpleNamespace(
            content=f"<@{bot_id}> покажи роли",
            guild=SimpleNamespace(id=1352394387362939003),
            channel=SimpleNamespace(id=1352394388449267897),
            mentions=[SimpleNamespace(id=bot_id)],
            raw_mentions=[bot_id],
            reference=None,
        )
        self.assertIsNone(_message_target_user_id(message, bot))

class RestoreFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await close_all_connections()

    async def test_skips_corrupt_newest_backup_and_restores_older_valid_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source.db")
            target_path = os.path.join(tmp, "target.db")
            connection = sqlite3.connect(source_path)
            connection.execute("CREATE TABLE sentinel (value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES ('restored')")
            connection.commit()
            connection.close()
            with open(source_path, "rb") as source:
                valid_raw = source.read()

            class Attachment:
                def __init__(self, raw):
                    self.filename = "bot_data.db"
                    self.size = len(raw)
                    self._raw = raw

                async def read(self):
                    return self._raw

            author = SimpleNamespace(id=42)
            corrupt_raw = b"SQLite format 3\x00" + (b"broken" * 20)
            messages = [
                SimpleNamespace(
                    id=2,
                    author=author,
                    content="[DATABASE_BACKUP] sha256=" + hashlib.sha256(corrupt_raw).hexdigest(),
                    attachments=[Attachment(corrupt_raw)],
                ),
                SimpleNamespace(
                    id=1,
                    author=author,
                    content="[DATABASE_BACKUP] sha256=" + hashlib.sha256(valid_raw).hexdigest(),
                    attachments=[Attachment(valid_raw)],
                ),
            ]

            class Channel:
                def history(self, limit=50):
                    async def generate():
                        for message in messages:
                            yield message
                    return generate()

            bot = SimpleNamespace(user=author)
            with patch("storage.BACKUP_CHANNEL_ID", 123), \
                 patch("storage._resolve_backup_channel", new=AsyncMock(return_value=Channel())):
                restored = await restore_db_from_discord(bot, target_path)

            self.assertTrue(restored)
            restored_db = sqlite3.connect(target_path)
            try:
                value = restored_db.execute("SELECT value FROM sentinel").fetchone()[0]
            finally:
                restored_db.close()
            self.assertEqual(value, "restored")

    async def test_restores_new_gzip_backup_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source.db")
            target_path = os.path.join(tmp, "target.db")
            connection = sqlite3.connect(source_path)
            connection.execute("CREATE TABLE sentinel (value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES ('gzip-restored')")
            connection.commit()
            connection.close()
            with open(source_path, "rb") as source:
                valid_raw = source.read()
            compressed = gzip.compress(valid_raw, mtime=0)

            class Attachment:
                filename = "bot_data.db.gz"
                size = len(compressed)

                async def read(self):
                    return compressed

            author = SimpleNamespace(id=42)
            message = SimpleNamespace(
                id=3,
                author=author,
                content=(
                    "[DATABASE_BACKUP] encoding=gzip sha256="
                    + hashlib.sha256(compressed).hexdigest()
                ),
                attachments=[Attachment()],
            )

            class Channel:
                def history(self, limit=50):
                    async def generate():
                        yield message

                    return generate()

            bot = SimpleNamespace(user=author)
            with patch("storage.BACKUP_CHANNEL_ID", 123), patch(
                "storage._resolve_backup_channel",
                new=AsyncMock(return_value=Channel()),
            ):
                restored = await restore_db_from_discord(bot, target_path)

            self.assertTrue(restored)
            restored_db = sqlite3.connect(target_path)
            try:
                value = restored_db.execute("SELECT value FROM sentinel").fetchone()[0]
            finally:
                restored_db.close()
            self.assertEqual(value, "gzip-restored")

    def test_gzip_restore_rejects_decompression_bomb(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_path = os.path.join(tmp, "expanded.db")
            compressed = gzip.compress(b"x" * 1024, mtime=0)
            with patch.object(storage, "_MAX_BACKUP_BYTES", 128):
                with self.assertRaisesRegex(ValueError, "decompressed database"):
                    storage._write_restore_payload(
                        target_path,
                        compressed,
                        compressed=True,
                    )


class BackupConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_backup_channel_warns_only_once(self):
        bot = SimpleNamespace()
        with patch.object(storage, "BACKUP_CHANNEL_ID", 0), patch.object(
            storage,
            "_backup_disabled_warning_emitted",
            False,
        ), patch.object(storage.logger, "warning") as warning:
            self.assertFalse(await storage.backup_db_to_discord(bot))
            self.assertFalse(await storage.backup_db_to_discord(bot))
            self.assertFalse(await storage.restore_db_from_discord(bot))

        warning.assert_called_once()
        self.assertIn("DB_BACKUP_CHANNEL_ID", warning.call_args.args[0])


class LoggingRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_update_reads_discord_py_slowmode_attribute(self):
        guild = SimpleNamespace(id=7)

        class FakeTextChannel:
            def __init__(self, slowmode_delay):
                self.id = 70
                self.guild = guild
                self.name = "general"
                self.mention = "<#70>"
                self.category_id = None
                self.category = None
                self.topic = None
                self.nsfw = False
                self.slowmode_delay = slowmode_delay
                self.overwrites = {}
                self.position = 1

        before = FakeTextChannel(0)
        after = FakeTextChannel(5)
        append_audit = AsyncMock()
        send_log = AsyncMock()

        with patch.object(logging_events.discord, "TextChannel", FakeTextChannel), patch.object(
            logging_events,
            "_append_audit_fields",
            append_audit,
        ), patch.object(logging_events, "send_log_embed", send_log):
            cog = logging_events.LoggingCog(SimpleNamespace())
            await cog.on_guild_channel_update(before, after)

        append_audit.assert_awaited_once()
        send_log.assert_awaited_once()
        self.assertIn(
            ("Slowmode", "0s → 5s", True),
            send_log.await_args.kwargs["fields"],
        )


if __name__ == "__main__":
    unittest.main()
