"""
Конфигурация бота AI Stars
"""

import os

# ===== ОСНОВНЫЕ НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "8263618011:AAGyH2h7ziuiWmtcV6EE-DS-stwH3L-CfqU")
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN", "604050:AAUxXlusqiyuAKHvxZHoAp4KAGfjxmzAvBl")

# ADMIN_IDS: массив чисел ID администраторов
admin_ids_env = os.getenv("ADMIN_IDS", "8440278509")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_env.split(",") if x.strip().isdigit()]

# WEBAPP_URL: автоопределение при деплое на Render
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
if RENDER_URL:
    WEBAPP_URL = RENDER_URL if RENDER_URL.endswith("/") else f"{RENDER_URL}/"
else:
    WEBAPP_URL = os.getenv("WEBAPP_URL", "YOUR_WEBAPP_URL_HERE")

# ===== БАЗА ДАННЫХ =====
DATABASE_PATH = os.getenv("DATABASE_PATH", "aistars.db")

# ===== ТАРИФЫ =====
PRICES = {
    "stars": {
        "month": {
            "amount": 200,
            "label": "Подписка на месяц (200 ⭐)",
            "currency": "XTR",
        },
        "forever": {
            "amount": 650,
            "label": "Навсегда (650 ⭐)",
            "currency": "XTR",
        },
    },
    "rub": {
        "month": {
            "amount": 250,
            "label": "Подписка на месяц (250 ₽)",
            "currency": "RUB",
        },
        "forever": {
            "amount": 800,
            "label": "Навсегда (800 ₽)",
            "currency": "RUB",
        },
    },
    "usd": {
        "month": {
            "amount": 3,
            "label": "Подписка на месяц ($3)",
            "currency": "USD",
        },
        "forever": {
            "amount": 10,
            "label": "Навсегда ($10)",
            "currency": "USD",
        },
    },
}
