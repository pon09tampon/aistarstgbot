import asyncio
import asyncpg
import sys

# Скрипт для переноса данных между двумя базами данных PostgreSQL (например, с одного аккаунта Render на другой)

async def migrate():
    print("Скрипт переноса данных PostgreSQL ➜ PostgreSQL")
    print("------------------------------------------------")
    
    old_url = input("Введите External Connection URL старой базы (postgres://): ").strip()
    new_url = input("Введите External Connection URL новой базы (postgres://): ").strip()
    
    if not old_url or not new_url:
        print("❌ Оба URL обязательны для заполнения.")
        return

    print("\n1. Подключение к старой базе данных...")
    try:
        old_conn = await asyncpg.connect(old_url)
        print("   Успешно подключено к старой базе!")
    except Exception as e:
        print(f"❌ Ошибка подключения к старой базе: {e}")
        return

    print("2. Подключение к новой базе данных...")
    try:
        new_conn = await asyncpg.connect(new_url)
        print("   Успешно подключено к новой базе!")
    except Exception as e:
        print(f"❌ Ошибка подключения к новой базе: {e}")
        await old_conn.close()
        return

    print("\n3. Создание таблиц в новой базе данных (если не созданы)...")
    await new_conn.execute("""
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
    await new_conn.execute("""
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
    await new_conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    await new_conn.execute("""
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

    print("\n4. Начало переноса данных...")

    # 1. Перенос users
    try:
        print("⏳ Перенос таблицы users...")
        users = await old_conn.fetch("SELECT * FROM users")
        await new_conn.execute("TRUNCATE TABLE users CASCADE")
        for u in users:
            await new_conn.execute("""
                INSERT INTO users (
                    user_id, username, first_name, subscription_type, payment_currency, 
                    payment_amount, activated_at, expires_at, is_forever, 
                    vpn_subscription_type, vpn_activated_at, vpn_expires_at, vpn_is_forever, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """, 
            u['user_id'], u['username'], u['first_name'], u['subscription_type'], u['payment_currency'],
            u['payment_amount'], u['activated_at'], u['expires_at'], u['is_forever'],
            u['vpn_subscription_type'], u['vpn_activated_at'], u['vpn_expires_at'], u['vpn_is_forever'], u['created_at'])
        print(f"   ✅ Перенесено пользователей: {len(users)}")
    except Exception as e:
        print(f"   ❌ Ошибка при переносе users: {e}")

    # 2. Перенос settings
    try:
        print("⏳ Перенос настроек...")
        settings = await old_conn.fetch("SELECT * FROM settings")
        await new_conn.execute("TRUNCATE TABLE settings CASCADE")
        for s in settings:
            await new_conn.execute("""
                INSERT INTO settings (key, value) VALUES ($1, $2)
            """, s['key'], s['value'])
        print(f"   ✅ Перенесено настроек: {len(settings)}")
    except Exception as e:
        print(f"   ❌ Ошибка при переносе settings: {e}")

    # 3. Перенос payments
    try:
        print("⏳ Перенос таблицы payments...")
        payments = await old_conn.fetch("SELECT * FROM payments")
        await new_conn.execute("TRUNCATE TABLE payments CASCADE")
        for p in payments:
            await new_conn.execute("""
                INSERT INTO payments (
                    id, user_id, payment_type, currency, amount, period, product, status, created_at, confirmed_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """, p['id'], p['user_id'], p['payment_type'], p['currency'], p['amount'], p['period'], p['product'], p['status'], p['created_at'], p['confirmed_at'])
        
        if payments:
            max_id = max(p['id'] for p in payments)
            await new_conn.execute(f"SELECT setval('payments_id_seq', {max_id})")
        print(f"   ✅ Перенесено платежей: {len(payments)}")
    except Exception as e:
        print(f"   ❌ Ошибка при переносе payments: {e}")

    # 4. Перенос support_tickets
    try:
        print("⏳ Перенос таблицы support_tickets...")
        tickets = await old_conn.fetch("SELECT * FROM support_tickets")
        await new_conn.execute("TRUNCATE TABLE support_tickets CASCADE")
        for t in tickets:
            await new_conn.execute("""
                INSERT INTO support_tickets (
                    id, user_id, username, message_text, reply_text, status, created_at, replied_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, t['id'], t['user_id'], t['username'], t['message_text'], t['reply_text'], t['status'], t['created_at'], t['replied_at'])
        
        if tickets:
            max_id = max(t['id'] for t in tickets)
            await new_conn.execute(f"SELECT setval('support_tickets_id_seq', {max_id})")
        print(f"   ✅ Перенесено тикетов: {len(tickets)}")
    except Exception as e:
        print(f"   ❌ Ошибка при переносе support_tickets: {e}")

    await old_conn.close()
    await new_conn.close()
    print("\n🎉 Все данные успешно перенесены в новую базу данных PostgreSQL!")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(migrate())
