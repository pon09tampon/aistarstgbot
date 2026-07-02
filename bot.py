"""
AI Stars Bot — Telegram-бот для продажи нейросети по Brawl Stars
"""

import asyncio
import json
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    MenuButtonWebApp,
    PreCheckoutQuery,
    WebAppInfo,
)
from aiogram.enums import ParseMode

from config import BOT_TOKEN, CRYPTO_PAY_TOKEN, ADMIN_IDS, WEBAPP_URL, PRICES
from crypto_pay import CryptoPay
from database import (
    init_db,
    get_or_create_user,
    add_subscription,
    check_subscription,
    create_pending_payment,
    confirm_payment,
    get_pending_payments,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
crypto_pay = CryptoPay(CRYPTO_PAY_TOKEN) if CRYPTO_PAY_TOKEN else None
dp = Dispatcher()

# ===== ПРОВЕРКА НАЛИЧИЯ WEBAPP URL =====
def is_webapp_configured() -> bool:
    return WEBAPP_URL and WEBAPP_URL != "YOUR_WEBAPP_URL_HERE" and WEBAPP_URL.startswith("https")


def get_shop_button():
    """Кнопка магазина — WebApp или инлайн."""
    if is_webapp_configured():
        return InlineKeyboardButton(
            text="🛒 Открыть магазин",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    else:
        return InlineKeyboardButton(
            text="🛒 Купить подписку",
            callback_data="shop",
        )


# ===== КОМАНДА /start =====
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Приветствие и кнопка Web App."""
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    # Проверим подписку
    sub = await check_subscription(message.from_user.id)

    if sub["active"]:
        status_text = "✅ У вас активная подписка!"
        if sub["type"] == "forever":
            status_text += "\n🔥 Тип: **Навсегда**"
        else:
            expires = datetime.fromisoformat(sub["expires_at"])
            status_text += f"\n📅 Действует до: **{expires.strftime('%d.%m.%Y')}**"
    else:
        status_text = "❌ У вас нет активной подписки"

    welcome_text = (
        f"🤖 **Привет, {message.from_user.first_name}!**\n\n"
        f"Добро пожаловать в бота для покупки подписки **AiStars**!\n\n"
        f"📊 **Статус подписки:** {status_text}\n\n"
        f"👇 Нажми кнопку ниже, чтобы купить подписку!"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [get_shop_button()],
            [
                InlineKeyboardButton(
                    text="📊 Мой статус",
                    callback_data="check_status",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Поддержка",
                    callback_data="support",
                )
            ],
        ]
    )

    await message.answer(
        welcome_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


# ===== ИНЛАЙН МАГАЗИН (без WebApp) =====
@dp.callback_query(F.data == "shop")
async def shop_callback(callback: types.CallbackQuery):
    """Магазин через инлайн-кнопки."""
    text = (
        "🛒 **Магазин AI Stars**\n\n"
        "Выберите валюту оплаты:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Звёзды Telegram", callback_data="currency_stars"),
            ],
            [
                InlineKeyboardButton(text="₽ Рубли", callback_data="currency_rub"),
            ],
            [
                InlineKeyboardButton(text="$ Доллары", callback_data="currency_usd"),
            ],
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"),
            ],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@dp.callback_query(F.data.startswith("currency_"))
async def currency_callback(callback: types.CallbackQuery):
    """Выбор тарифа после выбора валюты."""
    currency = callback.data.replace("currency_", "")

    currency_names = {"stars": "⭐ Звёзды", "rub": "₽ Рубли", "usd": "$ Доллары"}
    p = PRICES[currency]

    if currency == "stars":
        month_label = f"{p['month']['amount']} ⭐"
        forever_label = f"{p['forever']['amount']} ⭐"
    elif currency == "rub":
        month_label = f"{p['month']['amount']} ₽"
        forever_label = f"{p['forever']['amount']} ₽"
    else:
        month_label = f"${p['month']['amount']}"
        forever_label = f"${p['forever']['amount']}"

    text = (
        f"💎 **Тарифы ({currency_names[currency]})**\n\n"
        f"📅 **На месяц** — {month_label}\n"
        f"• Фарм кубков, автопуш 1-2-3 прайм\n"
        f"• Авто Уклонение + Аимбот 80%\n"
        f"• Работа 24/7, все режимы\n\n"
        f"♾️ **Навсегда** — {forever_label}\n"
        f"• Всё из подписки «На месяц»\n"
        f"• Приоритетная поддержка 24/7\n"
        f"• Гайд по окупу + Кфг владельца\n"
        f"• Ранний доступ к новым функциям"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📅 На месяц — {month_label}",
                    callback_data=f"buy_{currency}_month",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"♾️ Навсегда — {forever_label} 🔥",
                    callback_data=f"buy_{currency}_forever",
                ),
            ],
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="shop"),
            ],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def buy_callback(callback: types.CallbackQuery):
    """Обработка покупки через инлайн-кнопки."""
    parts = callback.data.split("_")  # buy_stars_month
    currency = parts[1]
    period = parts[2]
    price_info = PRICES[currency][period]

    if currency == "stars":
        # Оплата через Telegram Stars
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="AI Stars — Бот для Brawl Stars",
            description=price_info["label"],
            payload=json.dumps({
                "user_id": callback.from_user.id,
                "period": period,
                "currency": "XTR",
                "amount": price_info["amount"],
            }),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=price_info["label"], amount=price_info["amount"])],
        )
        await callback.answer()

    elif currency == "usd":
        if crypto_pay:
            try:
                invoice = await crypto_pay.create_invoice(
                    amount=price_info["amount"],
                    currency_type="fiat",
                    fiat="USD",
                    description=f"AI Stars — {price_info['label']}",
                    payload=json.dumps({"user_id": callback.from_user.id, "period": period, "amount": price_info["amount"]}),
                )
                invoice_id = invoice["invoice_id"]
                pay_url = invoice.get("bot_invoice_url") or invoice.get("mini_app_invoice_url") or invoice.get("pay_url")

                text = (
                    f"💎 **Оплата через CryptoBot**\n\n"
                    f"📦 Товар: AI Stars — {price_info['label']}\n"
                    f"💰 Сумма: **${price_info['amount']}**\n\n"
                    f"Нажмите кнопку ниже для оплаты через @CryptoBot.\n"
                    f"После оплаты нажмите кнопку «Проверить оплату»."
                )

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"💳 Оплатить ${price_info['amount']} в CryptoBot", url=pay_url)],
                        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_crypto_{invoice_id}_{period}")],
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="shop")],
                    ]
                )

                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                await callback.answer()
                return
            except Exception as e:
                logger.error(f"CryptoPay invoice error: {e}")

        # Фолбэк, если CryptoPay не сработал
        payment_id = await create_pending_payment(
            callback.from_user.id,
            price_info["currency"],
            price_info["amount"],
            period,
        )
        text = (
            f"🧾 **Заказ #{payment_id}**\n\n"
            f"📦 Товар: AI Stars — {price_info['label']}\n"
            f"💰 Сумма: **{price_info['amount']} $**\n\n"
            f"💳 **Payment details:**\n"
            f"• CryptoBot / Wallet\n\n"
            f"После оплаты нажмите /status или свяжитесь с администратором."
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        await callback.answer()

    elif currency == "rub":
        payment_id = await create_pending_payment(
            callback.from_user.id,
            price_info["currency"],
            price_info["amount"],
            period,
        )

        currency_symbol = "₽"
        payment_details = (
            "💳 **Реквизиты для оплаты:**\n"
            "• Банк: Сбер / Тинькофф\n"
            "• Номер карты: `XXXX XXXX XXXX XXXX`\n"
            "• Или по номеру телефона: `+7 (XXX) XXX-XX-XX`\n\n"
            "⚠️ **ВАЖНО:** В комментарии к переводу укажите:\n"
            f"`AI Stars #{payment_id}`"
        )

        text = (
            f"🧾 **Заказ #{payment_id}**\n\n"
            f"📦 Товар: AI Stars — {price_info['label']}\n"
            f"💰 Сумма: **{price_info['amount']} {currency_symbol}**\n\n"
            f"{payment_details}\n\n"
            f"После оплаты администратор проверит платёж и активирует подписку.\n"
            f"Обычно это занимает до 15 минут ⏱"
        )

        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        await callback.answer()

        # Уведомим админов
        for admin_id in ADMIN_IDS:
            try:
                admin_text = (
                    f"🔔 **Новый заказ #{payment_id}!**\n\n"
                    f"👤 Пользователь: @{callback.from_user.username or 'N/A'} "
                    f"(ID: `{callback.from_user.id}`)\n"
                    f"📦 Период: **{period}**\n"
                    f"💰 Сумма: **{price_info['amount']} {currency_symbol}**\n\n"
                    f"Для подтверждения:\n"
                    f"`/confirm {payment_id}`"
                )
                await bot.send_message(admin_id, admin_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")


@dp.callback_query(F.data == "back_start")
async def back_start_callback(callback: types.CallbackQuery):
    """Возврат к стартовому меню."""
    await callback.message.delete()
    await cmd_start(callback.message)
    await callback.answer()


# ===== ПРОВЕРКА ОПЛАТЫ CRYPTOPAY =====
@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_callback(callback: types.CallbackQuery):
    """Проверка статуса оплаты инвойса CryptoBot."""
    parts = callback.data.split("_")
    invoice_id = parts[2]
    period = parts[3]

    if not crypto_pay:
        await callback.answer("❌ Оплата через CryptoBot временно недоступна.", show_alert=True)
        return

    try:
        invoices = await crypto_pay.get_invoices(invoice_ids=invoice_id)
        if invoices:
            inv = invoices[0]
            status = inv.get("status")
            if status == "paid":
                amount = float(inv.get("amount", 0))
                await add_subscription(callback.from_user.id, period, "USD", amount)
                
                period_text = "навсегда 🔥" if period == "forever" else "на 1 месяц 📅"
                await callback.message.edit_text(
                    f"🎉 **Оплата прошла успешно!**\n\n"
                    f"✅ Подписка активирована **{period_text}**\n"
                    f"💫 Спасибо за покупку через CryptoBot!",
                    parse_mode=ParseMode.MARKDOWN
                )
                await callback.answer("✅ Подписка активирована!", show_alert=True)
                return
            elif status == "active":
                await callback.answer("⏳ Оплата ещё не поступила. Попробуйте после оплаты.", show_alert=True)
                return
            else:
                await callback.answer(f"Статус платежа: {status}", show_alert=True)
                return
        else:
            await callback.answer("❌ Инвойс не найден.", show_alert=True)
    except Exception as e:
        logger.error(f"Error checking crypto payment: {e}")
        await callback.answer("❌ Ошибка при проверке платежа.", show_alert=True)


# ===== ПРОВЕРКА СТАТУСА =====
@dp.callback_query(F.data == "check_status")
async def check_status_callback(callback: types.CallbackQuery):
    sub = await check_subscription(callback.from_user.id)

    if sub["active"]:
        if sub["type"] == "forever":
            text = "✅ **Подписка активна!**\n🔥 Тип: **Навсегда**\n\nВам доступны все функции нейросети."
        else:
            expires = datetime.fromisoformat(sub["expires_at"])
            days_left = (expires - datetime.now()).days
            text = (
                f"✅ **Подписка активна!**\n"
                f"📅 Тип: **На месяц**\n"
                f"⏳ Осталось: **{days_left} дней**\n"
                f"📆 Действует до: **{expires.strftime('%d.%m.%Y')}**"
            )
    else:
        text = (
            "❌ **Подписка не активна**\n\n"
            "Нажмите кнопку ниже, чтобы приобрести доступ!"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [get_shop_button()],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer()


# ===== ПОДДЕРЖКА =====
@dp.callback_query(F.data == "support")
async def support_callback(callback: types.CallbackQuery):
    text = (
        "💬 **Поддержка AI Stars**\n\n"
        "Опишите вашу проблему прямо в этом чате.\n\n"
        "Мы ответим в ближайшее время! 🙌"
    )
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


# ===== ОБРАБОТКА ДАННЫХ ИЗ WEB APP =====
@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    """Обработка данных, отправленных из Web App."""
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get("action")
        currency = data.get("currency")  # stars, rub, usd
        period = data.get("period")  # month, forever

        if action != "buy" or currency not in PRICES or period not in PRICES[currency]:
            await message.answer("❌ Неверные данные. Попробуйте ещё раз.")
            return

        price_info = PRICES[currency][period]

        if currency == "stars":
            # Оплата через Telegram Stars
            await bot.send_invoice(
                chat_id=message.from_user.id,
                title="AI Stars — Нейросеть для Brawl Stars",
                description=price_info["label"],
                payload=json.dumps({
                    "user_id": message.from_user.id,
                    "period": period,
                    "currency": "XTR",
                    "amount": price_info["amount"],
                }),
                provider_token="",  # Пустой для Telegram Stars
                currency="XTR",
                prices=[LabeledPrice(label=price_info["label"], amount=price_info["amount"])],
            )

        elif currency == "usd":
            if crypto_pay:
                try:
                    invoice = await crypto_pay.create_invoice(
                        amount=price_info["amount"],
                        currency_type="fiat",
                        fiat="USD",
                        description=f"AI Stars — {price_info['label']}",
                        payload=json.dumps({"user_id": message.from_user.id, "period": period, "amount": price_info["amount"]}),
                    )
                    invoice_id = invoice["invoice_id"]
                    pay_url = invoice.get("bot_invoice_url") or invoice.get("mini_app_invoice_url") or invoice.get("pay_url")

                    text = (
                        f"💎 **Оплата через CryptoBot**\n\n"
                        f"📦 Товар: AI Stars — {price_info['label']}\n"
                        f"💰 Сумма: **${price_info['amount']}**\n\n"
                        f"Нажмите кнопку ниже для оплаты через @CryptoBot.\n"
                        f"После оплаты нажмите кнопку «Проверить оплату»."
                    )

                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text=f"💳 Оплатить ${price_info['amount']} в CryptoBot", url=pay_url)],
                            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_crypto_{invoice_id}_{period}")],
                        ]
                    )

                    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                    return
                except Exception as e:
                    logger.error(f"CryptoPay invoice error in webapp: {e}")

            await message.answer("❌ Ошибка при создании счета в CryptoBot. Попробуйте позже.")

        elif currency == "rub":
            # Ручная оплата — создаём ожидающий платёж
            payment_id = await create_pending_payment(
                message.from_user.id,
                price_info["currency"],
                price_info["amount"],
                period,
            )

            currency_symbol = "₽"
            payment_details = (
                "💳 **Реквизиты для оплаты:**\n"
                "• Банк: Сбер / Тинькофф\n"
                "• Номер карты: `XXXX XXXX XXXX XXXX`\n"
                "• Или по номеру телефона: `+7 (XXX) XXX-XX-XX`\n\n"
                "⚠️ **ВАЖНО:** В комментарии к переводу укажите:\n"
                f"`AI Stars #{payment_id}`"
            )

            text = (
                f"🧾 **Заказ #{payment_id}**\n\n"
                f"📦 Товар: AI Stars — {price_info['label']}\n"
                f"💰 Сумма: **{price_info['amount']} {currency_symbol}**\n\n"
                f"{payment_details}\n\n"
                f"После оплаты администратор проверит платёж и активирует подписку.\n"
                f"Обычно это занимает до 15 минут ⏱"
            )

            await message.answer(text, parse_mode=ParseMode.MARKDOWN)

            # Уведомим админов
            for admin_id in ADMIN_IDS:
                try:
                    admin_text = (
                        f"🔔 **Новый заказ #{payment_id}!**\n\n"
                        f"👤 Пользователь: @{message.from_user.username or 'N/A'} "
                        f"(ID: `{message.from_user.id}`)\n"
                        f"📦 Период: **{period}**\n"
                        f"💰 Сумма: **{price_info['amount']} {currency_symbol}**\n\n"
                        f"Для подтверждения:\n"
                        f"`/confirm {payment_id}`"
                    )
                    await bot.send_message(admin_id, admin_text, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    except json.JSONDecodeError:
        await message.answer("❌ Ошибка обработки данных.")
    except Exception as e:
        logger.error(f"Ошибка обработки web_app_data: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ===== TELEGRAM STARS: PRE-CHECKOUT =====
@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Подтверждение оплаты через Telegram Stars."""
    await query.answer(ok=True)


# ===== TELEGRAM STARS: УСПЕШНАЯ ОПЛАТА =====
@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    """Обработка успешной оплаты через Telegram Stars."""
    payment = message.successful_payment
    try:
        payload = json.loads(payment.invoice_payload)
        user_id = payload["user_id"]
        period = payload["period"]
        currency = payload["currency"]
        amount = payload["amount"]

        await add_subscription(user_id, period, currency, amount)

        if period == "forever":
            period_text = "навсегда 🔥"
        else:
            period_text = "на 1 месяц 📅"

        text = (
            f"🎉 **Оплата прошла успешно!**\n\n"
            f"✅ Подписка активирована **{period_text}**\n"
            f"💫 Спасибо за покупку!\n\n"
            f"Теперь вам доступны все возможности нейросети AI Stars! 🤖"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Ошибка при обработке платежа: {e}")
        await message.answer(
            "❌ Ошибка при активации подписки. Обратитесь в поддержку."
        )


# ===== КОМАНДА /confirm — ПОДТВЕРЖДЕНИЕ ОПЛАТЫ АДМИНОМ =====
@dp.message(Command("confirm"))
async def cmd_confirm(message: types.Message):
    """Подтверждение платежа администратором."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: `/confirm <payment_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        payment_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID платежа должен быть числом.")
        return

    payment = await confirm_payment(payment_id)
    if not payment:
        await message.answer(f"❌ Платёж #{payment_id} не найден или уже подтверждён.")
        return

    # Уведомим пользователя
    user_id = payment["user_id"]
    period = payment["period"]
    if period == "forever":
        period_text = "навсегда 🔥"
    else:
        period_text = "на 1 месяц 📅"

    try:
        user_text = (
            f"🎉 **Оплата подтверждена!**\n\n"
            f"✅ Подписка активирована **{period_text}**\n"
            f"💫 Спасибо за покупку!\n\n"
            f"Теперь вам доступны все возможности нейросети AI Stars! 🤖"
        )
        await bot.send_message(user_id, user_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await message.answer(
        f"✅ Платёж #{payment_id} подтверждён! Подписка пользователя {user_id} активирована."
    )


# ===== КОМАНДА /pending — ОЖИДАЮЩИЕ ПЛАТЕЖИ =====
@dp.message(Command("pending"))
async def cmd_pending(message: types.Message):
    """Список ожидающих платежей (для админов)."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return

    payments = await get_pending_payments()

    if not payments:
        await message.answer("📭 Нет ожидающих платежей.")
        return

    text = "📋 **Ожидающие платежи:**\n\n"
    for p in payments:
        text += (
            f"**#{p['id']}** — @{p.get('username', 'N/A')} "
            f"(ID: `{p['user_id']}`)\n"
            f"   💰 {p['amount']} {p['currency']} | {p['period']}\n"
            f"   📅 {p['created_at']}\n"
            f"   → `/confirm {p['id']}`\n\n"
        )

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


# ===== КОМАНДА /status =====
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    """Проверка статуса подписки."""
    sub = await check_subscription(message.from_user.id)

    if sub["active"]:
        if sub["type"] == "forever":
            text = "✅ **Подписка активна!**\n🔥 Тип: **Навсегда**\n\nВам доступны все функции нейросети."
        else:
            expires = datetime.fromisoformat(sub["expires_at"])
            days_left = (expires - datetime.now()).days
            text = (
                f"✅ **Подписка активна!**\n"
                f"📅 Тип: **На месяц**\n"
                f"⏳ Осталось: **{days_left} дней**\n"
                f"📆 Действует до: **{expires.strftime('%d.%m.%Y')}**"
            )
    else:
        text = (
            "❌ **Подписка не активна**\n\n"
            "Используйте /start чтобы открыть магазин."
        )

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER И WEB APP =====
import os
from aiohttp import web

async def start_web_server():
    """Запуск встроенного веб-сервера для раздачи Web App и Health Check на Render."""
    port = int(os.getenv("PORT", 8080))
    app = web.Application()

    async def serve_index(request):
        webapp_path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
        if os.path.exists(webapp_path):
            return web.FileResponse(webapp_path)
        return web.Response(text="AI Stars Web App is running!")

    app.router.add_get("/", serve_index)
    app.router.add_get("/index.html", serve_index)

    webapp_dir = os.path.join(os.path.dirname(__file__), "webapp")
    if os.path.exists(webapp_dir):
        app.router.add_static("/static", path=webapp_dir, name="static")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web App сервер запущен на порту {port}")


# ===== ЗАПУСК БОТА =====
async def main():
    logger.info("🚀 Запуск AI Stars Bot...")
    await init_db()
    logger.info("✅ База данных инициализирована")
    
    # Запуск веб-сервера (для Render и раздачи WebApp)
    await start_web_server()
    logger.info(f"🔗 WEBAPP_URL: {WEBAPP_URL}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
