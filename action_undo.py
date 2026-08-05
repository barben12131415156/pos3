"""Deterministic action snapshots and contextual undo for P.OS tools."""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Mapping

import discord

from config import POS_CREATOR_ID
from storage import (
    claim_recent_pos_action_group,
    delete_entry,
    finish_pos_action_undo,
    is_ai_muted,
    set_ai_muted_user,
)
from vacation_mode import (
    is_owner_vacation_mode_enabled,
    set_owner_vacation_mode,
)


logger = logging.getLogger(__name__)


def target_guild(
    bot: discord.Client,
    message: discord.Message,
    args: Mapping[str, Any],
) -> discord.Guild | None:
    raw = str(args.get("server_id_or_name") or "").strip()
    if raw:
        digits = re.sub(r"[^0-9]", "", raw)
        if not digits:
            return None
        getter = getattr(bot, "get_guild", None)
        if callable(getter):
            resolved = getter(int(digits))
            if resolved is not None:
                return resolved
        source_guild = getattr(message, "guild", None)
        return source_guild if getattr(source_guild, "id", None) == int(digits) else None
    return message.guild


async def _member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


def action_succeeded(result: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(result or "")).strip().casefold()
    if not normalized:
        return False
    return not normalized.startswith(
        (
            "ошибка:",
            "отказано:",
            "действие не ",
            "не удалось",
            "запрос не ",
            "сообщение не отправлено",
            "канал связи с пумбой",
            "предыдущий запрос",
            "дневной лимит",
            "сначала дождись",
        )
    )


def _result_snowflake(result: str) -> int | None:
    matches = re.findall(r"(?<!\d)(\d{15,22})(?!\d)", str(result or ""))
    return int(matches[-1]) if matches else None


def _channel_state(channel: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "channel_id": int(getattr(channel, "id", 0) or 0),
        "name": str(getattr(channel, "name", ""))[:100],
        "category_id": getattr(channel, "category_id", None),
        "position": int(getattr(channel, "position", 0) or 0),
    }
    for attribute in ("topic", "slowmode_delay", "nsfw"):
        if hasattr(channel, attribute):
            state[attribute] = getattr(channel, attribute)
    return state


def _reaction_matches(reaction: discord.Reaction, raw_emoji: str) -> bool:
    wanted = str(raw_emoji or "").strip()
    if not wanted:
        return False
    digits = re.findall(r"(?<!\d)(\d{15,22})(?!\d)", wanted)
    reaction_id = getattr(reaction.emoji, "id", None)
    if digits and reaction_id is not None:
        return int(digits[-1]) == int(reaction_id)
    reaction_name = str(getattr(reaction.emoji, "name", reaction.emoji))
    return wanted == str(reaction.emoji) or wanted.casefold() == reaction_name.casefold()


async def capture_pre_state(
    bot: discord.Client,
    message: discord.Message,
    name: str,
    args: Mapping[str, Any],
    user_id: int | None,
) -> dict[str, Any]:
    """Capture only verified fields required by an inverse operation."""
    guild = target_guild(bot, message, args)
    if guild is None:
        return {}
    state: dict[str, Any] = {"target_guild_id": guild.id}
    target_member = await _member(guild, user_id) if user_id else None

    if name in {"enable_vacation_mode", "disable_vacation_mode"}:
        state["vacation_mode_enabled"] = await is_owner_vacation_mode_enabled()

    if name in {"timeout_user", "untimeout_user"} and target_member is not None:
        until = getattr(target_member, "timed_out_until", None)
        state["timed_out_until"] = until.isoformat() if until else ""
    elif name == "set_nickname" and target_member is not None:
        state["nickname"] = target_member.nick
    elif name in {"add_role", "remove_role"} and target_member is not None:
        role_id = int(re.sub(r"[^0-9]", "", str(args.get("role_id_or_name") or "0")) or 0)
        role = guild.get_role(role_id)
        if role is not None:
            state.update(role_id=role.id, had_role=role in target_member.roles)
    elif name == "unban_user" and user_id:
        try:
            entry = await guild.fetch_ban(discord.Object(id=user_id))
            state["ban_reason"] = str(entry.reason or "")[:512]
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    elif name == "kick_user" and target_member is not None:
        state["target_was_bot"] = target_member.bot
    elif name in {"mute_ai_for_user", "unmute_ai_for_user"} and user_id:
        state["ai_muted"] = await is_ai_muted(user_id, guild.id)

    if name == "edit_role":
        role_id = int(re.sub(r"[^0-9]", "", str(args.get("role_id_or_name") or "0")) or 0)
        role = guild.get_role(role_id)
        if role is not None:
            state["role"] = {
                "role_id": role.id,
                "name": role.name,
                "colour": role.colour.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "permissions": role.permissions.value,
                "position": role.position,
            }
    elif name == "edit_channel":
        channel_id = int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0)
        channel = guild.get_channel_or_thread(channel_id)
        if channel is not None:
            state["channel"] = _channel_state(channel)
    elif name in {"set_channel_permission", "lock_channel", "unlock_channel"}:
        channel_id = int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0)
        target_id = int(re.sub(r"[^0-9]", "", str(args.get("target_role_or_user") or "0")) or 0)
        channel = guild.get_channel(channel_id)
        permission_target: discord.Role | discord.Member | None = guild.get_role(target_id)
        if permission_target is None:
            permission_target = await _member(guild, target_id)
        if isinstance(channel, discord.abc.GuildChannel) and permission_target is not None:
            overwrite = channel.overwrites_for(permission_target)
            allow, deny = overwrite.pair()
            state["permission"] = {
                "channel_id": channel.id,
                "target_id": permission_target.id,
                "target_kind": "role" if isinstance(permission_target, discord.Role) else "member",
                "had_overwrite": any(item.id == permission_target.id for item in channel.overwrites),
                "allow": allow.value,
                "deny": deny.value,
            }
    elif name == "edit_server":
        state["guild"] = {
            "name": guild.name,
            "description": getattr(guild, "description", None),
            "verification_level": getattr(guild.verification_level, "value", None),
            "explicit_content_filter": getattr(guild.explicit_content_filter, "value", None),
            "default_notifications": getattr(guild.default_notifications, "value", None),
        }
    elif name == "archive_thread":
        channel_id = int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0)
        thread = guild.get_thread(channel_id)
        if thread is not None:
            state["thread"] = {
                "channel_id": thread.id,
                "archived": thread.archived,
                "locked": thread.locked,
            }
    elif name == "manage_message":
        channel_id = int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0)
        message_id = int(re.sub(r"[^0-9]", "", str(args.get("message_id") or "0")) or 0)
        channel = guild.get_channel_or_thread(channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)) and message_id:
            try:
                target_message = await channel.fetch_message(message_id)
                state["message"] = {
                    "channel_id": channel.id,
                    "message_id": target_message.id,
                    "content": target_message.content[:2000],
                    "pinned": target_message.pinned,
                    "author_id": target_message.author.id,
                }
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
    elif name == "manage_reaction":
        channel_id = int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0)
        message_id = int(re.sub(r"[^0-9]", "", str(args.get("message_id") or "0")) or 0)
        channel = guild.get_channel_or_thread(channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)) and message_id:
            try:
                target_message = await channel.fetch_message(message_id)
                matching = next(
                    (
                        reaction
                        for reaction in target_message.reactions
                        if _reaction_matches(reaction, str(args.get("emoji") or ""))
                    ),
                    None,
                )
                state["pos_had_reaction"] = bool(matching and matching.me)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
    return state


def derive_inverse(
    name: str,
    args: Mapping[str, Any],
    user_id: int | None,
    result: str,
    pre_state: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    try:
        guild_id = int(pre_state.get("target_guild_id") or args.get("server_id_or_name") or 0)
    except (TypeError, ValueError):
        guild_id = 0
    base = {"target_guild_id": guild_id}
    if name == "ban_user" and user_id:
        return "unban_user", {**base, "user_id": user_id}
    if name == "unban_user" and user_id:
        return "ban_user", {
            **base,
            "user_id": user_id,
            "reason": pre_state.get("ban_reason") or "Восстановление отменённого бана P.OS",
        }
    if name == "kick_user" and user_id:
        return "restore_kick_user", {
            **base,
            "user_id": user_id,
            "target_was_bot": bool(pre_state.get("target_was_bot")),
        }
    if name in {"timeout_user", "untimeout_user"} and user_id:
        return "restore_timeout_user", {
            **base,
            "user_id": user_id,
            "until": str(pre_state.get("timed_out_until") or ""),
        }
    if name == "set_nickname" and user_id:
        return "restore_nickname", {
            **base,
            "user_id": user_id,
            "nickname": pre_state.get("nickname"),
        }
    if name == "add_role" and user_id and pre_state.get("role_id") and not pre_state.get("had_role"):
        return "remove_role", {**base, "user_id": user_id, "role_id": pre_state["role_id"]}
    if name == "remove_role" and user_id and pre_state.get("role_id") and pre_state.get("had_role"):
        return "add_role", {**base, "user_id": user_id, "role_id": pre_state["role_id"]}
    if name in {"mute_ai_for_user", "unmute_ai_for_user"} and user_id:
        return "restore_ai_mute", {
            **base,
            "user_id": user_id,
            "muted": bool(pre_state.get("ai_muted")),
        }
    if (
        name in {"enable_vacation_mode", "disable_vacation_mode"}
        and "vacation_mode_enabled" in pre_state
    ):
        return "restore_vacation_mode", {
            **base,
            "enabled": bool(pre_state["vacation_mode_enabled"]),
        }

    created_id = _result_snowflake(result)
    if name == "create_role" and created_id:
        return "delete_role", {**base, "role_id": created_id}
    if name in {"create_channel", "create_thread", "create_forum_post"} and created_id:
        return "delete_channel", {**base, "channel_id": created_id}
    if name == "edit_role" and isinstance(pre_state.get("role"), dict):
        return "restore_role", {**base, **pre_state["role"]}
    if name == "edit_channel" and isinstance(pre_state.get("channel"), dict):
        return "restore_channel", {**base, **pre_state["channel"]}
    if name in {"set_channel_permission", "lock_channel", "unlock_channel"} and isinstance(pre_state.get("permission"), dict):
        return "restore_channel_permission", {**base, **pre_state["permission"]}
    if name == "edit_server" and isinstance(pre_state.get("guild"), dict):
        return "restore_guild", {**base, **pre_state["guild"]}
    if name == "archive_thread" and isinstance(pre_state.get("thread"), dict):
        return "restore_thread", {**base, **pre_state["thread"]}
    if name == "create_invite":
        match = re.search(r"https?://(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/([^\s)]+)", result)
        if match:
            return "revoke_invite", {**base, "code": match.group(1)}
    if name in {"send_message", "ping_user", "send_poll"} and created_id:
        channel_id = int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0)
        if channel_id:
            return "delete_message", {**base, "channel_id": channel_id, "message_id": created_id}
    if name == "manage_message" and isinstance(pre_state.get("message"), dict):
        if str(args.get("action") or "").casefold() in {"edit", "pin", "unpin"}:
            return "restore_message", {**base, **pre_state["message"]}
    if name == "manage_reaction" and str(args.get("action") or "").casefold() in {"add", "remove_pos"}:
        action = str(args.get("action") or "").casefold()
        had_reaction = bool(pre_state.get("pos_had_reaction"))
        if (action == "add" and had_reaction) or (action == "remove_pos" and not had_reaction):
            return None, None
        return "restore_reaction", {
            **base,
            "channel_id": int(re.sub(r"[^0-9]", "", str(args.get("channel_id_or_name") or "0")) or 0),
            "message_id": int(re.sub(r"[^0-9]", "", str(args.get("message_id") or "0")) or 0),
            "emoji": str(args.get("emoji") or ""),
            "should_exist": had_reaction,
        }
    if name == "remember_fact":
        match = re.search(r"ID:\s*`?(\d+)", result)
        if match:
            return "delete_memory_entry", {**base, "entry_id": int(match.group(1))}
    if name == "manage_automod_rule" and str(args.get("action") or "").startswith("create_") and created_id:
        return "delete_automod_rule", {**base, "rule_id": created_id}
    if name == "manage_scheduled_event" and str(args.get("action") or "").casefold() == "create" and created_id:
        return "delete_scheduled_event", {**base, "event_id": created_id}
    if name == "manage_emoji" and str(args.get("action") or "").casefold() == "create" and created_id:
        return "delete_emoji", {**base, "emoji_id": created_id}
    if name == "manage_sticker" and str(args.get("action") or "").casefold() == "create" and created_id:
        return "delete_sticker", {**base, "sticker_id": created_id}
    return None, None


async def _invite_channel(
    guild: discord.Guild,
    preferred_channel_id: int | None,
) -> discord.TextChannel | discord.VoiceChannel | None:
    candidates: list[discord.TextChannel | discord.VoiceChannel] = []
    if preferred_channel_id:
        preferred = guild.get_channel(preferred_channel_id)
        if isinstance(preferred, (discord.TextChannel, discord.VoiceChannel)):
            candidates.append(preferred)
    candidates.extend(guild.text_channels)
    candidates.extend(guild.voice_channels)
    seen: set[int] = set()
    for channel in candidates:
        if channel.id in seen:
            continue
        seen.add(channel.id)
        permissions = channel.permissions_for(guild.me) if guild.me else None
        if permissions and permissions.create_instant_invite:
            return channel
    return None


async def undo_exact_action(
    bot: discord.Client,
    action: Mapping[str, Any],
) -> tuple[bool, str]:
    operation = str(action.get("inverse_operation") or "")
    raw_inverse_args = action.get("inverse_args")
    args: Mapping[str, Any] = raw_inverse_args if isinstance(raw_inverse_args, dict) else {}
    guild_id = int(args.get("target_guild_id") or action.get("target_guild_id") or 0)
    guild = bot.get_guild(guild_id)
    if guild is None:
        return False, "целевой сервер больше недоступен P.OS"
    reason = "Откат подтверждённого действия P.OS"
    user_id = int(args.get("user_id") or 0)
    try:
        if operation == "unban_user":
            try:
                await guild.unban(discord.Object(id=user_id), reason=reason)
            except discord.NotFound:
                pass
            return True, "бан снят"
        if operation == "ban_user":
            await guild.ban(discord.Object(id=user_id), reason=str(args.get("reason") or reason)[:512])
            return True, "бан восстановлен"
        if operation == "restore_timeout_user":
            target = await _member(guild, user_id)
            if target is None:
                return False, "участник не находится на сервере"
            raw_until = str(args.get("until") or "")
            until = datetime.datetime.fromisoformat(raw_until) if raw_until else None
            if until is not None and until.tzinfo is None:
                until = until.replace(tzinfo=datetime.timezone.utc)
            if until is not None and until <= discord.utils.utcnow():
                until = None
            await target.timeout(until, reason=reason)
            return True, "прежнее состояние тайм-аута восстановлено"
        if operation == "restore_nickname":
            target = await _member(guild, user_id)
            if target is None:
                return False, "участник не находится на сервере"
            await target.edit(nick=args.get("nickname"), reason=reason)
            return True, "прежний никнейм восстановлен"
        if operation in {"add_role", "remove_role"}:
            target = await _member(guild, user_id)
            role = guild.get_role(int(args.get("role_id") or 0))
            if target is None or role is None:
                return False, "участник или роль больше недоступны"
            if operation == "add_role":
                await target.add_roles(role, reason=reason)
            else:
                await target.remove_roles(role, reason=reason)
            return True, "состав ролей восстановлен"
        if operation == "restore_ai_mute":
            await set_ai_muted_user(user_id, guild.id, bool(args.get("muted")))
            return True, "состояние игнорирования восстановлено"
        if operation == "restore_vacation_mode":
            enabled = bool(args.get("enabled"))
            await set_owner_vacation_mode(enabled, actor_id=POS_CREATOR_ID)
            return True, (
                "режим отпуска снова включён"
                if enabled
                else "режим отпуска снова выключен"
            )
        if operation == "delete_role":
            role = guild.get_role(int(args.get("role_id") or 0))
            if role is not None:
                await role.delete(reason=reason)
            return True, "созданная роль удалена"
        if operation == "delete_channel":
            channel = guild.get_channel_or_thread(int(args.get("channel_id") or 0))
            if channel is not None:
                await channel.delete(reason=reason)
            return True, "созданный канал или ветка удалены"
        if operation == "restore_role":
            role = guild.get_role(int(args.get("role_id") or 0))
            if role is None:
                return False, "роль больше не существует"
            await role.edit(
                name=str(args.get("name") or role.name)[:100],
                colour=discord.Colour(int(args.get("colour") or 0)),
                hoist=bool(args.get("hoist")),
                mentionable=bool(args.get("mentionable")),
                permissions=discord.Permissions(int(args.get("permissions") or 0)),
                position=int(args.get("position") or role.position),
                reason=reason,
            )
            return True, "параметры роли восстановлены"
        if operation == "restore_channel":
            channel = guild.get_channel_or_thread(int(args.get("channel_id") or 0))
            if channel is None:
                return False, "канал больше не существует"
            channel_kwargs: dict[str, Any] = {"name": str(args.get("name") or channel.name)[:100]}
            if hasattr(channel, "topic"):
                channel_kwargs["topic"] = args.get("topic")
            if hasattr(channel, "slowmode_delay"):
                channel_kwargs["slowmode_delay"] = int(args.get("slowmode_delay") or 0)
            if hasattr(channel, "nsfw"):
                channel_kwargs["nsfw"] = bool(args.get("nsfw"))
            if not isinstance(channel, discord.Thread):
                channel_kwargs["position"] = max(0, int(args.get("position") or 0))
            if not isinstance(channel, (discord.Thread, discord.CategoryChannel)):
                category_id = args.get("category_id")
                channel_kwargs["category"] = guild.get_channel(int(category_id)) if category_id else None
            await channel.edit(reason=reason, **channel_kwargs)
            return True, "параметры канала восстановлены"
        if operation == "restore_channel_permission":
            channel = guild.get_channel(int(args.get("channel_id") or 0))
            if not isinstance(channel, discord.abc.GuildChannel):
                return False, "канал больше не существует"
            target_id = int(args.get("target_id") or 0)
            permission_target: discord.Role | discord.Member | None = (
                guild.get_role(target_id) if args.get("target_kind") == "role" else await _member(guild, target_id)
            )
            if permission_target is None:
                return False, "цель прав больше недоступна"
            overwrite = None
            if args.get("had_overwrite"):
                overwrite = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(int(args.get("allow") or 0)),
                    discord.Permissions(int(args.get("deny") or 0)),
                )
            await channel.set_permissions(permission_target, overwrite=overwrite, reason=reason)
            return True, "прежние права канала восстановлены"
        if operation == "restore_guild":
            guild_kwargs: dict[str, Any] = {
                "name": str(args.get("name") or guild.name)[:100],
                "description": args.get("description"),
            }
            for key, enum_type in (
                ("verification_level", discord.VerificationLevel),
                ("explicit_content_filter", discord.ContentFilter),
                ("default_notifications", discord.NotificationLevel),
            ):
                raw = args.get(key)
                if raw is not None:
                    value = next((item for item in enum_type if item.value == raw), None)
                    if value is not None:
                        guild_kwargs[key] = value
            await guild.edit(reason=reason, **guild_kwargs)
            return True, "прежние параметры сервера восстановлены"
        if operation == "restore_thread":
            thread = guild.get_thread(int(args.get("channel_id") or 0))
            if thread is None:
                return False, "ветка больше не существует"
            await thread.edit(
                archived=bool(args.get("archived")),
                locked=bool(args.get("locked")),
                reason=reason,
            )
            return True, "состояние ветки восстановлено"
        if operation == "revoke_invite":
            invite = next((item for item in await guild.invites() if item.code == str(args.get("code") or "")), None)
            if invite is not None:
                await invite.delete(reason=reason)
            return True, "созданное приглашение отозвано"
        if operation in {"delete_message", "restore_message", "restore_reaction"}:
            channel = guild.get_channel_or_thread(int(args.get("channel_id") or 0))
            if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
                return False, "канал сообщения недоступен"
            try:
                target_message = await channel.fetch_message(int(args.get("message_id") or 0))
            except discord.NotFound:
                target_message = None
            if operation == "delete_message":
                if target_message is not None:
                    await target_message.delete()
                return True, "отправленное P.OS сообщение удалено"
            if target_message is None:
                return False, "сообщение больше не существует"
            if operation == "restore_message":
                if int(args.get("author_id") or 0) == getattr(getattr(bot, "user", None), "id", 0):
                    await target_message.edit(
                        content=str(args.get("content") or "")[:2000],
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                should_pin = bool(args.get("pinned"))
                if should_pin and not target_message.pinned:
                    await target_message.pin(reason=reason)
                elif not should_pin and target_message.pinned:
                    await target_message.unpin(reason=reason)
                return True, "состояние сообщения восстановлено"
            reaction_emoji = str(args.get("emoji") or "")
            if args.get("should_exist"):
                await target_message.add_reaction(reaction_emoji)
            elif guild.me is not None:
                await target_message.remove_reaction(reaction_emoji, guild.me)
            return True, "реакция P.OS восстановлена"
        if operation == "delete_memory_entry":
            await delete_entry(int(args.get("entry_id") or 0))
            return True, "созданная запись памяти удалена"
        if operation == "delete_automod_rule":
            rule = await guild.fetch_automod_rule(int(args.get("rule_id") or 0))
            await rule.delete(reason=reason)
            return True, "созданное правило AutoMod удалено"
        if operation == "delete_scheduled_event":
            event = await guild.fetch_scheduled_event(int(args.get("event_id") or 0))
            await event.delete(reason=reason)
            return True, "созданное событие удалено"
        if operation == "delete_emoji":
            custom_emoji = guild.get_emoji(int(args.get("emoji_id") or 0))
            if custom_emoji is not None:
                await custom_emoji.delete(reason=reason)
            return True, "созданный эмодзи удалён"
        if operation == "delete_sticker":
            sticker_id = int(args.get("sticker_id") or 0)
            sticker = next((item for item in guild.stickers if item.id == sticker_id), None)
            if sticker is not None:
                await sticker.delete(reason=reason)
            return True, "созданный стикер удалён"
        if operation == "restore_kick_user":
            if guild.get_member(user_id) is not None:
                return True, "участник уже вернулся на сервер"
            try:
                await guild.fetch_ban(discord.Object(id=user_id))
            except discord.NotFound:
                pass
            else:
                return False, "пользователь всё ещё забанен; сначала нужно снять бан"
            if args.get("target_was_bot"):
                return (
                    False,
                    "Discord не позволяет одному боту принудительно вернуть другого; "
                    "бан снят, но бота должен заново пригласить владелец приложения",
                )
            channel = await _invite_channel(guild, int(action.get("source_channel_id") or 0))
            if channel is None:
                return False, "нет канала, где P.OS может создать одноразовое приглашение"
            invite = await channel.create_invite(max_age=86400, max_uses=1, unique=True, reason=reason)
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)
            try:
                await user.send(
                    f"P.OS отменил исключение с сервера `{guild.name}`. Одноразовое приглашение: {invite.url}",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                return False, f"приглашение создано, но ЛС пользователя закрыты: {invite.url}"
            return True, "пользователю отправлено одноразовое приглашение на возврат"
    except Exception as exc:
        logger.error("P.OS deterministic undo failed: %s", type(exc).__name__, exc_info=True)
        return False, "Discord отклонил обратную операцию; подробности сохранены в журнале"
    return False, "для обратной операции нет проверенного исполнителя"


async def undo_recent_action_group(
    bot: discord.Client,
    message: discord.Message,
    args: Mapping[str, Any],
    action_labels: Mapping[str, str],
) -> str:
    try:
        within_minutes = max(1, min(int(args.get("within_minutes") or 30), 1440))
    except (TypeError, ValueError, OverflowError):
        within_minutes = 30
    channel_id = getattr(getattr(message, "channel", None), "id", None)
    if message.guild is None:
        return "Откат доступен только на сервере."
    actions = await claim_recent_pos_action_group(
        actor_id=message.author.id,
        source_guild_id=message.guild.id,
        source_channel_id=channel_id if isinstance(channel_id, int) else None,
        within_seconds=within_minutes * 60,
    )
    if not actions:
        return (
            "Не нашёл в этом канале недавнюю выполненную группу, которую можно "
            "однозначно отменить. Ничего не изменено."
        )

    lines: list[str] = []
    failed = 0
    irreversible = 0
    for action in actions:
        label = action_labels.get(str(action.get("operation") or ""), "действие")
        if action.get("undo_status") == "not_reversible":
            irreversible += 1
            result = "у Discord нет безопасной автоматической обратной операции"
            await finish_pos_action_undo(action["id"], status="acknowledged", result=result)
            lines.append(f"- {label}: {result}")
            continue
        success, result = await undo_exact_action(bot, action)
        terminal_partial = bool(
            not success
            and action.get("inverse_operation") == "restore_kick_user"
            and (
                bool((action.get("inverse_args") or {}).get("target_was_bot"))
                or result.startswith("приглашение создано")
            )
        )
        await finish_pos_action_undo(
            action["id"],
            status="undone" if success else "acknowledged" if terminal_partial else "failed",
            result=result,
        )
        if terminal_partial:
            irreversible += 1
        elif not success:
            failed += 1
        lines.append(f"- {label}: {result}")
    heading = (
        "Последняя группа действий полностью отменена."
        if not failed and not irreversible
        else "Откат выполнен частично: восстановлено всё, что Discord позволяет вернуть без угадывания и потери данных."
    )
    return heading + "\n" + "\n".join(lines)
