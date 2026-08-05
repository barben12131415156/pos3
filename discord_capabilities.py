"""Extended, owner-gated Discord capabilities used by the P.OS tool executor."""
from __future__ import annotations

import datetime as dt
import io
import re
from collections.abc import Sequence
from typing import Any, TypeVar

import discord


MAX_ASSET_BYTES = 512 * 1024
_NamedDiscordObject = TypeVar("_NamedDiscordObject")
EXTENDED_CAPABILITY_NAMES = frozenset({
    "manage_message", "manage_reaction", "list_invites", "revoke_invite",
    "list_webhooks", "delete_webhook", "list_automod_rules", "manage_automod_rule",
    "list_scheduled_events", "manage_scheduled_event", "create_forum_post",
    "set_server_safety", "list_emojis", "manage_emoji", "list_stickers",
    "manage_sticker",
})


def _digits(value: object) -> int | None:
    match = re.search(r"\d{15,22}", str(value or ""))
    return int(match.group(0)) if match else None


def _parse_bool(value: object, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    parsed = _parse_bool_strict(value)
    return default if parsed is None else parsed


def _parse_bool_strict(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in {"1", "true", "yes", "on", "да", "вкл", "включить"}:
        return True
    if normalized in {"0", "false", "no", "off", "нет", "выкл", "выключить"}:
        return False
    return None


def _split_values(value: object, limit: int) -> list[str]:
    return list(dict.fromkeys(
        item.strip()
        for item in re.split(r"[,;\n]+", str(value or ""))
        if item.strip()
    ))[:limit]


def _resolve_channel(
    guild: discord.Guild,
    value: object,
) -> discord.abc.GuildChannel | discord.Thread | None:
    raw = str(value or "").strip()
    channel_id = _digits(raw)
    if channel_id:
        return guild.get_channel_or_thread(channel_id)
    exact = [
        channel
        for channel in [*guild.channels, *getattr(guild, "threads", [])]
        if channel.name.casefold() == raw.casefold()
    ]
    return exact[0] if len(exact) == 1 else None


async def _fetch_message(
    guild: discord.Guild,
    args: dict[str, Any],
) -> tuple[discord.Message | None, str | None]:
    channel = _resolve_channel(guild, args.get("channel_id_or_name"))
    if not isinstance(
        channel,
        (discord.TextChannel, discord.Thread, discord.VoiceChannel),
    ):
        return None, "текстовый канал не найден однозначно"
    message_id = _digits(args.get("message_id"))
    if message_id is None:
        return None, "не указан Discord ID сообщения"
    try:
        return await channel.fetch_message(message_id), None
    except discord.NotFound:
        return None, "сообщение не найдено"


def _reason(args: dict[str, Any], action: str) -> str:
    return (str(args.get("reason") or "").strip() or f"P.OS: {action}")[:512]


def _resolve_by_id_or_name(
    items: Sequence[_NamedDiscordObject],
    value: object,
) -> _NamedDiscordObject | None:
    raw = str(value or "").strip()
    item_id = _digits(raw)
    if item_id:
        return next(
            (item for item in items if int(getattr(item, "id", 0)) == item_id),
            None,
        )
    exact = [
        item
        for item in items
        if str(getattr(item, "name", "")).casefold() == raw.casefold()
    ]
    return exact[0] if len(exact) == 1 else None


def _parse_datetime(value: object) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _event_line(event: discord.ScheduledEvent) -> str:
    channel = getattr(event, "channel", None)
    location = getattr(event, "location", None)
    place = (
        f"#{channel.name}"
        if channel is not None
        else str(location or "без места")
    )
    return (
        f"- {event.name} (`{event.id}`), status={event.status}, "
        f"start={event.start_time.isoformat()}, место={place}"
    )


async def _manage_message(
    guild: discord.Guild,
    args: dict[str, Any],
) -> str:
    target, error = await _fetch_message(guild, args)
    if target is None:
        return f"Ошибка: {error}."
    action = str(args.get("action") or "").strip().casefold()
    reason = _reason(args, f"{action} сообщения")
    if action == "edit":
        if guild.me is None or target.author.id != guild.me.id:
            return "Ошибка: Discord разрешает P.OS редактировать только собственные сообщения."
        content = str(args.get("text") or "").strip()
        if not content:
            return "Ошибка: для редактирования нужен новый текст."
        await target.edit(
            content=content[:2000],
            allowed_mentions=discord.AllowedMentions.none(),
        )
    elif action == "delete":
        await target.delete()
    elif action == "pin":
        await target.pin(reason=reason)
    elif action == "unpin":
        await target.unpin(reason=reason)
    elif action == "publish":
        await target.publish()
    elif action == "end_poll":
        await target.end_poll()
    else:
        return "Ошибка: действие сообщения должно быть edit/delete/pin/unpin/publish/end_poll."
    return f"Действие `{action}` выполнено для сообщения `{target.id}`."


async def _manage_reaction(
    guild: discord.Guild,
    args: dict[str, Any],
) -> str:
    target, error = await _fetch_message(guild, args)
    if target is None:
        return f"Ошибка: {error}."
    action = str(args.get("action") or "").strip().casefold()
    emoji = str(args.get("emoji") or "").strip()
    if action == "add":
        if not emoji:
            return "Ошибка: укажи emoji для реакции."
        await target.add_reaction(emoji)
    elif action == "remove_pos":
        if not emoji or guild.me is None:
            return "Ошибка: укажи emoji; членство P.OS должно быть доступно."
        await target.remove_reaction(emoji, guild.me)
    elif action == "clear":
        if not emoji:
            return "Ошибка: укажи emoji для очистки."
        await target.clear_reaction(emoji)
    elif action == "clear_all":
        await target.clear_reactions()
    else:
        return "Ошибка: действие реакции должно быть add/remove_pos/clear/clear_all."
    return f"Действие реакции `{action}` выполнено для сообщения `{target.id}`."


async def _list_invites(guild: discord.Guild) -> str:
    invites = await guild.invites()
    if not invites:
        return f"На сервере `{guild.name}` нет активных приглашений."
    lines = []
    for invite in invites[:100]:
        inviter = getattr(invite, "inviter", None)
        lines.append(
            f"- `{invite.code}` -> #{getattr(invite.channel, 'name', '?')}; "
            f"использований={invite.uses}; max={invite.max_uses or '∞'}; "
            f"создал={getattr(inviter, 'id', 'неизвестно')}"
        )
    return f"Фактические приглашения `{guild.name}`:\n" + "\n".join(lines)


async def _revoke_invite(guild: discord.Guild, args: dict[str, Any]) -> str:
    raw = str(args.get("invite_code_or_url") or "").strip()
    try:
        code = discord.utils.resolve_invite(raw).code
    except Exception:
        code = raw.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    invite = next(
        (item for item in await guild.invites() if item.code == code),
        None,
    )
    if invite is None:
        return f"Ошибка: активное приглашение `{code}` не найдено на `{guild.name}`."
    await invite.delete(reason=_reason(args, "отзыв приглашения"))
    return f"Приглашение `{code}` отозвано на сервере `{guild.name}`."


async def _list_webhooks(guild: discord.Guild) -> str:
    webhooks = await guild.webhooks()
    if not webhooks:
        return f"На сервере `{guild.name}` нет webhook."
    lines = [
        f"- {hook.name or 'без имени'} (`{hook.id}`), "
        f"channel_id={hook.channel_id}, type={hook.type}, "
        f"creator_id={getattr(hook.user, 'id', 'неизвестно')}"
        for hook in webhooks[:100]
    ]
    return f"Фактические webhook `{guild.name}` (токены не раскрываются):\n" + "\n".join(lines)


async def _delete_webhook(guild: discord.Guild, args: dict[str, Any]) -> str:
    webhook = _resolve_by_id_or_name(
        await guild.webhooks(),
        args.get("webhook_id_or_name"),
    )
    if webhook is None:
        return "Ошибка: webhook не найден однозначно."
    label = webhook.name or str(webhook.id)
    await webhook.delete(
        reason=_reason(args, "удаление webhook"),
        prefer_auth=True,
    )
    return f"Webhook `{label}` (`{webhook.id}`) удалён."


async def _list_automod_rules(guild: discord.Guild) -> str:
    rules = await guild.fetch_automod_rules()
    if not rules:
        return f"На сервере `{guild.name}` нет правил Discord AutoMod."
    lines = [
        f"- {rule.name} (`{rule.id}`), enabled={rule.enabled}, "
        f"trigger={rule.trigger.type}, actions="
        + ",".join(str(action.type) for action in rule.actions)
        for rule in rules[:100]
    ]
    return f"Фактические правила Discord AutoMod `{guild.name}`:\n" + "\n".join(lines)


def _automod_actions(
    guild: discord.Guild,
    args: dict[str, Any],
) -> tuple[list[discord.AutoModRuleAction], str | None]:
    actions = [
        discord.AutoModRuleAction(
            type=discord.AutoModRuleActionType.block_message,
            custom_message=(
                str(args.get("custom_message") or "").strip()[:150]
                or None
            ),
        )
    ]
    alert_channel_raw = str(args.get("alert_channel_id_or_name") or "").strip()
    if alert_channel_raw:
        alert_channel = _resolve_channel(guild, alert_channel_raw)
        if not isinstance(alert_channel, discord.TextChannel):
            return [], "канал AutoMod-уведомлений не найден"
        actions.append(
            discord.AutoModRuleAction(
                type=discord.AutoModRuleActionType.send_alert_message,
                channel_id=alert_channel.id,
            )
        )
    timeout_raw = str(args.get("timeout_minutes") or "").strip()
    if timeout_raw:
        try:
            timeout_minutes = max(1, min(int(timeout_raw), 40320))
        except ValueError:
            return [], "timeout_minutes должен быть целым числом"
        actions.append(
            discord.AutoModRuleAction(
                type=discord.AutoModRuleActionType.timeout,
                duration=dt.timedelta(minutes=timeout_minutes),
            )
        )
    return actions, None


async def _manage_automod_rule(
    guild: discord.Guild,
    args: dict[str, Any],
) -> str:
    action = str(args.get("action") or "").strip().casefold()
    reason = _reason(args, f"{action} Discord AutoMod")
    if action in {"create_keyword", "create_mention_spam"}:
        name = str(args.get("name") or "").strip()[:100]
        if not name:
            return "Ошибка: для правила AutoMod нужно имя."
        enabled = _parse_bool_strict(args.get("enabled"))
        if args.get("enabled") not in (None, "") and enabled is None:
            return "Ошибка: enabled должен быть true или false."
        actions, error = _automod_actions(guild, args)
        if error:
            return f"Ошибка: {error}."
        if action == "create_keyword":
            keywords = _split_values(args.get("keywords"), 1000)
            regex_patterns = _split_values(args.get("regex_patterns"), 10)
            allow_list = _split_values(args.get("allow_list"), 100)
            if not keywords and not regex_patterns:
                return "Ошибка: добавь keywords или regex_patterns."
            trigger = discord.AutoModTrigger(
                type=discord.AutoModRuleTriggerType.keyword,
                keyword_filter=keywords or None,
                regex_patterns=regex_patterns or None,
                allow_list=allow_list or None,
            )
        else:
            try:
                mention_limit = max(
                    1,
                    min(int(args.get("mention_limit") or 5), 50),
                )
            except ValueError:
                return "Ошибка: mention_limit должен быть целым числом."
            mention_raid = _parse_bool_strict(args.get("mention_raid_protection"))
            if (
                args.get("mention_raid_protection") not in (None, "")
                and mention_raid is None
            ):
                return "Ошибка: mention_raid_protection должен быть true или false."
            trigger = discord.AutoModTrigger(
                type=discord.AutoModRuleTriggerType.mention_spam,
                mention_limit=mention_limit,
                mention_raid_protection=True if mention_raid is None else mention_raid,
            )
        created_rule = await guild.create_automod_rule(
            name=name,
            event_type=discord.AutoModRuleEventType.message_send,
            trigger=trigger,
            actions=actions,
            enabled=True if enabled is None else enabled,
            reason=reason,
        )
        return (
            f"Правило Discord AutoMod `{created_rule.name}` создано "
            f"(`{created_rule.id}`)."
        )

    rules = await guild.fetch_automod_rules()
    target_rule = _resolve_by_id_or_name(rules, args.get("rule_id_or_name"))
    if target_rule is None:
        return "Ошибка: правило Discord AutoMod не найдено однозначно."
    if action == "enable":
        await target_rule.edit(enabled=True, reason=reason)
    elif action == "disable":
        await target_rule.edit(enabled=False, reason=reason)
    elif action == "rename":
        new_name = str(args.get("name") or "").strip()[:100]
        if not new_name:
            return "Ошибка: укажи новое имя правила."
        await target_rule.edit(name=new_name, reason=reason)
    elif action == "delete":
        await target_rule.delete(reason=reason)
    else:
        return "Ошибка: действие AutoMod должно быть create_keyword/create_mention_spam/enable/disable/rename/delete."
    return (
        f"Действие `{action}` выполнено для правила AutoMod "
        f"`{target_rule.id}`."
    )


async def _list_scheduled_events(guild: discord.Guild) -> str:
    events = list(guild.scheduled_events)
    if not events:
        try:
            events = await guild.fetch_scheduled_events(with_counts=True)
        except discord.HTTPException:
            events = []
    if not events:
        return f"На сервере `{guild.name}` нет запланированных событий."
    return f"Фактические события `{guild.name}`:\n" + "\n".join(
        _event_line(event) for event in events[:100]
    )


async def _manage_scheduled_event(
    guild: discord.Guild,
    args: dict[str, Any],
) -> str:
    action = str(args.get("action") or "").strip().casefold()
    reason = _reason(args, f"{action} события")
    if action == "create":
        name = str(args.get("name") or "").strip()[:100]
        start = _parse_datetime(args.get("start_time"))
        if not name or start is None:
            return "Ошибка: для события нужны name и start_time в ISO 8601."
        event_type = str(args.get("event_type") or "external").strip().casefold()
        description = str(args.get("description") or "").strip()[:1000]
        end = _parse_datetime(args.get("end_time"))
        if event_type == "external":
            location = str(args.get("location") or "").strip()[:100]
            if not location:
                return "Ошибка: для внешнего события нужна location."
            end = end or (start + dt.timedelta(hours=1))
            created_event = await guild.create_scheduled_event(
                name=name,
                start_time=start,
                end_time=end,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location=location,
                description=description,
                reason=reason,
            )
        else:
            if event_type not in {"stage", "voice"}:
                return "Ошибка: event_type должен быть external, stage или voice."
            channel = _resolve_channel(guild, args.get("channel_id_or_name"))
            if event_type == "stage":
                if not isinstance(channel, discord.StageChannel):
                    return "Ошибка: для события `stage` нужен stage-канал."
                created_event = await guild.create_scheduled_event(
                    name=name,
                    start_time=start,
                    entity_type=discord.EntityType.stage_instance,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    channel=channel,
                    description=description,
                    reason=reason,
                )
            elif event_type == "voice":
                if not isinstance(channel, discord.VoiceChannel):
                    return "Ошибка: для события `voice` нужен голосовой канал."
                created_event = await guild.create_scheduled_event(
                    name=name,
                    start_time=start,
                    entity_type=discord.EntityType.voice,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    channel=channel,
                    description=description,
                    reason=reason,
                )
        return f"Событие `{created_event.name}` создано (`{created_event.id}`)."

    events = list(guild.scheduled_events)
    if not events:
        events = await guild.fetch_scheduled_events(with_counts=False)
    target_event = _resolve_by_id_or_name(events, args.get("event_id_or_name"))
    if target_event is None:
        return "Ошибка: запланированное событие не найдено однозначно."
    if action == "delete":
        await target_event.delete(reason=reason)
    elif action in {"cancel", "start", "complete"}:
        status = {
            "cancel": discord.EventStatus.canceled,
            "start": discord.EventStatus.active,
            "complete": discord.EventStatus.completed,
        }[action]
        await target_event.edit(status=status, reason=reason)
    elif action == "edit":
        kwargs: dict[str, Any] = {}
        if str(args.get("name") or "").strip():
            kwargs["name"] = str(args["name"]).strip()[:100]
        if args.get("description") not in (None, ""):
            kwargs["description"] = str(args["description"]).strip()[:1000]
        start = _parse_datetime(args.get("start_time"))
        end = _parse_datetime(args.get("end_time"))
        if start is not None:
            kwargs["start_time"] = start
        if end is not None:
            kwargs["end_time"] = end
        requested_type = str(args.get("event_type") or "").strip().casefold()
        if requested_type and requested_type not in {"external", "stage", "voice"}:
            return "Ошибка: event_type должен быть external, stage или voice."
        channel_raw = str(args.get("channel_id_or_name") or "").strip()
        if requested_type == "external":
            location = str(args.get("location") or "").strip()[:100]
            if not location:
                return "Ошибка: при смене типа события на external нужна location."
            kwargs["entity_type"] = discord.EntityType.external
            kwargs["channel"] = None
            kwargs["location"] = location
        elif requested_type in {"stage", "voice"}:
            channel = _resolve_channel(guild, channel_raw)
            expected = discord.StageChannel if requested_type == "stage" else discord.VoiceChannel
            if not isinstance(channel, expected):
                return f"Ошибка: при смене типа на `{requested_type}` нужен точный подходящий канал."
            kwargs["entity_type"] = (
                discord.EntityType.stage_instance
                if requested_type == "stage"
                else discord.EntityType.voice
            )
            kwargs["channel"] = channel
        elif channel_raw:
            channel = _resolve_channel(guild, channel_raw)
            if not isinstance(channel, (discord.StageChannel, discord.VoiceChannel)):
                return "Ошибка: voice/stage-канал события не найден однозначно."
            kwargs["channel"] = channel
        if not kwargs:
            return "Ошибка: не указаны поля события для изменения."
        await target_event.edit(reason=reason, **kwargs)
    else:
        return "Ошибка: действие события должно быть create/edit/start/complete/cancel/delete."
    return f"Действие `{action}` выполнено для события `{target_event.id}`."


async def _create_forum_post(
    guild: discord.Guild,
    args: dict[str, Any],
) -> str:
    channel = _resolve_channel(guild, args.get("channel_id_or_name"))
    if not isinstance(channel, discord.ForumChannel):
        return "Ошибка: форумный канал не найден однозначно."
    name = str(args.get("name") or "").strip()[:100]
    content = str(args.get("text") or "").strip()[:2000]
    if not name or not content:
        return "Ошибка: для форумного поста нужны name и text."
    created = await channel.create_thread(
        name=name,
        content=content,
        allowed_mentions=discord.AllowedMentions.none(),
        reason=_reason(args, "создание форумного поста"),
    )
    thread = created.thread
    return f"Форумный пост `{thread.name}` создан (`{thread.id}`)."


async def _set_server_safety(
    guild: discord.Guild,
    args: dict[str, Any],
) -> str:
    kwargs: dict[str, Any] = {}
    if args.get("invites_disabled") not in (None, ""):
        invites_disabled = _parse_bool_strict(args["invites_disabled"])
        if invites_disabled is None:
            return "Ошибка: invites_disabled должен быть true или false."
        kwargs["invites_disabled"] = invites_disabled
    if args.get("raid_alerts_enabled") not in (None, ""):
        raid_alerts_enabled = _parse_bool_strict(args["raid_alerts_enabled"])
        if raid_alerts_enabled is None:
            return "Ошибка: raid_alerts_enabled должен быть true или false."
        kwargs["raid_alerts_disabled"] = not raid_alerts_enabled
    safety_channel_raw = str(
        args.get("safety_alerts_channel_id_or_name") or ""
    ).strip()
    if safety_channel_raw:
        safety_channel = _resolve_channel(guild, safety_channel_raw)
        if not isinstance(safety_channel, discord.TextChannel):
            return "Ошибка: канал safety-уведомлений не найден."
        kwargs["safety_alerts_channel"] = safety_channel
    now = discord.utils.utcnow()
    for arg_name, discord_name in (
        ("invites_disabled_minutes", "invites_disabled_until"),
        ("dms_disabled_minutes", "dms_disabled_until"),
    ):
        raw = str(args.get(arg_name) or "").strip()
        if not raw:
            continue
        try:
            minutes = max(1, min(int(raw), 24 * 60))
        except ValueError:
            return f"Ошибка: {arg_name} должен быть целым числом."
        kwargs[discord_name] = now + dt.timedelta(minutes=minutes)
    if not kwargs:
        return "Ошибка: не указаны нативные safety-настройки для изменения."
    await guild.edit(
        reason=_reason(args, "изменение нативной защиты Discord"),
        **kwargs,
    )
    return (
        f"Нативные safety-настройки `{guild.name}` обновлены: "
        + ", ".join(sorted(kwargs))
        + "."
    )


async def _list_assets(guild: discord.Guild, asset_type: str) -> str:
    items: list[Any]
    if asset_type == "emoji":
        items = list(guild.emojis)
        label = "эмодзи"
    else:
        items = list(guild.stickers)
        label = "стикеры"
    if not items:
        return f"На сервере `{guild.name}` нет пользовательских {label}."
    lines = [
        f"- {item.name} (`{item.id}`), available={getattr(item, 'available', True)}"
        for item in items[:200]
    ]
    return f"Фактические {label} `{guild.name}`:\n" + "\n".join(lines)


async def _read_current_attachment(
    message: discord.Message,
    index_raw: object,
) -> tuple[bytes | None, str | None]:
    try:
        index = max(0, int(str(index_raw or "0")))
    except ValueError:
        return None, "attachment_index должен быть целым числом"
    attachments = list(getattr(message, "attachments", []) or [])
    if index >= len(attachments):
        return None, "в текущем сообщении нет вложения с таким индексом"
    attachment = attachments[index]
    declared_size = int(getattr(attachment, "size", 0) or 0)
    if declared_size <= 0 or declared_size > MAX_ASSET_BYTES:
        return None, "вложение пустое или превышает 512 КБ"
    try:
        data = await attachment.read(use_cached=True)
    except TypeError:
        data = await attachment.read()
    if not isinstance(data, bytes) or not data or len(data) > MAX_ASSET_BYTES:
        return None, "вложение не удалось безопасно прочитать"
    return data, None


async def _manage_emoji(
    guild: discord.Guild,
    message: discord.Message,
    args: dict[str, Any],
) -> str:
    action = str(args.get("action") or "").strip().casefold()
    reason = _reason(args, f"{action} эмодзи")
    if action == "create":
        name = str(args.get("name") or "").strip()[:32]
        data, error = await _read_current_attachment(
            message,
            args.get("attachment_index"),
        )
        if not name or data is None:
            return f"Ошибка: {error or 'укажи имя эмодзи'}."
        created_emoji = await guild.create_custom_emoji(
            name=name,
            image=data,
            reason=reason,
        )
        return (
            f"Эмодзи `{created_emoji.name}` создан (`{created_emoji.id}`)."
        )
    target_emoji = _resolve_by_id_or_name(
        list(guild.emojis),
        args.get("emoji_id_or_name"),
    )
    if target_emoji is None:
        return "Ошибка: эмодзи не найден однозначно."
    if action == "delete":
        await target_emoji.delete(reason=reason)
    elif action == "rename":
        name = str(args.get("name") or "").strip()[:32]
        if not name:
            return "Ошибка: укажи новое имя эмодзи."
        await target_emoji.edit(name=name, reason=reason)
    else:
        return "Ошибка: действие эмодзи должно быть create/rename/delete."
    return f"Действие `{action}` выполнено для эмодзи `{target_emoji.id}`."


async def _manage_sticker(
    guild: discord.Guild,
    message: discord.Message,
    args: dict[str, Any],
) -> str:
    action = str(args.get("action") or "").strip().casefold()
    reason = _reason(args, f"{action} стикера")
    if action == "create":
        name = str(args.get("name") or "").strip()[:30]
        emoji = str(args.get("emoji") or "").strip()[:50]
        data, error = await _read_current_attachment(
            message,
            args.get("attachment_index"),
        )
        if not name or not emoji or data is None:
            return f"Ошибка: {error or 'нужны name и emoji'}."
        file = discord.File(
            io.BytesIO(data),
            filename="pos-sticker.png",
        )
        created_sticker = await guild.create_sticker(
            name=name,
            description=str(args.get("description") or "").strip()[:100],
            emoji=emoji,
            file=file,
            reason=reason,
        )
        return (
            f"Стикер `{created_sticker.name}` создан "
            f"(`{created_sticker.id}`)."
        )
    target_sticker = _resolve_by_id_or_name(
        list(guild.stickers),
        args.get("sticker_id_or_name"),
    )
    if target_sticker is None:
        return "Ошибка: стикер не найден однозначно."
    if action == "delete":
        await target_sticker.delete(reason=reason)
    elif action == "edit":
        kwargs: dict[str, str] = {}
        for key, limit in (("name", 30), ("description", 100), ("emoji", 50)):
            if args.get(key) not in (None, ""):
                kwargs[key] = str(args[key]).strip()[:limit]
        if not kwargs:
            return "Ошибка: не указаны поля стикера для изменения."
        await target_sticker.edit(reason=reason, **kwargs)
    else:
        return "Ошибка: действие стикера должно быть create/edit/delete."
    return (
        f"Действие `{action}` выполнено для стикера "
        f"`{target_sticker.id}`."
    )


async def execute_extended_capability(
    guild: discord.Guild,
    message: discord.Message,
    name: str,
    args: dict[str, Any],
) -> str | None:
    """Execute one extended capability; return ``None`` for unknown names."""
    if name not in EXTENDED_CAPABILITY_NAMES:
        return None
    try:
        if name == "manage_message":
            return await _manage_message(guild, args)
        if name == "manage_reaction":
            return await _manage_reaction(guild, args)
        if name == "list_invites":
            return await _list_invites(guild)
        if name == "revoke_invite":
            return await _revoke_invite(guild, args)
        if name == "list_webhooks":
            return await _list_webhooks(guild)
        if name == "delete_webhook":
            return await _delete_webhook(guild, args)
        if name == "list_automod_rules":
            return await _list_automod_rules(guild)
        if name == "manage_automod_rule":
            return await _manage_automod_rule(guild, args)
        if name == "list_scheduled_events":
            return await _list_scheduled_events(guild)
        if name == "manage_scheduled_event":
            return await _manage_scheduled_event(guild, args)
        if name == "create_forum_post":
            return await _create_forum_post(guild, args)
        if name == "set_server_safety":
            return await _set_server_safety(guild, args)
        if name == "list_emojis":
            return await _list_assets(guild, "emoji")
        if name == "manage_emoji":
            return await _manage_emoji(guild, message, args)
        if name == "list_stickers":
            return await _list_assets(guild, "sticker")
        if name == "manage_sticker":
            return await _manage_sticker(guild, message, args)
    except discord.Forbidden:
        return "Ошибка: Discord запретил операцию из-за прав или иерархии."
    except discord.NotFound:
        return "Ошибка: объект уже удалён или больше недоступен."
    except discord.HTTPException as exc:
        status = getattr(exc, "status", None)
        suffix = f" (HTTP {status})" if isinstance(status, int) else ""
        return f"Ошибка: Discord API отклонил операцию{suffix}."
    return None
