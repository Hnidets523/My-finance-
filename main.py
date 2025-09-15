import os
import sqlite3
from datetime import datetime, timedelta
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

# ======== CONFIG ========
BOT_TOKEN = "ТВОЙ_ТОКЕН"  # <-- ВСТАВ СЮДА СВОЙ ТОКЕН!
DB_PATH = "finance.db"
pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

# ======== СТАНИ ========
TYPE, CATEGORY, SUBCATEGORY, AMOUNT, CURRENCY, COMMENT, NAME, CURRENCY_SETUP = range(8)

# ======== КАТЕГОРІЇ ========
TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції"]

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

# ======== БД ========
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
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
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    currency TEXT
)
""")
conn.commit()

# ======== КЛАВІАТУРИ ========
def kb(rows):
    return ReplyKeyboardMarkup([[KeyboardButton(x) for x in row] for row in rows], resize_keyboard=True)

def main_menu_kb():
    return kb([["💸 Витрати", "💰 Надходження"], ["📈 Інвестиції"], ["📊 Статистика", "👤 Мій профіль"]])

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

def currencies_kb():
    return kb([CURRENCIES, ["↩️ Назад"]])

# ======== ФУНКЦІЇ ========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    if not user:
        await update.message.reply_text("👋 Привіт! Я — фінансовий бот. Давай познайомимось.\nЯк до тебе звертатись?")
        return NAME
    await update.message.reply_text(
        "👋 Привіт знову! Обери дію 👇", reply_markup=main_menu_kb()
    )
    return TYPE

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data["name"] = name
    await update.message.reply_text(f"Приємно познайомитись, {name}! Обери валюту:", reply_markup=currencies_kb())
    return CURRENCY_SETUP

async def save_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text
    if currency not in CURRENCIES:
        await update.message.reply_text("Будь ласка, обери валюту з кнопок:", reply_markup=currencies_kb())
        return CURRENCY_SETUP
    user_id = update.effective_user.id
    name = context.user_data["name"]
    cur.execute("INSERT OR REPLACE INTO users (user_id, name, currency) VALUES (?, ?, ?)", (user_id, name, currency))
    conn.commit()
    await update.message.reply_text(
        f"✅ Профіль створено!\n\n"
        f"Твій особистий фінансовий кабінет готовий.\n\n"
        f"Можливості:\n"
        f"• Додавати витрати, надходження та інвестиції\n"
        f"• Переглядати статистику за день чи місяць\n"
        f"• Завантажувати PDF-звіти\n"
        f"• Редагувати ім'я та валюту\n\n"
        f"Обери дію нижче 👇",
        reply_markup=main_menu_kb()
    )
    return TYPE

def save_tx(user_id, ttype, cat, sub, amount, currency, comment, date_str):
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, ttype, cat, sub, amount, currency, comment, date_str, datetime.utcnow().isoformat()))
    conn.commit()

async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t not in TYPES and t not in ["📊 Статистика", "👤 Мій профіль"]:
        await update.message.reply_text("Будь ласка, обери кнопку нижче:", reply_markup=main_menu_kb())
        return TYPE
    if t == "📊 Статистика":
        await show_statistics(update, context)
        return TYPE
    if t == "👤 Мій профіль":
        await show_profile(update)
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
    await update.message.reply_text("Введи суму (наприклад 123.45):")
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
    await update.message.reply_text("Введи суму (наприклад 123.45):")
    return AMOUNT

async def pick_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".").strip()
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("Сума має бути числом. Спробуй ще раз:")
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text("Додай коментар або '-' якщо без коментаря:")
    return COMMENT

async def pick_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    if comment == "-":
        comment = None
    user_id = update.effective_user.id
    cur.execute("SELECT currency FROM users WHERE user_id=?", (user_id,))
    user_currency = cur.fetchone()[0]
    ud = context.user_data
    date_str = datetime.now().strftime("%Y-%m-%d")
    save_tx(user_id, ud["type"], ud["category"], ud.get("subcategory"), ud["amount"], user_currency, comment, date_str)
    await update.message.reply_text(
        f"✅ Записано: {ud['type']} → {ud['category']} → {ud.get('subcategory', '')}\n"
        f"Сума: {ud['amount']} {user_currency}\nДата: {date_str}",
        reply_markup=main_menu_kb()
    )
    ud.clear()
    return TYPE

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT * FROM transactions WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📊 У тебе ще немає записів.", reply_markup=main_menu_kb())
        return
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='💸 Витрати' AND date=?", (user_id, today))
    expenses = cur.fetchone()[0] or 0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='💰 Надходження' AND date=?", (user_id, today))
    income = cur.fetchone()[0] or 0
    await update.message.reply_text(
        f"📅 Статистика за {today}:\n💰 Надходження: {income}\n💸 Витрати: {expenses}",
        reply_markup=main_menu_kb()
    )

async def show_profile(update: Update):
    user_id = update.effective_user.id
    cur.execute("SELECT name, currency FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    if user:
        await update.message.reply_text(
            f"👤 Твій профіль:\nІм'я: {user[0]}\nВалюта: {user[1]}",
            reply_markup=main_menu_kb()
        )
    else:
        await update.message.reply_text("Профіль ще не створено. Напиши /start", reply_markup=main_menu_kb())

# ======== APP ========
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
            CURRENCY_SETUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_currency)],
            TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_type)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_category)],
            SUBCATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_subcategory)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_amount)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_comment)],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling()

if __name__ == "__main__":
    main()
