import asyncio
import sqlite3
import asyncpg
import sys

# Скрипт для переноса локальной базы данных SQLite в PostgreSQL на Render

SQLITE_PATH = "aistars.db"

async def migrate():
    print("Скрипт переноса локальной SQLite БД в PostgreSQL на Render")
    print("-------------------------------------------------------")
    
    # Запрос URL базы данных
    pg_url = input("Введите External Database URL от Render (начинается с postgres://): ").strip()
    if not pg_url:
        print("❌ URL не может быть пустым.")
        return

    print(f"\n1. Подключение к локальной SQLite ({SQLITE_PATH})...")
    try:
        lite_conn = sqlite3.connect(SQLITE_PATH)
        lite_conn.row_factory = sqlite3.Row
        lite_cur = lite_conn.cursor()
        
        # Проверяем наличие таблиц
        lite_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r['name'] for r in lite_cur.fetchall()]
        print(f"   Найдено локальных таблиц: {', '.join(tables)}")
    except Exception as e:
        print(f"❌ Ошибка подключения к SQLite: {e}")
        return

    print("2. Подключение к удаленному PostgreSQL...")
    try:
        pg_conn = await asyncpg.connect(pg_url)
        print("   Успешно подключено к PostgreSQL!")
    except Exception as e:
        print(f"❌ Ошибка подключения к PostgreSQL: {e}")
        lite_conn.close()
        return

    print("\n3. Создание схемы таблиц в PostgreSQL (если они еще не созданы)...")
    # Создаем таблицы в PostgreSQL, если их нет
    await pg_conn.execute("""
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
    await pg_conn.execute("""
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
    await pg_conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    await pg_conn.execute("""
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

    # 1. Перенос таблицы users
    if 'users' in tables:
        print("\n⏳ Перенос таблицы users...")
        lite_cur.execute("SELECT * FROM users")
        users = lite_cur.fetchall()
        
        await pg_conn.execute("TRUNCATE TABLE users CASCADE")
        
        for user in users:
            await pg_conn.execute("""
                INSERT INTO users (
                    user_id, username, first_name, subscription_type, payment_currency, 
                    payment_amount, activated_at, expires_at, is_forever, 
                    vpn_subscription_type, vpn_activated_at, vpn_expires_at, vpn_is_forever, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """, 
            user['user_id'], user['username'], user['first_name'], user['subscription_type'], user['payment_currency'],
            user['payment_amount'], user['activated_at'], user['expires_at'], user['is_forever'],
            user['vpn_subscription_type'], user['vpn_activated_at'], user['vpn_expires_at'], user['vpn_is_forever'], user['created_at'])
        print(f"   ✅ Перенесено пользователей: {len(users)}")

    # 2. Перенос таблицы settings
    if 'settings' in tables:
        print("\n⏳ Перенос таблицы settings...")
        lite_cur.execute("SELECT * FROM settings")
        settings = lite_cur.fetchall()
        
        await pg_conn.execute("TRUNCATE TABLE settings CASCADE")
        for setting in settings:
            await pg_conn.execute("""
                INSERT INTO settings (key, value) VALUES ($1, $2)
            """, setting['key'], setting['value'])
        print(f"   ✅ Перенесено настроек: {len(settings)}")

    # 3. Перенос таблицы payments
    if 'payments' in tables:
        print("\n⏳ Перенос таблицы payments...")
        lite_cur.execute("SELECT * FROM payments")
        payments = lite_cur.fetchall()
        
        await pg_conn.execute("TRUNCATE TABLE payments CASCADE")
        for p in payments:
            await pg_conn.execute("""
                INSERT INTO payments (
                    id, user_id, payment_type, currency, amount, period, product, status, created_at, confirmed_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """, p['id'], p['user_id'], p['payment_type'], p['currency'], p['amount'], p['period'], p['product'], p['status'], p['created_at'], p['confirmed_at'])
        
        if payments:
            max_id = max(p['id'] for p in payments)
            await pg_conn.execute(f"SELECT setval('payments_id_seq', {max_id})")
        print(f"   ✅ Перенесено платежей: {len(payments)}")

    # 4. Перенос таблицы support_tickets
    if 'support_tickets' in tables:
        print("\n⏳ Перенос таблицы support_tickets...")
        lite_cur.execute("SELECT * FROM support_tickets")
        tickets = lite_cur.fetchall()
        
        await pg_conn.execute("TRUNCATE TABLE support_tickets CASCADE")
        for t in tickets:
            await pg_conn.execute("""
                INSERT INTO support_tickets (
                    id, user_id, username, message_text, reply_text, status, created_at, replied_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, t['id'], t['user_id'], t['username'], t['message_text'], t['reply_text'], t['status'], t['created_at'], t['replied_at'])
        
        if tickets:
            max_id = max(t['id'] for t in tickets)
            await pg_conn.execute(f"SELECT setval('support_tickets_id_seq', {max_id})")
        print(f"   ✅ Перенесено обращений: {len(tickets)}")

    lite_conn.close()
    await pg_conn.close()
    print("\n🎉 Все данные успешно перенесены в PostgreSQL!")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(migrate())
