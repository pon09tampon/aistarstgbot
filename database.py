"""
Модуль работы с базой данных (SQLite / PostgreSQL) для AiStars Bot
"""

import os
import logging
from datetime import datetime, timedelta
import aiosqlite
from config import DATABASE_PATH, DATABASE_URL

logger = logging.getLogger(__name__)

PG_URL = DATABASE_URL
if PG_URL and PG_URL.startswith("postgres://"):
    PG_URL = PG_URL.replace("postgres://", "postgresql://", 1)

_pg_pool = None


async def get_pg_pool():
    global _pg_pool
    if _pg_pool is None and PG_URL:
        import asyncpg
        _pg_pool = await asyncpg.create_pool(PG_URL)
    return _pg_pool


async def init_db():
    """Инициализация базы данных и создание таблиц."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    subscription_type TEXT DEFAULT NULL,
                    payment_currency TEXT DEFAULT NULL,
                    payment_amount DOUBLE PRECISION DEFAULT 0,
                    activated_at TEXT DEFAULT NULL,
                    expires_at TEXT DEFAULT NULL,
                    is_forever INTEGER DEFAULT 0,
                    vpn_subscription_type TEXT DEFAULT NULL,
                    vpn_activated_at TEXT DEFAULT NULL,
                    vpn_expires_at TEXT DEFAULT NULL,
                    vpn_is_forever INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Upgrade existing schema if needed
            for col, col_type in [
                ("vpn_subscription_type", "TEXT DEFAULT NULL"),
                ("vpn_activated_at", "TEXT DEFAULT NULL"),
                ("vpn_expires_at", "TEXT DEFAULT NULL"),
                ("vpn_is_forever", "INTEGER DEFAULT 0"),
            ]:
                try:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {col_type}")
                except Exception:
                    pass
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    payment_type TEXT,
                    currency TEXT,
                    amount DOUBLE PRECISION,
                    period TEXT,
                    product TEXT DEFAULT 'aistars',
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TEXT DEFAULT NULL
                )
            """)
            try:
                await conn.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS product TEXT DEFAULT 'aistars'")
            except Exception:
                pass
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    username TEXT,
                    message_text TEXT,
                    reply_text TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    replied_at TEXT DEFAULT NULL
                )
            """)
            await conn.execute("""
                INSERT INTO settings (key, value) VALUES ('card_number', '0000 0000 0000 0000')
                ON CONFLICT (key) DO NOTHING
            """)
            logger.info("✅ PostgreSQL база данных успешно инициализирована!")
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    subscription_type TEXT DEFAULT NULL,
                    payment_currency TEXT DEFAULT NULL,
                    payment_amount REAL DEFAULT 0,
                    activated_at TEXT DEFAULT NULL,
                    expires_at TEXT DEFAULT NULL,
                    is_forever INTEGER DEFAULT 0,
                    vpn_subscription_type TEXT DEFAULT NULL,
                    vpn_activated_at TEXT DEFAULT NULL,
                    vpn_expires_at TEXT DEFAULT NULL,
                    vpn_is_forever INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Upgrade existing sqlite schema if needed
            for col, col_type in [
                ("vpn_subscription_type", "TEXT DEFAULT NULL"),
                ("vpn_activated_at", "TEXT DEFAULT NULL"),
                ("vpn_expires_at", "TEXT DEFAULT NULL"),
                ("vpn_is_forever", "INTEGER DEFAULT 0"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                except Exception:
                    pass
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    payment_type TEXT,
                    currency TEXT,
                    amount REAL,
                    period TEXT,
                    product TEXT DEFAULT 'aistars',
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TEXT DEFAULT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            try:
                await db.execute("ALTER TABLE payments ADD COLUMN product TEXT DEFAULT 'aistars'")
            except Exception:
                pass
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    message_text TEXT,
                    reply_text TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    replied_at TEXT DEFAULT NULL
                )
            """)
            await db.execute("""
                INSERT OR IGNORE INTO settings (key, value) VALUES ('card_number', '0000 0000 0000 0000')
            """)
            await db.commit()
            logger.info("✅ SQLite база данных успешно инициализирована!")


async def get_setting(key: str, default: str = "") -> str:
    """Получить значение настройки."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT value FROM settings WHERE key = $1", key)
            return val if val is not None else default
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    """Установить значение настройки."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, key, str(value))
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            await db.commit()


async def get_or_create_user(user_id: int, username: str = None, first_name: str = None) -> dict:
    """Получить или создать пользователя."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            if row:
                return dict(row)
            await conn.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES ($1, $2, $3)",
                user_id, username, first_name,
            )
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return dict(row)
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()

            if row:
                return dict(row)

            await db.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                (user_id, username, first_name),
            )
            await db.commit()

            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return dict(row)


async def get_all_user_ids() -> list:
    """Получить список всех ID пользователей (для рассылки)."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users")
            return [r["user_id"] for r in rows]
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT user_id FROM users")
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def add_subscription(
    user_id: int,
    period: str,
    currency: str,
    amount: float,
    product: str = "aistars",
) -> None:
    """Активировать подписку пользователю."""
    now = datetime.now()
    is_forever = 1 if period == "forever" else 0
    days = 90 if period == "3month" else 30
    expires_at = None if is_forever else (now + timedelta(days=days)).isoformat()

    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if product == "vpn":
                await conn.execute(
                    """
                    UPDATE users SET
                        vpn_subscription_type = $1,
                        payment_currency = $2,
                        payment_amount = $3,
                        vpn_activated_at = $4,
                        vpn_expires_at = $5,
                        vpn_is_forever = $6
                    WHERE user_id = $7
                    """,
                    period, currency, amount, now.isoformat(), expires_at, is_forever, user_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE users SET
                        subscription_type = $1,
                        payment_currency = $2,
                        payment_amount = $3,
                        activated_at = $4,
                        expires_at = $5,
                        is_forever = $6
                    WHERE user_id = $7
                    """,
                    period, currency, amount, now.isoformat(), expires_at, is_forever, user_id,
                )
            await conn.execute(
                """
                INSERT INTO payments (user_id, payment_type, currency, amount, period, product, status, confirmed_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'confirmed', $7)
                """,
                user_id, "payment", currency, amount, period, product, now.isoformat(),
            )
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if product == "vpn":
                await db.execute(
                    """
                    UPDATE users SET
                        vpn_subscription_type = ?,
                        payment_currency = ?,
                        payment_amount = ?,
                        vpn_activated_at = ?,
                        vpn_expires_at = ?,
                        vpn_is_forever = ?
                    WHERE user_id = ?
                    """,
                    (period, currency, amount, now.isoformat(), expires_at, is_forever, user_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE users SET
                        subscription_type = ?,
                        payment_currency = ?,
                        payment_amount = ?,
                        activated_at = ?,
                        expires_at = ?,
                        is_forever = ?
                    WHERE user_id = ?
                    """,
                    (period, currency, amount, now.isoformat(), expires_at, is_forever, user_id),
                )
            await db.execute(
                """
                INSERT INTO payments (user_id, payment_type, currency, amount, period, product, status, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?)
                """,
                (user_id, "payment", currency, amount, period, product, now.isoformat()),
            )
            await db.commit()


async def check_subscription(user_id: int, product: str = "aistars") -> dict:
    """Проверить статус подписки."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            if not row:
                return {"active": False, "type": None, "expires_at": None}
            user = dict(row)
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                return {"active": False, "type": None, "expires_at": None}
            user = dict(row)

    if product == "vpn":
        is_forever = user.get("vpn_is_forever", 0)
        expires_at = user.get("vpn_expires_at")
        sub_type = user.get("vpn_subscription_type")
    else:
        is_forever = user.get("is_forever", 0)
        expires_at = user.get("expires_at")
        sub_type = user.get("subscription_type")

    if is_forever:
        return {
            "active": True,
            "type": "forever",
            "expires_at": None,
            "currency": user["payment_currency"],
        }

    if expires_at:
        expires = datetime.fromisoformat(expires_at)
        if expires > datetime.now():
            return {
                "active": True,
                "type": sub_type or "month",
                "expires_at": expires_at,
                "currency": user["payment_currency"],
            }

    return {"active": False, "type": None, "expires_at": None}


async def create_pending_payment(user_id: int, currency: str, amount: float, period: str, product: str = "aistars") -> int:
    """Создать ожидающий платёж."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                """
                INSERT INTO payments (user_id, payment_type, currency, amount, period, product, status)
                VALUES ($1, 'manual', $2, $3, $4, $5, 'pending')
                RETURNING id
                """,
                user_id, currency, amount, period, product,
            )
            return val
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                INSERT INTO payments (user_id, payment_type, currency, amount, period, product, status)
                VALUES (?, 'manual', ?, ?, ?, ?, 'pending')
                """,
                (user_id, currency, amount, period, product),
            )
            await db.commit()
            return cursor.lastrowid


async def confirm_payment(payment_id: int) -> dict | None:
    """Подтвердить платёж (администратором)."""
    now = datetime.now()
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM payments WHERE id = $1 AND status = 'pending'", payment_id)
            if not row:
                return None
            payment = dict(row)
            await conn.execute(
                "UPDATE payments SET status = 'confirmed', confirmed_at = $1 WHERE id = $2",
                now.isoformat(), payment_id,
            )
            await add_subscription(
                payment["user_id"],
                payment["period"],
                payment["currency"],
                payment["amount"],
                payment.get("product", "aistars"),
            )
            return payment
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM payments WHERE id = ? AND status = 'pending'", (payment_id,))
            payment = await cursor.fetchone()

            if not payment:
                return None

            payment = dict(payment)
            await db.execute(
                "UPDATE payments SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
                (now.isoformat(), payment_id),
            )
            await db.commit()

            await add_subscription(
                payment["user_id"],
                payment["period"],
                payment["currency"],
                payment["amount"],
                payment.get("product", "aistars"),
            )
            return payment


async def reject_payment(payment_id: int) -> dict | None:
    """Отклонить платёж (администратором)."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM payments WHERE id = $1 AND status = 'pending'", payment_id)
            if not row:
                return None
            payment = dict(row)
            await conn.execute("UPDATE payments SET status = 'rejected' WHERE id = $1", payment_id)
            return payment
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM payments WHERE id = ? AND status = 'pending'", (payment_id,))
            payment = await cursor.fetchone()

            if not payment:
                return None

            payment = dict(payment)
            await db.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (payment_id,))
            await db.commit()
            return payment


async def get_pending_payments() -> list:
    """Получить все ожидающие платежи."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.*, u.username, u.first_name
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.status = 'pending'
                ORDER BY p.created_at DESC
                """
            )
            return [dict(r) for r in rows]
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT p.*, u.username, u.first_name
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.status = 'pending'
                ORDER BY p.created_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def create_support_ticket(user_id: int, username: str, message_text: str) -> int:
    """Создать обращение в поддержку."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                """
                INSERT INTO support_tickets (user_id, username, message_text, status)
                VALUES ($1, $2, $3, 'open')
                RETURNING id
                """,
                user_id, username, message_text,
            )
            return val
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                INSERT INTO support_tickets (user_id, username, message_text, status)
                VALUES (?, ?, ?, 'open')
                """,
                (user_id, username, message_text),
            )
            await db.commit()
            return cursor.lastrowid


async def get_open_tickets() -> list:
    """Получить все открытые тикеты поддержки."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM support_tickets WHERE status = 'open' ORDER BY created_at DESC")
            return [dict(r) for r in rows]
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM support_tickets WHERE status = 'open' ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def reply_support_ticket(ticket_id: int, reply_text: str) -> dict | None:
    """Ответить на тикет поддержки."""
    now = datetime.now()
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM support_tickets WHERE id = $1 AND status = 'open'", ticket_id)
            if not row:
                return None
            ticket = dict(row)
            await conn.execute(
                "UPDATE support_tickets SET reply_text = $1, status = 'closed', replied_at = $2 WHERE id = $3",
                reply_text, now.isoformat(), ticket_id,
            )
            return ticket
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM support_tickets WHERE id = ? AND status = 'open'", (ticket_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            ticket = dict(row)

            await db.execute(
                "UPDATE support_tickets SET reply_text = ?, status = 'closed', replied_at = ? WHERE id = ?",
                (reply_text, now.isoformat(), ticket_id),
            )
            await db.commit()
            return ticket


async def clear_all_pending_payments() -> int:
    """Удалить все платежи и сбросить нумерацию заказов."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            count_val = await conn.fetchval("SELECT COUNT(*) FROM payments")
            await conn.execute("TRUNCATE TABLE payments RESTART IDENTITY")
            return count_val or 0
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("DELETE FROM payments")
            count = cursor.rowcount
            try:
                await db.execute("DELETE FROM sqlite_sequence WHERE name = 'payments'")
            except Exception:
                pass
            await db.commit()
            return count


async def clear_all_open_tickets() -> int:
    """Удалить все тикеты поддержки и сбросить нумерацию."""
    if PG_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            count_val = await conn.fetchval("SELECT COUNT(*) FROM support_tickets")
            await conn.execute("TRUNCATE TABLE support_tickets RESTART IDENTITY")
            return count_val or 0
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("DELETE FROM support_tickets")
            count = cursor.rowcount
            try:
                await db.execute("DELETE FROM sqlite_sequence WHERE name = 'support_tickets'")
            except Exception:
                pass
            await db.commit()
            return count

