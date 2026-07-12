"""
AiStars Bot — Telegram-бот для продажи подписки с панелью администратора
"""

import asyncio
import html
import json
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
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
    reject_payment,
    get_pending_payments,
    get_setting,
    set_setting,
    create_support_ticket,
    get_open_tickets,
    reply_support_ticket,
    get_all_user_ids,
    clear_all_pending_payments,
    clear_all_open_tickets,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
crypto_pay = CryptoPay(CRYPTO_PAY_TOKEN) if CRYPTO_PAY_TOKEN else None
dp = Dispatcher(storage=MemoryStorage())

# Кулдауны (user_id -> timestamp последнего действия)
COOLDOWN_SECONDS = 300  # 5 минут
_cooldown_orders: dict[int, float] = {}
_cooldown_support: dict[int, float] = {}


# ===== FSM СОСТОЯНИЯ =====
class AdminStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_broadcast = State()
    waiting_for_ticket_reply = State()
    waiting_for_price_value = State()


class UserStates(StatesGroup):
    waiting_for_support_message = State()


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_webapp_configured() -> bool:
    return WEBAPP_URL and WEBAPP_URL != "YOUR_WEBAPP_URL_HERE" and WEBAPP_URL.startswith("https")


def get_shop_button():
    """Кнопка открытия Web App магазина."""
    return InlineKeyboardButton(
        text="🛒 Открыть магазин",
        web_app=WebAppInfo(url=WEBAPP_URL),
    )


async def get_price(currency: str, period: str, product: str = "aistars") -> float:
    """Динамическое получение цены с учётом настроек в БД."""
    custom_price = await get_setting(f"price_{product}_{currency}_{period}")
    if custom_price:
        try:
            return float(custom_price)
        except ValueError:
            pass
    return PRICES.get(product, {}).get(currency, {}).get(period, {}).get("amount", 0)


async def process_purchase(message: types.Message, currency: str, period: str, product: str = "aistars"):
    """Общий обработчик создания платежей."""
    if product not in PRICES or currency not in PRICES[product] or period not in PRICES[product][currency]:
        await message.answer("❌ Неверные данные тарифа.")
        return

    amount = await get_price(currency, period, product)
    user_id = message.from_user.id
    
    prod_label = "VPN" if product == "vpn" else "Подписка"
    label = f"{prod_label} ({period})"
    
    title = "VPN — ДЛЯ БОТОВ" if product == "vpn" else "AiStars — Бот для Brawl Stars"
    description = f"{title} — {label} ({int(amount)} ⭐)" if currency == "stars" else f"{title} — {label}"

    if currency == "stars":
        await bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description[:120],
            payload=json.dumps({
                "user_id": user_id,
                "period": period,
                "product": product,
                "currency": "XTR",
                "amount": amount,
            }),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=label, amount=int(amount))],
        )

    elif currency == "usd":
        if crypto_pay:
            try:
                invoice = await crypto_pay.create_invoice(
                    amount=amount,
                    currency_type="fiat",
                    fiat="USD",
                    description=description,
                    payload=json.dumps({
                        "user_id": user_id, 
                        "period": period, 
                        "product": product, 
                        "amount": amount
                    }),
                )
                invoice_id = invoice["invoice_id"]
                pay_url = invoice.get("bot_invoice_url") or invoice.get("mini_app_invoice_url") or invoice.get("pay_url")

                text = (
                    f"💎 <b>Оплата через CryptoBot</b>\n\n"
                    f"📦 Товар: {title} — {label}\n"
                    f"💰 Сумма: <b>${amount}</b>\n\n"
                    f"Нажмите кнопку ниже для оплаты через @CryptoBot.\n"
                    f"После оплаты нажмите кнопку «Проверить оплату»."
                )

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"💳 Оплатить ${amount} в CryptoBot", url=pay_url)],
                        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_crypto_{invoice_id}_{product}_{period}")],
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_start")],
                    ]
                )
                await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                return
            except Exception as e:
                logger.error(f"CryptoPay error: {e}")

        await message.answer("❌ Ошибка при создании счета в CryptoBot.")

    elif currency == "rub":
        card_number = html.escape(str(await get_setting("card_number", "0000 0000 0000 0000")))
        user_tag = f"@{html.escape(message.from_user.username)}" if message.from_user.username else f"ID: {user_id}"

        text = (
            f"📦 Товар: {title} — {label}\n"
            f"💰 Сумма: <b>{amount} ₽</b>\n\n"
            f"💳 <b>Номер карты:</b> <code>{card_number}</code>\n\n"
            f"⚠️ <b>ВАЖНО:</b> В комментарии к переводу укажите ваш юзернейм в Telegram:\n"
            f"<code>{user_tag}</code>"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я ОПЛАТИЛ", callback_data=f"paid_rub_{product}_{period}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_start")],
            ]
        )

        await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("paid_rub_"))
async def paid_rub_callback(callback: types.CallbackQuery):
    import time
    user_id = callback.from_user.id
    now = time.time()
    last_order = _cooldown_orders.get(user_id, 0)
    if now - last_order < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last_order))
        minutes = remaining // 60
        seconds = remaining % 60
        await callback.answer(
            f"⏳ Подождите {minutes} мин {seconds} сек перед повторной проверкой.",
            show_alert=True,
        )
        return

    parts = callback.data.split("_")
    product = "aistars"
    if len(parts) >= 4:
        product = parts[2]
        period = parts[3]
    else:
        period = parts[2]

    amount = await get_price(currency="rub", period=period, product=product)

    if not amount:
        await callback.answer("❌ Ошибка: неверный тариф.", show_alert=True)
        return

    await create_pending_payment(user_id, "RUB", amount, period, product)
    _cooldown_orders[user_id] = now
    await callback.answer("❌ Перевод не найден", show_alert=True)


# ===== КОМАНДА /start =====
@dp.message(CommandStart(), StateFilter("*"))
async def cmd_start(message: types.Message, command: CommandObject = None, state: FSMContext = None):
    """Приветствие и главное меню."""
    if state:
        await state.clear()

    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    args = command.args if command else None
    if args and args.startswith("buy_"):
        parts = args.split("_")
        product = "aistars"
        if len(parts) >= 4:
            product = parts[1]
            currency = parts[2]
            period = parts[3]
        elif len(parts) == 3:
            currency = parts[1]
            period = parts[2]
        else:
            await message.answer("❌ Неверные аргументы платежа.")
            return

        await process_purchase(message, currency, period, product)
        return

    sub_aistars = await check_subscription(message.from_user.id, "aistars")
    sub_vpn = await check_subscription(message.from_user.id, "vpn")

    status_parts = []
    if sub_aistars["active"]:
        if sub_aistars["type"] == "forever":
            status_parts.append("AiStars: ✅ <b>Навсегда</b>")
        else:
            expires = datetime.fromisoformat(sub_aistars["expires_at"])
            status_parts.append(f"AiStars: ✅ до <b>{expires.strftime('%d.%m.%Y')}</b>")
    else:
        status_parts.append("AiStars: ❌ Нет подписки")

    if sub_vpn["active"]:
        if sub_vpn["type"] == "forever":
            status_parts.append("VPN: ✅ <b>Навсегда</b>")
        else:
            expires = datetime.fromisoformat(sub_vpn["expires_at"])
            status_parts.append(f"VPN: ✅ до <b>{expires.strftime('%d.%m.%Y')}</b>")
    else:
        status_parts.append("VPN: ❌ Нет VPN")

    status_text = "\n".join(status_parts)
    first_name_esc = html.escape(message.from_user.first_name)

    welcome_text = (
        f"🤖 <b>Привет, {first_name_esc}!</b>\n\n"
        f"Добро пожаловать в бота для покупки подписки <b>AiStars</b>!\n\n"
        f"📊 <b>Статус услуг:</b>\n{status_text}\n\n"
        f"👇 Нажми кнопку ниже, чтобы войти в магазин!"
    )

    buttons = [
        [get_shop_button()],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="check_status")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")],
    ]

    if message.from_user.id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        welcome_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "back_start", StateFilter("*"))
async def back_start_callback(callback: types.CallbackQuery, state: FSMContext = None):
    """Возврат к стартовому меню."""
    if state:
        await state.clear()
    await callback.message.delete()
    await cmd_start(callback.message)
    await callback.answer()


# ===== ПРОВЕРКА ОПЛАТЫ CRYPTOPAY =====
@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_callback(callback: types.CallbackQuery):
    """Проверка статуса оплаты инвойса CryptoBot."""
    parts = callback.data.split("_")
    invoice_id = parts[2]
    product = parts[3]
    period = parts[4]

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
                await add_subscription(callback.from_user.id, period, "USD", amount, product)
                
                prod_title = "VPN" if product == "vpn" else "подписка AiStars"
                period_text = "навсегда 🔥" if period == "forever" else ("на 3 месяца 📅" if period == "3month" else "на 1 месяц 📅")
                await callback.message.edit_text(
                    f"🎉 <b>Оплата прошла успешно!</b>\n\n"
                    f"✅ {prod_title.capitalize()} активирована <b>{period_text}</b>\n"
                    f"💫 Спасибо за покупку через CryptoBot!",
                    parse_mode=ParseMode.HTML
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
    sub_aistars = await check_subscription(callback.from_user.id, "aistars")
    sub_vpn = await check_subscription(callback.from_user.id, "vpn")

    status_parts = []
    if sub_aistars["active"]:
        if sub_aistars["type"] == "forever":
            status_parts.append("🤖 <b>AiStars:</b> Активна (Навсегда 🔥)")
        else:
            expires = datetime.fromisoformat(sub_aistars["expires_at"])
            days_left = (expires - datetime.now()).days
            status_parts.append(f"🤖 <b>AiStars:</b> Активна (ещё {days_left} дн., до {expires.strftime('%d.%m.%Y')} 📅)")
    else:
        status_parts.append("🤖 <b>AiStars:</b> Не активна")

    if sub_vpn["active"]:
        if sub_vpn["type"] == "forever":
            status_parts.append("🛡️ <b>VPN:</b> Активен (Навсегда 🔥)")
        else:
            expires = datetime.fromisoformat(sub_vpn["expires_at"])
            days_left = (expires - datetime.now()).days
            status_parts.append(f"🛡️ <b>VPN:</b> Активен (ещё {days_left} дн., до {expires.strftime('%d.%m.%Y')} 📅)")
    else:
        status_parts.append("🛡️ <b>VPN:</b> Не активен")

    text = (
        "📊 <b>Статус ваших услуг:</b>\n\n" +
        "\n".join(status_parts) +
        "\n\nНажмите кнопку ниже, чтобы приобрести или продлить доступ!"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [get_shop_button()],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_start")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


# ===== ПОДДЕРЖКА ПОЛЬЗОВАТЕЛЯ =====
@dp.callback_query(F.data == "support")
async def support_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_for_support_message)
    text = (
        "💬 <b>Поддержка AiStars</b>\n\n"
        "Опишите вашу проблему прямо следующим сообщением в чат.\n\n"
        "Мы ответим в ближайшее время! 🙌"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="back_start")]]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.message(UserStates.waiting_for_support_message)
async def handle_user_support_message(message: types.Message, state: FSMContext):
    """Приём сообщения в поддержку от пользователя."""
    import time
    user_id = message.from_user.id

    now = time.time()
    last_ticket = _cooldown_support.get(user_id, 0)
    if now - last_ticket < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last_ticket))
        minutes = remaining // 60
        seconds = remaining % 60
        await state.clear()
        await message.answer(
            f"⏳ Подождите {minutes} мин {seconds} сек перед повторным обращением.",
        )
        return

    ticket_id = await create_support_ticket(
        user_id,
        message.from_user.username or "N/A",
        message.text,
    )
    _cooldown_support[user_id] = now
    await state.clear()
    await message.answer(
        f"✅ <b>Ваше обращение #{ticket_id} отправлено в поддержку!</b>\n"
        f"Ожидайте ответа от администратора.",
        parse_mode=ParseMode.HTML,
    )


# =====================================================================
# 👑 АДМИН-ПАНЕЛЬ (ТОЛЬКО ДЛЯ ADMIN_IDS)
# =====================================================================

@dp.message(Command("admin"), StateFilter("*"))
@dp.callback_query(F.data == "admin_panel", StateFilter("*"))
async def show_admin_panel(event: types.Message | types.CallbackQuery, state: FSMContext = None):
    """Главная страница панели администратора."""
    user_id = event.from_user.id if isinstance(event, types.Message) else event.from_user.id
    if user_id not in ADMIN_IDS:
        if isinstance(event, types.CallbackQuery):
            await event.answer("⛔ У вас нет прав доступа к админ-панели.", show_alert=True)
        else:
            await event.answer("⛔ У вас нет прав доступа к админ-панели.")
        return

    if state:
        await state.clear()

    pending_payments = await get_pending_payments()
    open_tickets = await get_open_tickets()
    card_number = html.escape(str(await get_setting("card_number", "Не задана")))

    text = (
        "👑 <b>Панель Администратора AiStars</b>\n\n"
        f"💳 <b>Текущая карта:</b> <code>{card_number}</code>\n"
        f"📋 <b>Ожидают подтверждения:</b> {len(pending_payments)} заказов\n"
        f"💬 <b>Открытые тикеты:</b> {len(open_tickets)} шт.\n\n"
        f"Выберите раздел:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📋 Заказы ({len(pending_payments)})", callback_data="admin_orders")],
            [InlineKeyboardButton(text=f"💬 Поддержка ({len(open_tickets)})", callback_data="admin_tickets")],
            [InlineKeyboardButton(text="💳 Сменить карту", callback_data="admin_change_card")],
            [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="💰 Изменить цены", callback_data="admin_prices")],
            [InlineKeyboardButton(text="◀️ Выйти из админки", callback_data="back_start")],
        ]
    )

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ----- 1. ЗАКАЗЫ (ПОДТВЕРЖДЕНИЕ / ОТКЛОНЕНИЕ) -----
@dp.callback_query(F.data == "admin_orders")
async def admin_orders_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    payments = await get_pending_payments()

    if not payments:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]]
        )
        await callback.message.edit_text("📭 Нет ожидающих заказов.", reply_markup=keyboard)
        await callback.answer()
        return

    text = f"📋 <b>Ожидающие заказы ({len(payments)} шт.):</b>\n\n"
    buttons = []

    for p in payments[:10]:
        raw_uname = p.get('username')
        uname_str = f"@{html.escape(raw_uname)}" if raw_uname else "N/A"
        prod_title = f" ({p.get('product', 'aistars')})" if p.get('product') else ""
        text += (
            f"<b>Заказ #{p['id']}</b> | {uname_str} (ID: <code>{p['user_id']}</code>)\n"
            f"💰 Сумма: {p['amount']} {p['currency']} | Тариф: {p['period']}{prod_title}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(text=f"✅ Подтвердить #{p['id']}", callback_data=f"adm_confirm_{p['id']}"),
            InlineKeyboardButton(text=f"❌ Отклонить #{p['id']}", callback_data=f"adm_reject_{p['id']}"),
        ])

    buttons.append([InlineKeyboardButton(text="🗑 Очистить все заказы", callback_data="adm_clear_orders_confirm")])
    buttons.append([InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_confirm_"))
async def adm_confirm_order(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    payment_id = int(callback.data.replace("adm_confirm_", ""))
    payment = await confirm_payment(payment_id)

    if payment:
        user_id = payment["user_id"]
        prod_title = "VPN" if payment.get("product") == "vpn" else "подписка AiStars"
        period_text = "навсегда 🔥" if payment["period"] == "forever" else ("на 3 месяца 📅" if payment["period"] == "3month" else "на 1 месяц 📅")
        try:
            await bot.send_message(
                user_id,
                f"🎉 <b>Оплата подтверждена!</b>\n\n"
                f"✅ {prod_title.capitalize()} активирована <b>{period_text}</b>\n"
                f"💫 Спасибо за покупку!",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

        await callback.answer(f"✅ Заказ #{payment_id} подтверждён!", show_alert=True)
    else:
        await callback.answer("❌ Платёж не найден или уже обработан.", show_alert=True)

    await admin_orders_callback(callback)


@dp.callback_query(F.data.startswith("adm_reject_"))
async def adm_reject_order(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    payment_id = int(callback.data.replace("adm_reject_", ""))
    payment = await reject_payment(payment_id)

    if payment:
        user_id = payment["user_id"]
        try:
            await bot.send_message(
                user_id,
                f"❌ <b>Ваш заказ #{payment_id} был отклонён администратором.</b>\n\n"
                f"Если произошла ошибка — напишите в поддержку.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

        await callback.answer(f"❌ Заказ #{payment_id} отклонён.", show_alert=True)
    else:
        await callback.answer("❌ Платёж не найден.", show_alert=True)

    await admin_orders_callback(callback)


@dp.callback_query(F.data == "adm_clear_orders_confirm")
async def adm_clear_orders_confirm(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, очистить", callback_data="adm_clear_orders_yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_orders"),
            ]
        ]
    )
    await callback.message.edit_text(
        "⚠️ <b>Вы уверены?</b>\n\nВсе ожидающие заказы будут удалены. Это действие нельзя отменить.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_clear_orders_yes")
async def adm_clear_orders_yes(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    count = await clear_all_pending_payments()
    await callback.answer(f"🗑 Удалено заказов: {count}", show_alert=True)
    await admin_orders_callback(callback)


# ----- 2. ПОДДЕРЖКА В АДМИНКЕ -----
@dp.callback_query(F.data == "admin_tickets", StateFilter("*"))
async def admin_tickets_callback(callback: types.CallbackQuery, state: FSMContext = None):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return
    if state:
        await state.clear()

    await callback.answer()

    try:
        tickets = await get_open_tickets()
    except Exception as e:
        logger.error(f"Ошибка получения тикетов: {e}")
        await callback.message.edit_text("❌ Ошибка загрузки тикетов.")
        return

    if not tickets:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")]]
        )
        await callback.message.edit_text("📭 Нет открытых обращений в поддержку.", reply_markup=keyboard)
        return

    text = f"💬 Открытые обращения ({len(tickets)} шт.):\n\n"
    buttons = []

    for t in tickets[:5]:
        uname = t.get('username') or 'N/A'
        display_name = f"@{uname}" if uname != 'N/A' else f"ID: {t['user_id']}"
        msg = str(t.get('message_text', ''))[:100]
        text += (
            f"Тикет #{t['id']} от {display_name} (ID: {t['user_id']}):\n"
            f"💬 {msg}\n\n"
        )
        buttons.append([InlineKeyboardButton(text=f"✉️ Ответить на #{t['id']}", callback_data=f"adm_reply_ticket_{t['id']}")])

    buttons.append([InlineKeyboardButton(text="🗑 Очистить все тикеты", callback_data="adm_clear_tickets_confirm")])
    buttons.append([InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка отображения тикетов: {e}")


@dp.callback_query(F.data == "adm_clear_tickets_confirm")
async def adm_clear_tickets_confirm(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, очистить", callback_data="adm_clear_tickets_yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_tickets"),
            ]
        ]
    )
    await callback.message.edit_text(
        "⚠️ <b>Вы уверены?</b>\n\nВсе открытые тикеты поддержки будут удалены. Это действие нельзя отменить.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_clear_tickets_yes")
async def adm_clear_tickets_yes(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    count = await clear_all_open_tickets()
    await callback.answer(f"🗑 Удалено тикетов: {count}", show_alert=True)
    await admin_tickets_callback(callback)


@dp.callback_query(F.data.startswith("adm_reply_ticket_"))
async def adm_start_ticket_reply(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    ticket_id = int(callback.data.replace("adm_reply_ticket_", ""))
    await state.update_data(reply_ticket_id=ticket_id)
    await state.set_state(AdminStates.waiting_for_ticket_reply)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_tickets")]]
    )
    await callback.message.edit_text(
        f"✉️ <b>Введите ваш ответ на тикет #{ticket_id}:</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@dp.message(AdminStates.waiting_for_ticket_reply)
async def adm_send_ticket_reply(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    await state.clear()

    ticket = await reply_support_ticket(ticket_id, message.text)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 К тикетам", callback_data="admin_tickets")],
            [InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")],
        ]
    )

    if ticket:
        uname = ticket.get('username') or 'N/A'
        display_name = f"@{html.escape(uname)}" if uname != 'N/A' else f"ID: {ticket['user_id']}"
        try:
            await bot.send_message(
                ticket["user_id"],
                f"💬 <b>Ответ от поддержки (по обращению #{ticket_id}):</b>\n\n"
                f"{html.escape(message.text)}",
                parse_mode=ParseMode.HTML,
            )
            await message.answer(
                f"✅ Ответ отправлен пользователю {display_name}!",
                reply_markup=keyboard,
            )
        except Exception as e:
            await message.answer(
                f"⚠️ Ответ сохранен, но не удалось доставить пользователю: {e}",
                reply_markup=keyboard,
            )
    else:
        await message.answer(
            "❌ Ошибка: тикет не найден.",
            reply_markup=keyboard,
        )


# ----- 3. СМЕНА РЕКВИЗИТОВ КАРТЫ -----
@dp.callback_query(F.data == "admin_change_card")
async def admin_change_card_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    card_number = html.escape(str(await get_setting("card_number", "Не задана")))
    await state.set_state(AdminStates.waiting_for_card)

    text = (
        f"💳 <b>Смена реквизитов карты</b>\n\n"
        f"Текущая карта: <code>{card_number}</code>\n\n"
        f"Введите новый номер карты в ответ на это сообщение:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.message(AdminStates.waiting_for_card)
async def process_new_card(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    new_card = message.text.strip()
    await set_setting("card_number", new_card)
    await state.clear()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")]]
    )
    card_esc = html.escape(new_card)
    await message.answer(f"✅ <b>Номер карты успешно обновлён!</b>\nНовая карта: <code>{card_esc}</code>", reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ----- 4. РАССЫЛКА -----
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    await state.set_state(AdminStates.waiting_for_broadcast)
    text = (
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Введите текст сообщения, которое будет отправлено <b>ВСЕМ</b> пользователям бота:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.clear()
    users = await get_all_user_ids()
    success_count = 0
    fail_count = 0

    status_msg = await message.answer(f"⏳ Отправка рассылки {len(users)} пользователям...")

    for uid in users:
        try:
            await bot.send_message(uid, message.text, parse_mode=ParseMode.HTML)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            try:
                await bot.send_message(uid, message.text)
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail_count += 1

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")]]
    )
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Успешно доставлено: <b>{success_count}</b>\n"
        f"Не доставлено: <b>{fail_count}</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


# ----- 5. ИЗМЕНЕНИЕ ЦЕН -----
@dp.callback_query(F.data == "admin_prices", StateFilter("*"))
async def admin_prices_callback(callback: types.CallbackQuery, state: FSMContext = None):
    if callback.from_user.id not in ADMIN_IDS:
        return
    if state:
        await state.clear()

    rub_m = await get_price("rub", "month")
    rub_f = await get_price("rub", "forever")
    usd_m = await get_price("usd", "month")
    usd_f = await get_price("usd", "forever")
    stars_m = await get_price("stars", "month")
    stars_f = await get_price("stars", "forever")

    text = (
        "💰 <b>Текущие цены:</b>\n\n"
        f"• Рубли: {rub_m} ₽ (мес) | {rub_f} ₽ (навсегда)\n"
        f"• Доллары: ${usd_m} (мес) | ${usd_f} (навсегда)\n"
        f"• Звёзды: {int(stars_m)} ⭐ (мес) | {int(stars_f)} ⭐ (навсегда)\n\n"
        f"Выберите параметр для изменения:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="₽ Рубли — Месяц", callback_data="setprice_rub_month"),
             InlineKeyboardButton(text="₽ Рубли — Навсегда", callback_data="setprice_rub_forever")],
            [InlineKeyboardButton(text="$ Доллары — Месяц", callback_data="setprice_usd_month"),
             InlineKeyboardButton(text="$ Доллары — Навсегда", callback_data="setprice_usd_forever")],
            [InlineKeyboardButton(text="⭐ Звёзды — Месяц", callback_data="setprice_stars_month"),
             InlineKeyboardButton(text="⭐ Звёзды — Навсегда", callback_data="setprice_stars_forever")],
            [InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_panel")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(F.data.startswith("setprice_"))
async def adm_setprice_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    parts = callback.data.split("_")
    currency = parts[1]
    period = parts[2]

    await state.update_data(change_currency=currency, change_period=period)
    await state.set_state(AdminStates.waiting_for_price_value)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_prices")]]
    )
    await callback.message.edit_text(
        f"💰 <b>Введите новую цену для <code>{currency.upper()}</code> ({period}):</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@dp.message(AdminStates.waiting_for_price_value)
async def adm_setprice_save(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        new_val = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Ошибка: введите число!")
        return

    data = await state.get_data()
    currency = data.get("change_currency")
    period = data.get("change_period")
    await state.clear()

    await set_setting(f"price_{currency}_{period}", str(new_val))

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ К ценам", callback_data="admin_prices")]]
    )
    await message.answer(
        f"✅ <b>Цена для {currency.upper()} ({period}) успешно изменена на {new_val}!</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


# ===== TELEGRAM STARS: PRE-CHECKOUT & SUCCESS =====
@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    try:
        payload = json.loads(payment.invoice_payload)
        user_id = payload["user_id"]
        period = payload["period"]
        currency = payload["currency"]
        amount = payload["amount"]

        await add_subscription(user_id, period, currency, amount)
        period_text = "навсегда 🔥" if period == "forever" else "на 1 месяц 📅"

        await message.answer(
            f"🎉 <b>Оплата прошла успешно!</b>\n\n"
            f"✅ Подписка активирована <b>{period_text}</b>\n"
            f"💫 Спасибо за покупку!\n\n"
            f"Теперь вам доступны все возможности нейросети AiStars! 🤖",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке платежа: {e}")
        await message.answer("❌ Ошибка при активации подписки. Обратитесь в поддержку.")


# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER И WEB APP =====
import os
from aiohttp import web

async def start_web_server():
    port = int(os.getenv("PORT", 8080))
    app = web.Application()

    async def serve_index(request):
        webapp_path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
        if os.path.exists(webapp_path):
            return web.FileResponse(webapp_path)
        return web.Response(text="AiStars Web App is running!")

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
    logger.info("🚀 Запуск AiStars Bot...")
    await init_db()
    logger.info("✅ База данных инициализирована")

    await start_web_server()
    logger.info(f"🔗 WEBAPP_URL: {WEBAPP_URL}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
