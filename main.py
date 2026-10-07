import asyncio
import datetime
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    CallbackQuery,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# ================= TOKEN BO'LIMI =================
BOT_TOKEN = "8940640747:AAFdR3w-8n0mbsYxGBDEk0yEA4eQUQXE_Sg"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()
router = Router()

# Admin ma'lumotlari
ADMIN_LOGIN = "isakov"
ADMIN_PAROL = "sardor"

authenticated_admins = set()

# ================= DATABASE (SQLite) =================
DB_FILE = "bot_data.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_active TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            remind_time TEXT
        )
    """)
    conn.commit()
    conn.close()


def update_user_activity(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "INSERT INTO users (user_id, last_active) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET last_active=?",
        (user_id, today, today),
    )
    conn.commit()
    conn.close()


def save_reminder(user_id: int, text: str, remind_time_str: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reminders (user_id, text, remind_time) VALUES (?, ?, ?)",
        (user_id, text, remind_time_str),
    )
    conn.commit()
    conn.close()


def get_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE last_active = ?", (today,))
    today_users = cursor.fetchone()[0]

    conn.close()
    return total_users, today_users


# ================= FSM STATES =================
class ReminderState(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_hour = State()
    waiting_for_minute = State()
    waiting_for_confirm = State()


class AdminState(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()


# ================= KEYBOARDS =================
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Reja qo'shish")],
            [KeyboardButton(text="⚙️ Admin panel")],
        ],
        resize_keyboard=True,
    )


def date_keyboard():
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    after_tomorrow = today + datetime.timedelta(days=2)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Bugun ({today.strftime('%d.%m')})",
                    callback_data=f"date_{today.strftime('%Y-%m-%d')}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Ertaga ({tomorrow.strftime('%d.%m')})",
                    callback_data=f"date_{tomorrow.strftime('%Y-%m-%d')}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Indinga ({after_tomorrow.strftime('%d.%m')})",
                    callback_data=f"date_{after_tomorrow.strftime('%Y-%m-%d')}",
                )
            ],
        ]
    )


def hour_keyboard():
    buttons = []
    row = []
    for h in range(24):
        hour_str = f"{h:02d}"
        row.append(
            InlineKeyboardButton(
                text=f"{hour_str}:00", callback_data=f"hour_{hour_str}"
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def minute_keyboard():
    minutes = ["00", "15", "30", "45"]
    buttons = [
        [
            InlineKeyboardButton(
                text=f":{m}", callback_data=f"minute_{m}"
            )
            for m in minutes
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data="confirm_yes"
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data="confirm_no"
                ),
            ]
        ]
    )


# ================= SCHEDULER REMINDER HANDLER =================
async def send_reminder_notification(user_id: int, text: str, time_str: str):
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"⏰ **ESLATMA!**\n\nRejangiz boshlanishiga 5 daqiqa qoldi!\n📌 **Reja:** {text}\n📅 **Belgilangan vaqt:** {time_str}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Eslatma yuborishda xatolik: {e}")


# ================= HANDLERS =================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    update_user_activity(message.from_user.id)
    await message.answer(
        "Xush kelibsiz! Eslatma botidan foydalanish uchun quyidagi tugmalardan birini tanlang:",
        reply_markup=main_keyboard(),
    )


# --- REJA QO'SHISH FLOW ---
@router.message(F.text == "➕ Reja qo'shish")
async def add_plan_start(message: Message, state: FSMContext):
    update_user_activity(message.from_user.id)
    await state.set_state(ReminderState.waiting_for_text)
    await message.answer(
        "Nimani eslatay? Rejangiz mazmunini yozing:",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ReminderState.waiting_for_text)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(ReminderState.waiting_for_date)
    await message.answer(
        "📅 Qaysi kunga eslatishni tanlang:", reply_markup=date_keyboard()
    )


@router.callback_query(ReminderState.waiting_for_date, F.data.startswith("date_"))
async def process_date(callback: CallbackQuery, state: FSMContext):
    selected_date = callback.data.split("_")[1]
    await state.update_data(selected_date=selected_date)
    await state.set_state(ReminderState.waiting_for_hour)
    await callback.message.edit_text(
        f"📅 Tanlangan sana: **{selected_date}**\n\n🕒 Endi soatni tanlang:",
        reply_markup=hour_keyboard(),
        parse_mode="Markdown",
    )


@router.callback_query(ReminderState.waiting_for_hour, F.data.startswith("hour_"))
async def process_hour(callback: CallbackQuery, state: FSMContext):
    selected_hour = callback.data.split("_")[1]
    await state.update_data(selected_hour=selected_hour)
    await state.set_state(ReminderState.waiting_for_minute)
    await callback.message.edit_text(
        f"🕒 Tanlangan soat: **{selected_hour}:XX**\n\n⏱ Endi daqiqani tanlang:",
        reply_markup=minute_keyboard(),
        parse_mode="Markdown",
    )


@router.callback_query(
    ReminderState.waiting_for_minute, F.data.startswith("minute_")
)
async def process_minute(callback: CallbackQuery, state: FSMContext):
    selected_minute = callback.data.split("_")[1]
    data = await state.get_data()

    remind_time_str = (
        f"{data['selected_date']} {data['selected_hour']}:{selected_minute}"
    )

    try:
        remind_dt = datetime.datetime.strptime(remind_time_str, "%Y-%m-%d %H:%M")
        now = datetime.datetime.now()
        notify_dt = remind_dt - datetime.timedelta(minutes=5)

        if notify_dt <= now:
            await callback.answer(
                "❌ Bu vaqt o'tib ketgan! Qaytadan kelajakdagi vaqtni tanlang.",
                show_alert=True,
            )
            await state.set_state(ReminderState.waiting_for_date)
            await callback.message.edit_text(
                "📅 Qaysi kunga eslatishni tanlang:", reply_markup=date_keyboard()
            )
            return

        await state.update_data(remind_time=remind_time_str, notify_dt=notify_dt)

        await state.set_state(ReminderState.waiting_for_confirm)
        await callback.message.edit_text(
            f"📌 **Reja:** {data['text']}\n"
            f"⏰ **Vaqt:** {remind_time_str}\n"
            f"🔔 **Eslatma yuborilishi:** {notify_dt.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Ma'lumotlarni tasdiqlaysizmi?",
            reply_markup=confirm_keyboard(),
            parse_mode="Markdown",
        )
    except Exception as e:
        await callback.message.edit_text("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")


@router.callback_query(
    ReminderState.waiting_for_confirm, F.data.in_(["confirm_yes", "confirm_no"])
)
async def process_confirm(callback: CallbackQuery, state: FSMContext):
    if callback.data == "confirm_yes":
        data = await state.get_data()
        user_id = callback.from_user.id
        text = data["text"]
        remind_time_str = data["remind_time"]
        notify_dt = data["notify_dt"]

        # Database ga saqlash
        save_reminder(user_id, text, remind_time_str)

        # Scheduler ga 5 daqiqa oldin eslatish topshirig'ini qo'shish
        scheduler.add_job(
            send_reminder_notification,
            "date",
            run_date=notify_dt,
            args=[user_id, text, remind_time_str],
        )

        await callback.message.edit_text(
            "✅ Rejangiz bot xotirasiga saqlandi! Belgilangan vaqtdan 5 daqiqa oldin eslatma yuboriladi."
        )
        await callback.message.answer(
            "Asosiy menyu:", reply_markup=main_keyboard()
        )
    else:
        await callback.message.edit_text("❌ Reja saqlash bekor qilindi.")
        await callback.message.answer(
            "Asosiy menyu:", reply_markup=main_keyboard()
        )

    await state.clear()


# --- ADMIN PANEL FLOW ---
@router.message(F.text == "⚙️ Admin panel")
async def admin_start(message: Message, state: FSMContext):
    update_user_activity(message.from_user.id)
    user_id = message.from_user.id

    if user_id in authenticated_admins:
        total, today = get_stats()
        await message.answer(
            f"📊 **BOT STATISTIKASI**\n\n"
            f"👥 Jami foydalanuvchilar: {total} ta\n"
            f"🔥 Bugun kirganlar (Online): {today} ta",
            reply_markup=main_keyboard(),
            parse_mode="Markdown",
        )
        return

    await state.set_state(AdminState.waiting_for_login)
    await message.answer(
        "🔐 Admin panelga kirish uchun Loginni kiriting:",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AdminState.waiting_for_login)
async def process_login(message: Message, state: FSMContext):
    if message.text == ADMIN_LOGIN:
        await state.set_state(AdminState.waiting_for_password)
        await message.answer("Parolni kiriting:")
    else:
        await state.clear()
        await message.answer("❌ Login noto'g'ri!", reply_markup=main_keyboard())


@router.message(AdminState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    if message.text == ADMIN_PAROL:
        authenticated_admins.add(message.from_user.id)
        await state.clear()

        total, today = get_stats()
        await message.answer(
            f"✅ **Muvaffaqiyatli kirdingiz!**\n\n"
            f"📊 **BOT STATISTIKASI**\n\n"
            f"👥 Jami foydalanuvchilar: {total} ta\n"
            f"🔥 Bugun kirganlar (Online): {today} ta",
            reply_markup=main_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await state.clear()
        await message.answer("❌ Parol noto'g'ri!", reply_markup=main_keyboard())


# ================= BOTNI ISHGA TUSHIRISH =================
async def main():
    init_db()
    dp.include_router(router)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())