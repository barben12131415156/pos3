"""
storage.py — async SQLite через aiosqlite.

Изменения по аудиту:
- единое долгоживущее соединение на путь к БД (раньше connect() на каждый запрос
  блокировал event loop и давал "database is locked" при параллельных сообщениях);
- режим WAL для конкурентного чтения/записи;
- целостный снапшот для бэкапа через `VACUUM INTO` (раньше копировался живой файл,
  что при активном WAL давало повреждённую копию);
- восстановление из Discord только из сообщений, отправленных САМИМ ботом
  (раньше любой, кто мог писать в backup-канал, мог подменить базу);
- удалены неиспользуемые таблицы private_chats (plaintext-пароли) и chat_messages.
"""
from __future__ import annotations

import os
import asyncio
import gzip
import hashlib
import io
import logging
import json
import re
import shutil
import sqlite3
import tempfile
import time
from weakref import WeakKeyDictionary

import discord
import aiosqlite

DEFAULT_DB_PATH = "bot_data.db"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Единое соединение на путь к БД
# ---------------------------------------------------------------------------
_connections: dict[str, aiosqlite.Connection] = {}
_conn_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()
# A single aiosqlite connection serializes individual statements, but it does
# not make a multi-statement transaction atomic. Keep every write transaction
# and VACUUM snapshot behind the same lock.
_write_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


def _loop_lock(
    registry: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock],
) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = registry.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        registry[loop] = lock
    return lock


async def _get_conn(db_path: str = DEFAULT_DB_PATH) -> aiosqlite.Connection:
    """Вернуть (создав при необходимости) общее соединение для db_path."""
    conn = _connections.get(db_path)
    if conn is not None:
        return conn
    async with _loop_lock(_conn_locks):
        conn = _connections.get(db_path)
        if conn is not None:
            return conn
        conn = await aiosqlite.connect(db_path)
        # WAL даёт одновременное чтение во время записи и снижает блокировки.
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.commit()
        _connections[db_path] = conn
        return conn


async def close_all_connections() -> None:
    """Корректно закрыть все соединения (вызывать при остановке бота)."""
    async with _loop_lock(_write_locks):
        async with _loop_lock(_conn_locks):
            for path, conn in list(_connections.items()):
                try:
                    await conn.close()
                except Exception:
                    logger.exception("Не удалось закрыть соединение %s.", path)
                _connections.pop(path, None)


async def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    async with _loop_lock(_write_locks):
        await _init_db_unlocked(db_path)


async def _init_db_unlocked(db_path: str) -> None:
    conn = await _get_conn(db_path)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_context (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            context TEXT,
            PRIMARY KEY (user_id, guild_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_muted (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            muted INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )
    """)
    # 0.8: настройки модерации/поведения на сервер. Хранятся как JSON-строка,
    # чтобы схему можно было расширять без миграций. guild_id=0 — глобальный слот
    # значений по умолчанию для всех серверов.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            settings TEXT
        )
    """)
    # Фактический журнал для P.OS: server logs, tool-действия, пинги и удаления.
    # Это не заменяет Discord log-каналы, но даёт ИИ проверяемую память, чтобы он
    # отвечал по данным, а не по догадкам.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT,
            target_user_id INTEGER,
            target_role_id INTEGER,
            channel_id INTEGER,
            message_id INTEGER,
            summary TEXT,
            details TEXT,
            deleted INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_event_guild_ts ON ai_event_log(guild_id, ts)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_event_type ON ai_event_log(event_type)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_event_target_user ON ai_event_log(target_user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_event_target_role ON ai_event_log(target_role_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_event_message ON ai_event_log(guild_id, message_id)")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_event_recipients (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            source_role_id INTEGER,
            PRIMARY KEY (event_id, user_id)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_event_recipient_user ON ai_event_recipients(user_id, event_id)")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS security_state (
            guild_id INTEGER PRIMARY KEY,
            raid_until REAL NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS security_posture (
            guild_id INTEGER PRIMARY KEY,
            snapshot TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS form_decisions (
            message_id INTEGER PRIMARY KEY,
            decided_at INTEGER NOT NULL
        )
    """)
    # Чистим устаревшие таблицы со старых версий (plaintext-пароли и т.п.).
    await conn.execute("DROP TABLE IF EXISTS private_chats")
    await conn.execute("DROP TABLE IF EXISTS chat_messages")
    await conn.commit()


# ---------------------------------------------------------------------------
# entries helpers
# ---------------------------------------------------------------------------

async def add_entry(title: str, description: str, db_path: str = DEFAULT_DB_PATH) -> int:
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        cursor = await conn.execute(
            "INSERT INTO entries (title, description) VALUES (?, ?)",
            ((title or "").strip(), (description or "").strip()),
        )
        await conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an ID for the inserted entry")
        return cursor.lastrowid


async def delete_entry(entry_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        cursor = await conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        await conn.commit()
        return cursor.rowcount > 0


async def list_entries(limit: int = 10, db_path: str = DEFAULT_DB_PATH) -> list[tuple[int, str, str]]:
    conn = await _get_conn(db_path)
    cursor = await conn.execute(
        "SELECT id, title, description FROM entries ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 50)),),
    )
    rows = await cursor.fetchall()
    return [(int(row[0]), str(row[1] or ""), str(row[2] or "")) for row in rows]


# ---------------------------------------------------------------------------
# AI context helpers  (keyed by user_id + guild_id)
# user_id=0 is used as the guild-level shared memory slot.
# ---------------------------------------------------------------------------

async def get_ai_context(user_id: int, guild_id: int, db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Return stored AI context JSON string for (user_id, guild_id), or None."""
    conn = await _get_conn(db_path)
    cursor = await conn.execute(
        "SELECT context FROM ai_context WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id),
    )
    row = await cursor.fetchone()
    return str(row[0]) if row and row[0] is not None else None


async def update_ai_context(user_id: int, guild_id: int, context: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Upsert AI context JSON string for (user_id, guild_id)."""
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute(
            "INSERT INTO ai_context (user_id, guild_id, context) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET context = excluded.context",
            (user_id, guild_id, context),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# AI mute helpers
# ---------------------------------------------------------------------------

async def is_ai_muted(user_id: int, guild_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Return True if P.OS is muted for this user on this guild."""
    conn = await _get_conn(db_path)
    cursor = await conn.execute(
        "SELECT muted FROM ai_muted WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def set_ai_muted_user(user_id: int, guild_id: int, muted: bool, db_path: str = DEFAULT_DB_PATH) -> None:
    """Add a user to P.OS ignore or physically remove the ignore record."""
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        if muted:
            await conn.execute(
                "INSERT INTO ai_muted (user_id, guild_id, muted) VALUES (?, ?, 1) "
                "ON CONFLICT(user_id, guild_id) DO UPDATE SET muted = 1",
                (user_id, guild_id),
            )
        else:
            await conn.execute(
                "DELETE FROM ai_muted WHERE user_id = ? AND guild_id = ?",
                (user_id, guild_id),
            )
        await conn.commit()


# ---------------------------------------------------------------------------
# Guild settings helpers (0.8) — per-guild JSON blob of moderation/behaviour
# toggles. guild_id=0 is the global default slot.
# ---------------------------------------------------------------------------

async def get_guild_settings_raw(guild_id: int, db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Return the stored settings JSON string for guild_id, or None."""
    conn = await _get_conn(db_path)
    cursor = await conn.execute(
        "SELECT settings FROM guild_settings WHERE guild_id = ?",
        (guild_id,),
    )
    row = await cursor.fetchone()
    return str(row[0]) if row and row[0] is not None else None


async def set_guild_settings_raw(guild_id: int, settings_json: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Upsert the settings JSON string for guild_id."""
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute(
            "INSERT INTO guild_settings (guild_id, settings) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET settings = excluded.settings",
            (guild_id, settings_json),
        )
        await conn.commit()


async def claim_form_decision(
    message_id: int,
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """Atomically claim a persistent form decision; False means already handled."""
    if int(message_id) <= 0:
        return False
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO form_decisions (message_id, decided_at) VALUES (?, ?)",
            (int(message_id), int(time.time())),
        )
        await conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Persistent security state
# ---------------------------------------------------------------------------

async def set_raid_state(
    guild_id: int,
    raid_until: float,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    if guild_id <= 0:
        raise ValueError("guild_id must be positive")
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute(
            "INSERT INTO security_state (guild_id, raid_until, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "raid_until = excluded.raid_until, updated_at = excluded.updated_at",
            (guild_id, float(raid_until), int(time.time())),
        )
        await conn.commit()


async def clear_raid_state(guild_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute("DELETE FROM security_state WHERE guild_id = ?", (guild_id,))
        await conn.commit()


async def get_active_raid_states(
    *,
    now: float | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[int, float]:
    current_time = time.time() if now is None else float(now)
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute("DELETE FROM security_state WHERE raid_until <= ?", (current_time,))
        cursor = await conn.execute(
            "SELECT guild_id, raid_until FROM security_state WHERE raid_until > ?",
            (current_time,),
        )
        rows = await cursor.fetchall()
        await conn.commit()
        return {int(row[0]): float(row[1]) for row in rows}


async def get_security_posture(
    guild_id: int,
    db_path: str = DEFAULT_DB_PATH,
) -> dict | None:
    conn = await _get_conn(db_path)
    cursor = await conn.execute(
        "SELECT snapshot, snapshot_hash FROM security_posture WHERE guild_id = ?",
        (int(guild_id),),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    snapshot_text = str(row[0] or "")
    expected_hash = str(row[1] or "")
    actual_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        logger.error("Security posture hash mismatch for guild %s", guild_id)
        return None
    try:
        snapshot = json.loads(snapshot_text)
    except json.JSONDecodeError:
        return None
    return snapshot if isinstance(snapshot, dict) else None


async def set_security_posture(
    guild_id: int,
    snapshot: dict,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    if guild_id <= 0:
        raise ValueError("guild_id must be positive")
    snapshot_text = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(snapshot_text) > 2_000_000:
        raise ValueError("security posture snapshot is too large")
    snapshot_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute(
            "INSERT INTO security_posture (guild_id, snapshot, snapshot_hash, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET "
            "snapshot = excluded.snapshot, snapshot_hash = excluded.snapshot_hash, "
            "updated_at = excluded.updated_at",
            (int(guild_id), snapshot_text, snapshot_hash, int(time.time())),
        )
        await conn.commit()
    return snapshot_hash


# ---------------------------------------------------------------------------
# AI factual event log
# ---------------------------------------------------------------------------

async def add_ai_event(
    *,
    guild_id: int,
    event_type: str,
    actor_id: int | None = None,
    actor_name: str | None = None,
    target_user_id: int | None = None,
    target_role_id: int | None = None,
    channel_id: int | None = None,
    message_id: int | None = None,
    summary: str = "",
    details: str | dict | list | None = None,
    ts: int | None = None,
    deleted: bool = False,
    recipient_user_ids: list[int] | tuple[int, ...] | set[int] | None = None,
    recipient_role_id: int | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    if details is None:
        details_text = ""
    elif isinstance(details, str):
        details_text = details
    else:
        details_text = json.dumps(details, ensure_ascii=False)
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        cursor = await conn.execute(
            """
            INSERT INTO ai_event_log (
                ts, guild_id, event_type, actor_id, actor_name, target_user_id,
                target_role_id, channel_id, message_id, summary, details, deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(ts or time.time()),
                int(guild_id),
                str(event_type or "event")[:80],
                actor_id,
                (actor_name or "")[:200],
                target_user_id,
                target_role_id,
                channel_id,
                message_id,
                (summary or "")[:1200],
                details_text[:8000],
                int(bool(deleted)),
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an ID for the inserted AI event")
        event_id = cursor.lastrowid
        if recipient_user_ids:
            recipient_rows = [
                (event_id, user_id, recipient_role_id)
                for user_id in dict.fromkeys(int(value) for value in recipient_user_ids)
                if user_id > 0
            ][:50_000]
            if recipient_rows:
                await conn.executemany(
                    "INSERT OR IGNORE INTO ai_event_recipients "
                    "(event_id, user_id, source_role_id) VALUES (?, ?, ?)",
                    recipient_rows,
                )
        await conn.commit()
        return event_id


async def mark_ai_message_deleted(guild_id: int, message_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.execute(
            "UPDATE ai_event_log SET deleted = 1 WHERE guild_id = ? AND message_id = ?",
            (int(guild_id), int(message_id)),
        )
        await conn.commit()


async def mark_ai_messages_deleted(guild_id: int, message_ids, db_path: str = DEFAULT_DB_PATH) -> None:
    ids = [int(message_id) for message_id in dict.fromkeys(message_ids or [])]
    if not ids:
        return
    async with _loop_lock(_write_locks):
        conn = await _get_conn(db_path)
        await conn.executemany(
            "UPDATE ai_event_log SET deleted = 1 WHERE guild_id = ? AND message_id = ?",
            [(int(guild_id), message_id) for message_id in ids[:10_000]],
        )
        await conn.commit()


async def search_ai_events(
    *,
    guild_id: int | None = None,
    event_type: str | None = None,
    actor_id: int | None = None,
    target_user_id: int | None = None,
    target_role_id: int | None = None,
    recipient_user_id: int | None = None,
    channel_id: int | None = None,
    message_id: int | None = None,
    query: str | None = None,
    limit: int = 25,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    conn = await _get_conn(db_path)
    guild_filter = int(guild_id) if guild_id is not None else None
    event_filter = str(event_type) if event_type else None
    actor_filter = int(actor_id) if actor_id is not None else None
    user_filter = int(target_user_id) if target_user_id is not None else None
    role_filter = int(target_role_id) if target_role_id is not None else None
    recipient_filter = int(recipient_user_id) if recipient_user_id is not None else None
    channel_filter = int(channel_id) if channel_id is not None else None
    message_filter = int(message_id) if message_id is not None else None
    query_text = query.strip() if query else ""
    query_filter = f"%{query_text}%" if query_text else None
    capped_limit = max(1, min(int(limit or 25), 100))
    cursor = await conn.execute(
        """
        SELECT id, ts, guild_id, event_type, actor_id, actor_name, target_user_id,
               target_role_id, channel_id, message_id, summary, details, deleted
        FROM ai_event_log
        WHERE (? IS NULL OR guild_id = ?)
          AND (? IS NULL OR event_type = ?)
          AND (? IS NULL OR actor_id = ?)
          AND (? IS NULL OR target_user_id = ?)
          AND (? IS NULL OR target_role_id = ?)
          AND (
              ? IS NULL OR EXISTS (
                  SELECT 1
                  FROM ai_event_recipients AS recipient
                  WHERE recipient.event_id = ai_event_log.id
                    AND recipient.user_id = ?
              )
          )
          AND (? IS NULL OR channel_id = ?)
          AND (? IS NULL OR message_id = ?)
          AND (? IS NULL OR summary LIKE ? OR details LIKE ? OR actor_name LIKE ?)
        ORDER BY ts DESC, id DESC
        LIMIT ?
        """,
        (
            guild_filter,
            guild_filter,
            event_filter,
            event_filter,
            actor_filter,
            actor_filter,
            user_filter,
            user_filter,
            role_filter,
            role_filter,
            recipient_filter,
            recipient_filter,
            channel_filter,
            channel_filter,
            message_filter,
            message_filter,
            query_filter,
            query_filter,
            query_filter,
            query_filter,
            capped_limit,
        ),
    )
    rows = await cursor.fetchall()
    keys = [
        "id", "ts", "guild_id", "event_type", "actor_id", "actor_name",
        "target_user_id", "target_role_id", "channel_id", "message_id",
        "summary", "details", "deleted",
    ]
    return [dict(zip(keys, row)) for row in rows]


# ---------------------------------------------------------------------------
# Backup / Restore database using a Discord channel as persistent storage
# ---------------------------------------------------------------------------
# #13: Бэкап базы идёт в отдельный канал, НЕ совпадающий с логами модерации.
# Если переменная среды не задана — бэкап отключен и данные хранятся только локально.
def _safe_env_int(name: str, default: int = 0) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid integer in %s; using %s.", name, default)
        return default


BACKUP_CHANNEL_ID = _safe_env_int("DB_BACKUP_CHANNEL_ID") or 0
_SQLITE_MAGIC = b"SQLite format 3"  # первые 15 байт любого валидного файла SQLite
_BACKUP_MARKER = "[DATABASE_BACKUP]"
_BACKUP_HASH_RE = re.compile(r"\bsha256=([0-9a-f]{64})\b", re.IGNORECASE)
_MAX_BACKUP_BYTES = 100 * 1024 * 1024
# Сколько последних бэкапов держать в канале (бэкап каждые 10 минут копится вечно
# и захламляет канал — старые сообщения подчищаем после успешной загрузки).
_BACKUP_KEEP_LAST = 50
_backup_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()
# Если канал бэкапов настроен, upload запрещён до безопасного restore/no-backup
# результата. Это защищает не только loop, но и shutdown/P.OS shutdown пути.
_backup_uploads_allowed = not bool(BACKUP_CHANNEL_ID)
_backup_disabled_warning_emitted = False


def _warn_backup_disabled_once() -> None:
    global _backup_disabled_warning_emitted
    if _backup_disabled_warning_emitted:
        return
    _backup_disabled_warning_emitted = True
    logger.warning(
        "Резервное копирование базы отключено: DB_BACKUP_CHANNEL_ID не настроен. "
        "SQLite остаётся только на локальном диске и может быть потеряна при перезапуске "
        "хостинга с временным диском."
    )


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compress_file(source_path: str, destination_path: str) -> None:
    with open(source_path, "rb") as source, open(destination_path, "wb") as output:
        with gzip.GzipFile(
            filename="bot_data.db",
            mode="wb",
            fileobj=output,
            compresslevel=6,
            mtime=0,
        ) as compressed:
            shutil.copyfileobj(source, compressed, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())


def _write_restore_payload(path: str, raw: bytes, *, compressed: bool) -> int:
    total = 0
    with open(path, "wb") as output:
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_BACKUP_BYTES:
                        raise ValueError("decompressed database exceeds the size limit")
                    output.write(chunk)
        else:
            total = len(raw)
            if total > _MAX_BACKUP_BYTES:
                raise ValueError("database exceeds the size limit")
            output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return total


def _sqlite_quick_check(path: str) -> tuple[bool, str]:
    try:
        uri = f"file:{os.path.abspath(path)}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            rows = connection.execute("PRAGMA quick_check").fetchall()
            if rows == [("ok",)]:
                return True, "ok"
            details = "; ".join(str(row[0]) for row in rows[:5]) or "empty quick_check result"
            return False, details
        finally:
            connection.close()
    except Exception as exc:
        return False, str(exc)


async def _create_consistent_snapshot(db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Сделать целостный снапшот БД через VACUUM INTO.

    Копирование живого файла при активном WAL может дать несогласованную базу.
    VACUUM INTO создаёт согласованную копию даже во время записи.
    Возвращает путь к временному файлу-снапшоту (его нужно удалить после загрузки).
    """
    snapshot_path = f"{db_path}.backup"
    async with _loop_lock(_write_locks):
        try:
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
        except OSError:
            pass
        try:
            conn = await _get_conn(db_path)
            # Параметризовать имя файла в VACUUM INTO нельзя — экранируем кавычки вручную.
            safe_path = snapshot_path.replace("'", "''")
            await conn.execute(f"VACUUM INTO '{safe_path}'")
            return snapshot_path
        except Exception:
            logger.exception("Не удалось создать согласованный снапшот БД.")
            return None


async def _resolve_backup_channel(bot: discord.Client) -> discord.TextChannel | None:
    channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(BACKUP_CHANNEL_ID)
        except Exception:
            channel = None
    return channel if isinstance(channel, discord.TextChannel) else None


async def backup_db_to_discord(bot: discord.Client, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Upload a consistent snapshot of the DB to the dedicated backup channel."""
    async with _loop_lock(_backup_locks):
        # #13: Не делаем бэкап, если канал не настроен
        if not BACKUP_CHANNEL_ID:
            _warn_backup_disabled_once()
            return False
        if not _backup_uploads_allowed:
            logger.warning("Database backup blocked: restore has not completed safely.")
            return False
        channel = await _resolve_backup_channel(bot)
        if not channel:
            logger.warning(f"Database backup failed: channel {BACKUP_CHANNEL_ID} not found.")
            return False

        if not os.path.exists(db_path):
            logger.warning(f"Database backup failed: {db_path} does not exist.")
            return False

        snapshot_path = await _create_consistent_snapshot(db_path)
        if not snapshot_path or not os.path.exists(snapshot_path):
            logger.warning("Database backup failed: snapshot was not created.")
            return False

        compressed_path = f"{snapshot_path}.gz"
        try:
            snapshot_size = os.path.getsize(snapshot_path)
            if snapshot_size <= 0 or snapshot_size > _MAX_BACKUP_BYTES:
                logger.error("Database backup rejected: invalid snapshot size %s bytes.", snapshot_size)
                return False
            await asyncio.to_thread(_compress_file, snapshot_path, compressed_path)
            compressed_size = os.path.getsize(compressed_path)
            if compressed_size <= 0 or compressed_size > _MAX_BACKUP_BYTES:
                logger.error("Database backup rejected: invalid compressed size %s bytes.", compressed_size)
                return False
            upload_limit = int(getattr(getattr(channel, "guild", None), "filesize_limit", 0) or 0)
            if upload_limit > 0 and compressed_size > upload_limit:
                logger.error(
                    "Database backup is %s bytes after gzip, above Discord limit %s bytes.",
                    compressed_size,
                    upload_limit,
                )
                return False
            snapshot_hash = await asyncio.to_thread(_sha256_file, compressed_path)
            file = discord.File(compressed_path, filename="bot_data.db.gz")
            try:
                await channel.send(
                    content=(
                        f"{_BACKUP_MARKER} Automatic database backup encoding=gzip "
                        f"sha256={snapshot_hash} size={compressed_size} "
                        f"original_size={snapshot_size}"
                    ),
                    file=file,
                )
            finally:
                file.close()
            logger.info("Database backup uploaded to Discord successfully.")
            try:
                await _prune_old_backups(channel, bot)
            except Exception as e:
                logger.warning(f"Не удалось подчистить старые бэкапы: {e}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload database backup to Discord: {e}")
            return False
        finally:
            for temporary_path in (snapshot_path, compressed_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass


async def _prune_old_backups(channel: discord.TextChannel, bot: discord.Client) -> None:
    """Удалить старые бэкап-сообщения бота, оставив последние _BACKUP_KEEP_LAST."""
    bot_user_id = bot.user.id if bot.user else None
    if bot_user_id is None:
        return
    backups: list[discord.Message] = []
    async for msg in channel.history(limit=200):
        if msg.author.id != bot_user_id:
            continue
        if not msg.content.startswith(_BACKUP_MARKER):
            continue
        backups.append(msg)
    # history отдаёт от новых к старым — всё после первых _BACKUP_KEEP_LAST удаляем.
    for msg in backups[_BACKUP_KEEP_LAST:]:
        try:
            await msg.delete()
        except Exception:
            pass


async def restore_db_from_discord(bot: discord.Client, db_path: str = DEFAULT_DB_PATH) -> bool | None:
    """Scan the backup channel for the latest backup uploaded BY THE BOT and restore it.

    Return values:
    - True: backup restored.
    - False: restore is intentionally skipped or no backup exists.
    - None: restore was configured but failed/was unsafe; callers must not upload
      a fresh backup over the last known good copy yet.
    """
    global _backup_uploads_allowed
    async with _loop_lock(_backup_locks):
        if not BACKUP_CHANNEL_ID:
            _backup_uploads_allowed = True
            _warn_backup_disabled_once()
            return False
        channel = await _resolve_backup_channel(bot)
        if not channel:
            _backup_uploads_allowed = False
            logger.warning("Database restore failed: channel %s not found.", BACKUP_CHANNEL_ID)
            return None

        bot_user_id = bot.user.id if bot.user else None
        if bot_user_id is None:
            _backup_uploads_allowed = False
            logger.error("Database restore attempted before Discord login completed.")
            return None

        saw_candidate = False
        rejected_candidates: list[str] = []
        try:
            async for msg in channel.history(limit=50):
                if msg.author.id != bot_user_id:
                    continue
                content = str(msg.content or "")
                if not content.startswith(_BACKUP_MARKER) or not msg.attachments:
                    continue
                att = msg.attachments[0]
                if att.filename not in {"bot_data.db", "bot_data.db.gz"}:
                    continue
                saw_candidate = True
                candidate_label = f"message={msg.id}"

                try:
                    if att.size and att.size > _MAX_BACKUP_BYTES:
                        raise ValueError(f"file too large: {att.size} bytes")
                    raw = await att.read()
                    if not raw or len(raw) > _MAX_BACKUP_BYTES:
                        raise ValueError(f"invalid downloaded size: {len(raw)} bytes")
                    compressed = att.filename == "bot_data.db.gz"
                    if not compressed and not raw.startswith(_SQLITE_MAGIC):
                        raise ValueError("SQLite magic bytes missing")

                    expected_match = _BACKUP_HASH_RE.search(content)
                    if "sha256=" in content.lower() and not expected_match:
                        raise ValueError("malformed SHA-256 metadata")
                    actual_hash = hashlib.sha256(raw).hexdigest()
                    if expected_match and actual_hash.lower() != expected_match.group(1).lower():
                        raise ValueError("SHA-256 mismatch")

                    db_dir = os.path.dirname(os.path.abspath(db_path)) or "."
                    fd, temp_path = tempfile.mkstemp(prefix=".pos-restore-", suffix=".db", dir=db_dir)
                    os.close(fd)
                    try:
                        restored_size = await asyncio.to_thread(
                            _write_restore_payload,
                            temp_path,
                            raw,
                            compressed=compressed,
                        )
                        if restored_size <= 0:
                            raise ValueError("restored database is empty")
                        with open(temp_path, "rb") as restored_file:
                            if not restored_file.read(len(_SQLITE_MAGIC)).startswith(_SQLITE_MAGIC):
                                raise ValueError("SQLite magic bytes missing")
                        valid, check_details = await asyncio.to_thread(_sqlite_quick_check, temp_path)
                        if not valid:
                            raise ValueError(f"SQLite quick_check failed: {check_details}")

                        await close_all_connections()
                        for suffix in ("-wal", "-shm"):
                            side = f"{db_path}{suffix}"
                            if os.path.exists(side):
                                try:
                                    os.remove(side)
                                except OSError:
                                    pass

                        rollback_path = f"{db_path}.restore-rollback-{os.getpid()}-{time.time_ns()}"
                        had_original = os.path.exists(db_path)
                        if had_original:
                            os.replace(db_path, rollback_path)
                        try:
                            os.replace(temp_path, db_path)
                            temp_path = ""
                            await init_db(db_path)
                        except Exception:
                            await close_all_connections()
                            for suffix in ("-wal", "-shm"):
                                side = f"{db_path}{suffix}"
                                if os.path.exists(side):
                                    try:
                                        os.remove(side)
                                    except OSError:
                                        pass
                            if had_original and os.path.exists(rollback_path):
                                os.replace(rollback_path, db_path)
                                await init_db(db_path)
                            elif not had_original and os.path.exists(db_path):
                                try:
                                    os.remove(db_path)
                                except OSError:
                                    pass
                            raise
                        else:
                            if had_original and os.path.exists(rollback_path):
                                try:
                                    os.remove(rollback_path)
                                except OSError:
                                    pass

                        _backup_uploads_allowed = True
                        if not expected_match:
                            logger.warning("Restored legacy database backup without SHA-256 metadata (%s).", candidate_label)
                        logger.info("Database successfully restored from Discord backup (%s).", candidate_label)
                        return True
                    finally:
                        if temp_path and os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except OSError:
                                pass
                except Exception as exc:
                    reason = f"{candidate_label}: {exc}"
                    rejected_candidates.append(reason)
                    logger.warning("Skipping invalid database backup %s", reason)
                    continue

            if saw_candidate:
                _backup_uploads_allowed = False
                logger.error(
                    "No valid database backup found; rejected %s candidate(s).",
                    len(rejected_candidates),
                )
                return None

            logger.info("No database backup found in history.")
            _backup_uploads_allowed = True
            return False
        except Exception as exc:
            _backup_uploads_allowed = False
            logger.error("Failed to restore database from Discord: %s", exc, exc_info=True)
            return None
