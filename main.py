import os
import sqlite3
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

# Підключення шрифту
pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "finance.db"

# База даних
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    currency TEXT DEFAULT 'грн'
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

TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції", "📊 Статистика", "👤 Мій профіль"]
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

CURRENCIES = ["грн", "$"]
MONTHS = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
    5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
    9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"
}

NAME, TYPE, CATEGORY, SUBCATEGORY, AMOUNT, CURRENCY, COMMENT, STAT_MODE, STAT_YEAR, STAT_MONTH, STAT_DAY = range(11)

def kb(rows):
    return ReplyKeyboardMarkup([[KeyboardButton(x) for x in row] for row in rows], resize_keyboard=True)

def main_menu_kb():
    return kb([["💸 Витрати", "💰 Надходження"], ["📈 Інвестиції", "📊 Статистика"], ["👤 Мій профіль"]])

def categories_kb(for_type):
    cats = list(CATEGORIES[for_type].keys())
    rows, row = [], []
    for c in cats:
        row.append(c)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row: rows.append(row)
    rows.append(["↩️ Назад"])
    return kb(rows)

def subcategories_kb(for_type, category):
    subs = CATEGORIES[for_type][category]
    rows = []
    if subs:
        row = []
        for s in subs:
            row.append(s)
            if len(row) == 2:
                rows.append(row)
                row = []
        if row: rows.append(row)
    rows.append(["(без підкатегорії)", "↩️ Назад"])
    return kb(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT name FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    if not user:
        await update.message.reply_text("👋 Привіт! Я — фінансовий бот. Давай познайомимось.\nЯк до тебе звертатись?")
        return NAME
    await update.message.reply_text("👋 Радий тебе знову бачити! Обери дію:", reply_markup=main_menu_kb())
    return TYPE

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    user_id = update.effective_user.id
    cur.execute("INSERT OR REPLACE INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    await update.message.reply_text(
        f"✅ Профіль створено!\nІм'я: {name}\nВалюта: грн\n\n"
        "Цей бот допоможе тобі:\n"
        "• Записувати витрати та доходи\n"
        "• Вести інвестиції\n"
        "• Отримувати статистику з PDF-звітом\n"
        "• Переглядати свій профіль\n\n"
        "Обери дію нижче:",
        reply_markup=main_menu_kb()
    )
    return TYPE

async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t not in TYPES:
        await update.message.reply_text("Будь ласка, обери кнопку нижче:", reply_markup=main_menu_kb())
        return TYPE
    if t == "📊 Статистика":
        await update.message.reply_text("Оберіть режим:", reply_markup=kb([["📅 За день", "📅 За місяць"], ["↩️ Назад"]]))
        return STAT_MODE
    if t == "👤 Мій профіль":
        user_id = update.effective_user.id
        cur.execute("SELECT name, currency FROM users WHERE user_id=?", (user_id,))
        u = cur.fetchone()
        await update.message.reply_text(f"👤 Профіль:\nІм'я: {u[0]}\nВалюта: {u[1]}", reply_markup=main_menu_kb())
        return TYPE
    context.user_data["type"] = t
    await update.message.reply_text("Вибери категорію:", reply_markup=categories_kb(t))
    return CATEGORY

async def pick_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    t = context.user_data.get("type")
    if text == "↩️ Назад":
        await update.message.reply_text("Повернувся в головне меню:", reply_markup=main_menu_kb())
        return TYPE
    if text not in CATEGORIES[t]:
        await update.message.reply_text("Обери категорію:", reply_markup=categories_kb(t))
        return CATEGORY
    context.user_data["category"] = text
    subs = CATEGORIES[t][text]
    if subs:
        await update.message.reply_text("Підкатегорія:", reply_markup=subcategories_kb(t, text))
        return SUBCATEGORY
    context.user_data["subcategory"] = None
    await update.message.reply_text("Введи суму:")
    return AMOUNT

async def pick_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    t = context.user_data.get("type")
    c = context.user_data.get("category")
    if text == "↩️ Назад":
        await update.message.reply_text("Вибери категорію:", reply_markup=categories_kb(t))
        return CATEGORY
    if text == "(без підкатегорії)":
        context.user_data["subcategory"] = None
    else:
        subs = CATEGORIES[t][c] or []
        if text not in subs:
            await update.message.reply_text("Обери підкатегорію:", reply_markup=subcategories_kb(t, c))
            return SUBCATEGORY
        context.user_data["subcategory"] = text
    await update.message.reply_text("Введи суму:")
    return AMOUNT

async def pick_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".").strip()
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("Сума має бути числом:")
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text("Валюта?", reply_markup=kb([CURRENCIES, ["↩️ Назад"]]))
    return CURRENCY

async def pick_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "↩️ Назад":
        await update.message.reply_text("Введи суму ще раз:")
        return AMOUNT
    if text not in CURRENCIES:
        await update.message.reply_text("Обери валюту:", reply_markup=kb([CURRENCIES, ["↩️ Назад"]]))
        return CURRENCY
    context.user_data["currency"] = text
    await update.message.reply_text("Додай коментар або напиши '-' якщо без:", reply_markup=kb([["-"]]))
    return COMMENT

async def pick_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    if comment == "-":
        comment = None
    ud = context.user_data
    date_str = datetime.now().strftime("%Y-%m-%d")
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        update.effective_user.id,
        ud["type"], ud["category"], ud.get("subcategory"),
        ud["amount"], ud["currency"], comment, date_str, datetime.utcnow().isoformat()
    ))
    conn.commit()
    await update.message.reply_text(
        f"✅ Записано: {ud['type']} → {ud['category']} → {ud.get('subcategory', '')}\n"
        f"Сума: {ud['amount']} {ud['currency']}\nДата: {date_str}",
        reply_markup=main_menu_kb()
    )
    ud.clear()
    return TYPE

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
            TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_type)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_category)],
            SUBCATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_subcategory)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_amount)],
            CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_currency)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_comment)],
        },
        fallbacks=[],
        allow_reentry=True
    )
    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling()

if __name__ == "__main__":
    main()
