"""Persistent owner vacation mode and deterministic Discord ping handling."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import discord

from config import POS_CREATOR_ID
from logging_utils import is_log_channel
from storage import DEFAULT_DB_PATH, get_integration_state, set_integration_state


logger = logging.getLogger(__name__)

_STATE_KEY = "owner_vacation_mode:v1"

VACATION_PING_REPLY = (
    "Пумба сейчас в отпуске и не отвечает в Discord. Если нужен ответ, попроси "
    "P.OS написать Пумбе в Telegram и сразу добавь текст сообщения, например: "
    "«P.OS, напиши Пумбе в Telegram: ...»."
)


@dataclass(frozen=True, slots=True)
class VacationModeState:
    enabled: bool = False
    changed_at: int = 0
    changed_by: int = 0


def _decode_state(raw: str | None) -> VacationModeState:
    if not raw:
        return VacationModeState()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            raise ValueError("invalid vacation-mode payload")
        return VacationModeState(
            enabled=payload["enabled"],
            changed_at=max(0, int(payload.get("changed_at") or 0)),
            changed_by=max(0, int(payload.get("changed_by") or 0)),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring malformed persistent vacation-mode state.")
        return VacationModeState()


async def get_owner_vacation_mode(
    db_path: str = DEFAULT_DB_PATH,
) -> VacationModeState:
    return _decode_state(await get_integration_state(_STATE_KEY, db_path))


async def is_owner_vacation_mode_enabled(
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    return (await get_owner_vacation_mode(db_path)).enabled


async def set_owner_vacation_mode(
    enabled: bool,
    *,
    actor_id: int,
    db_path: str = DEFAULT_DB_PATH,
) -> tuple[VacationModeState, bool]:
    """Set the global mode only for the immutable Pumba Discord identity."""
    if int(actor_id) != POS_CREATOR_ID:
        raise PermissionError("only Pumba can change vacation mode")

    current = await get_owner_vacation_mode(db_path)
    if current.enabled == bool(enabled):
        return current, False

    state = VacationModeState(
        enabled=bool(enabled),
        changed_at=int(time.time()),
        changed_by=POS_CREATOR_ID,
    )
    await set_integration_state(
        _STATE_KEY,
        json.dumps(
            {
                "enabled": state.enabled,
                "changed_at": state.changed_at,
                "changed_by": state.changed_by,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        db_path,
    )
    return state, True


def _mentioned_user_ids(message: discord.Message) -> set[int]:
    ids = {
        int(user.id)
        for user in (getattr(message, "mentions", None) or ())
        if getattr(user, "id", None)
    }
    for value in getattr(message, "raw_mentions", None) or ():
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _mentioned_role_ids(message: discord.Message) -> set[int]:
    ids = {
        int(role.id)
        for role in (getattr(message, "role_mentions", None) or ())
        if getattr(role, "id", None)
    }
    for value in getattr(message, "raw_role_mentions", None) or ():
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids


async def _creator_has_mentioned_role(
    guild: discord.Guild,
    role_ids: set[int],
) -> bool:
    if not role_ids:
        return False
    creator = guild.get_member(POS_CREATOR_ID)
    if creator is None:
        try:
            creator = await guild.fetch_member(POS_CREATOR_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    creator_role_ids: set[int] = set()
    for role in getattr(creator, "roles", None) or ():
        role_id = getattr(role, "id", None)
        is_default = getattr(role, "is_default", None)
        if role_id and not (callable(is_default) and is_default()):
            creator_role_ids.add(int(role_id))
    return bool(role_ids & creator_role_ids)


async def handle_owner_vacation_ping(message: discord.Message) -> bool:
    """Reply once when an active vacation mode message genuinely pings Pumba."""
    guild = getattr(message, "guild", None)
    author = getattr(message, "author", None)
    if (
        guild is None
        or author is None
        or getattr(author, "bot", False)
        or int(getattr(author, "id", 0) or 0) == POS_CREATOR_ID
        or is_log_channel(getattr(message, "channel", None))
    ):
        return False

    directly_mentioned = POS_CREATOR_ID in _mentioned_user_ids(message)
    role_ids = _mentioned_role_ids(message)
    if not directly_mentioned and not role_ids:
        return False
    try:
        enabled = await is_owner_vacation_mode_enabled()
    except Exception as exc:
        logger.error(
            "Vacation-mode state unavailable for message %s: %s",
            getattr(message, "id", "unknown"),
            type(exc).__name__,
            exc_info=True,
        )
        return False
    if not enabled:
        return False
    if not directly_mentioned and not await _creator_has_mentioned_role(guild, role_ids):
        return False

    await message.reply(
        VACATION_PING_REPLY,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return True
