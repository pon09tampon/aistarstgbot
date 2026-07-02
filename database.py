"""
Модуль работы с базой данных SQLite для AI Stars Bot
"""

import aiosqlite
from datetime import datetime, timedelta
from config import DATABASE_PATH


async def init_db():
    """Инициализация базы данных и создание таблиц."""
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                payment_type TEXT,
                currency TEXT,
                amount REAL,
                period TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TEXT DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


async def get_or_create_user(user_id: int, username: str = None, first_name: str = None) -> dict:
    """Получить или создать пользователя."""
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


async def add_subscription(
    user_id: int,
    period: str,
    currency: str,
    amount: float,
) -> None:
    """Активировать подписку пользователю.
    
    period: 'month' или 'forever'
    """
    now = datetime.now()
    is_forever = 1 if period == "forever" else 0
    expires_at = None if is_forever else (now + timedelta(days=30)).isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
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
            INSERT INTO payments (user_id, payment_type, currency, amount, period, status, confirmed_at)
            VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (user_id, "payment", currency, amount, period, now.isoformat()),
        )
        await db.commit()


async def check_subscription(user_id: int) -> dict:
    """Проверить статус подписки.
    
    Returns: dict с ключами 'active', 'type', 'expires_at'
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

        if not row:
            return {"active": False, "type": None, "expires_at": None}

        user = dict(row)

        if user["is_forever"]:
            return {
                "active": True,
                "type": "forever",
                "expires_at": None,
                "currency": user["payment_currency"],
            }

        if user["expires_at"]:
            expires = datetime.fromisoformat(user["expires_at"])
            if expires > datetime.now():
                return {
                    "active": True,
                    "type": "month",
                    "expires_at": user["expires_at"],
                    "currency": user["payment_currency"],
                }

        return {"active": False, "type": None, "expires_at": None}


async def create_pending_payment(user_id: int, currency: str, amount: float, period: str) -> int:
    """Создать ожидающий платёж (для ручной проверки RUB/USD)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO payments (user_id, payment_type, currency, amount, period, status)
            VALUES (?, 'manual', ?, ?, ?, 'pending')
            """,
            (user_id, currency, amount, period),
        )
        await db.commit()
        return cursor.lastrowid


async def confirm_payment(payment_id: int) -> dict | None:
    """Подтвердить платёж (администратором)."""
    now = datetime.now()
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

        # Активируем подписку
        await add_subscription(
            payment["user_id"],
            payment["period"],
            payment["currency"],
            payment["amount"],
        )
        return payment


async def get_pending_payments() -> list:
    """Получить все ожидающие платежи."""
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
