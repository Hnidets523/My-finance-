import os
import sqlite3
import calendar
import random
import requests
from collections import defaultdict
from datetime import datetime

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    MessageHandler, CallbackQueryHandler, ContextTypes, filters
)

# ==== PDF ====
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==== Charts ====
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_KEY = os.getenv("HF_API_KEY")  # HuggingFace API KEY
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено у змінних середовища (Railway → Variables).")

DB_PATH = "finance.db"
pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

# ===================== DB =====================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    currency TEXT DEFAULT 'грн',
    created_at TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    category TEXT,
    subcategory TEXT,
    amount REAL,
    currency TEXT,
    comment TEXT,
    date TEXT,
    created_at TEXT
)
""")
conn.commit()

# ===================== CONSTANTS =====================
MONTHS = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
    5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
    9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"
}
MONTHS_BY_NAME = {v: k for k, v in MONTHS.items()}

TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції"]
CURRENCIES = ["грн", "$"]

CATEGORIES = {
    "💸 Витрати": {
        "Харчування": ["Кафе", "Супермаркет/ринок", "Гульки", "Трати на роботі"],
        "Одяг та взуття": ["Секонд", "Фізичний магазин", "Онлайн"],
        "Оренда/житло": None,
        "Господарчі товари": None,
        "Дорога/подорожі": ["Маршрутки", "Автобуси/дальність"],
        "Онлайн підписки": ["iCloud", "YouTube", "Prom"],
        "Поповнення мобільного": None,
        "Розваги": None,
        "Vodafone": ["Чай/поповнення", "Сім-карти"],
    },
    "📈 Інвестиції": {
        "Крипта": None,
        "Зарядні пристрої": None,
        "Hub station": None,
        "Акаунти": None,
        "Купівля $": None,
    },
    "💰 Надходження": {
        "Зарплата": None,
        "Переказ": None,
        "Інше": None,
    },
}

CATEGORY_EMOJI = {
    "Харчування": "🍔", "Одяг та взуття": "👕", "Оренда/житло": "🏠",
    "Господарчі товари": "🧴", "Дорога/подорожі": "🚌", "Онлайн підписки": "📲",
    "Поповнення мобільного": "📶", "Розваги": "🎉", "Vodafone": "📡",
    "Крипта": "🪙", "Зарядні пристрої": "🔌", "Hub station": "🖥️",
    "Акаунти": "👤", "Купівля $": "💵", "Зарплата": "💼", "Переказ": "🔁",
    "Інше": "➕",
}

CATEGORY_COLORS = {
    "Харчування": "#FF9800", "Одяг та взуття": "#3F51B5", "Оренда/житло": "#009688",
    "Господарчі товари": "#795548", "Дорога/подорожі": "#4CAF50",
    "Онлайн підписки": "#9C27B0", "Поповнення мобільного": "#607D8B",
    "Розваги": "#673AB7", "Vodafone": "#E91E63", "Крипта": "#FBC02D",
    "Зарядні пристрої": "#8BC34A", "Hub station": "#00BCD4",
    "Акаунти": "#CDDC39", "Купівля $": "#FF5722", "Зарплата": "#2196F3",
    "Переказ": "#00ACC1", "Інше": "#9E9E9E"
}

TIPS = [
    "Не заощаджуй те, що залишилось після витрат — витрачай те, що залишилось після заощаджень. — Уоррен Баффет",
    "Бюджет — це те, що змушує ваші гроші робити те, що ви хочете. — Дейв Ремзі",
    "Записуй витрати щодня — дисципліна перемагає інтуїцію.",
    "Плати спочатку собі: відкладайте 10–20% від кожного доходу.",
    "Сніжний ком: гасіть найменші борги першими, щоб набирати темп.",
    "Диверсифікуй інвестиції — не клади всі яйця в один кошик.",
    "Купуй активи, а не статус. Статус згорає, активи працюють.",
    "Те, що не вимірюєш — тим не керуєш. Статистика = контроль.",
    "Найкращий час почати інвестувати був учора. Другий найкращий — сьогодні.",
    "Гроші люблять тишу. Приймай рішення раціонально, не імпульсивно."
]

# ===================== STATES =====================
(
    ASK_NAME, MAIN, AMOUNT, COMMENT,
    STAT_YEAR_SELECT, STAT_MONTH_SELECT, STAT_DAY_SELECT,
    PROFILE_EDIT_NAME, QUIZ_ACTIVE, AI_CHAT
) = range(10)

# ===================== AI =====================
async def ask_ai(prompt):
    url = "https://api-inference.huggingface.co/models/meta-llama/Llama-3.2-3B-Instruct"
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 200, "temperature": 0.7}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        res = r.json()
        if isinstance(res, list) and "generated_text" in res[0]:
            return res[0]["generated_text"]
        elif "generated_text" in res:
            return res["generated_text"]
        return "⚠️ Вибач, не знайшов відповідь."
    except Exception:
        return "⚠️ Помилка підключення до AI."

async def ai_intro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *AI-помічник*\n\n"
        "Можу допомогти з фінансами, інвестиціями, і загальними питаннями.\n"
        "Просто напиши питання 👇", parse_mode="Markdown"
    )
    return AI_CHAT

async def ai_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await update.message.reply_text("⏳ Думаю над відповіддю…")
    reply = await ask_ai(text)
    await update.message.reply_text(f"🤖 {reply}")
    return MAIN

# ===================== MAIN MENU =====================
def main_menu_ikb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Витрати", callback_data="type:exp"),
         InlineKeyboardButton("💰 Надходження", callback_data="type:inc")],
        [InlineKeyboardButton("📈 Інвестиції", callback_data="type:inv"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats:open")],
        [InlineKeyboardButton("🎮 Гра", callback_data="quiz:start"),
         InlineKeyboardButton("👤 Мій профіль", callback_data="profile:open")],
        [InlineKeyboardButton("🤖 AI-помічник", callback_data="ai:start")]
    ])

# ===================== CALLBACK ROUTER (уривок з твоєї логіки) =====================
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()

    if data == "ai:start":
        await q.message.reply_text("🤖 Напиши своє питання:", parse_mode="Markdown")
        return AI_CHAT

    # решта твого великого router тут без змін...
    # ...

# ===================== APP =====================
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.job_queue.run_repeating(refresh_rates_job, interval=60, first=0)

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name),
                       CallbackQueryHandler(on_cb)],
            MAIN: [CallbackQueryHandler(on_cb)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount),
                     CallbackQueryHandler(on_cb)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comment),
                      CallbackQueryHandler(on_cb)],
            STAT_YEAR_SELECT: [CallbackQueryHandler(on_cb)],
            STAT_MONTH_SELECT: [CallbackQueryHandler(on_cb)],
            STAT_DAY_SELECT: [CallbackQueryHandler(on_cb)],
            PROFILE_EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_edit_name),
                                CallbackQueryHandler(on_cb)],
            QUIZ_ACTIVE: [CallbackQueryHandler(on_cb)],
            AI_CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_response)]
        },
        fallbacks=[CallbackQueryHandler(on_cb)],
        allow_reentry=True
    )

    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
