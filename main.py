import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
    ConversationHandler
)

# ====== CONFIG ======
BOT_TOKEN = "8420371366:AAG9UfAnEqKyrk5v1DOPHvh7hlp1ZDtHJy8"  # твій токен
ONLY_USER_ID = None  # можеш вказати свій Telegram ID, щоб обмежити доступ

# Типи операцій
TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції", "📊 Статистика"]

# Категорії та підкатегорії
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
STATS_PERIODS = ["📅 Сьогодні", "📅 Тиждень", "📅 Місяць", "↩️ Назад"]

# ====== DB ======
DB_PATH = "finance.db"
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
conn.commit()

# ====== STATES ======
TYPE, CATEGORY, SUBCATEGORY, AMOUNT, CURRENCY, COMMENT, STATS = range(7)

# ====== KEYBOARDS ======
def kb(rows):
    return ReplyKeyboardMarkup(
        [[KeyboardButton(x) for x in row] for row in rows],
        resize_keyboard=True
    )

def main_menu_kb():
    return kb([TYPES])

def categories_kb(for_type):
    cats = list(CATEGORIES[for_type].keys())
    rows, row = [], []
    for c in cats:
        row.append(c)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
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
        if row:
            rows.append(row)
    rows.append(["(без підкатегорії)", "↩️ Назад"])
    return kb(rows)

def currencies_kb():
    return kb([CURRENCIES, ["↩️ Назад"]])

def stats_kb():
    return kb([STATS_PERIODS])

# ====== DATABASE SAVE ======
def save_tx(user_id, ttype, cat, sub, amount, currency, comment, date_str):
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, ttype, cat, sub, amount, currency, comment, date_str, datetime.utcnow().isoformat()))
    conn.commit()

# ====== HELPERS ======
def get_stats(period: str, user_id: int):
    now = datetime.now()
    if period == "📅 Сьогодні":
        start_date = now.strftime("%Y-%m-%d")
        query = """
            SELECT type, currency, SUM(amount)
            FROM transactions
            WHERE user_id=? AND date=?
            GROUP BY type, currency
        """
        params = (user_id, start_date)
    elif period == "📅 Тиждень":
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        query = """
            SELECT type, currency, SUM(amount)
            FROM transactions
            WHERE user_id=? AND date>=?
            GROUP BY type, currency
        """
        params = (user_id, start_date)
    elif period == "📅 Місяць":
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        query = """
            SELECT type, currency, SUM(amount)
            FROM transactions
            WHERE user_id=? AND date>=?
            GROUP BY type, currency
        """
        params = (user_id, start_date)
    else:
        return "❌ Невідомий період."

    cur.execute(query, params)
    rows = cur.fetchall()
    if not rows:
        return "📭 Немає записів за обраний період."

    lines = [f"📊 Статистика за {period}:\n"]
    by_type = {}
    for t, curr, s in rows:
        by_type.setdefault(t, []).append((curr, s))

    for t, arr in by_type.items():
        parts = [f"{amt:.2f} {curr}" for curr, amt in arr]
        lines.append(f"{t}: " + " + ".join(parts))
    return "\n".join(lines)

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 Привіт! Я — фінансовий бот, який допоможе вести облік витрат, доходів та інвестицій.\n\n"
        "Тут ти можеш:\n"
        "💸 Додавати витрати та сортувати їх за категоріями\n"
        "💰 Фіксувати надходження\n"
        "📈 Вести облік інвестицій\n"
        "📊 Переглядати статистику своїх фінансів\n\n"
        "Бот створений для особистого використання.\n"
        "Засновник: @hnidets011"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu_kb())
    return TYPE

async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "📊 Статистика":
        await update.message.reply_text("Оберіть період для перегляду статистики:", reply_markup=stats_kb())
        return STATS
    if t not in TYPES:
        await update.message.reply_text("Будь ласка, оберіть кнопку нижче:", reply_markup=main_menu_kb())
        return TYPE
    context.user_data["type"] = t
    await update.message.reply_text("Виберіть категорію:", reply_markup=categories_kb(t))
    return CATEGORY

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    period = update.message.text
    if period == "↩️ Назад":
        await update.message.reply_text("Повернувся в головне меню:", reply_markup=main_menu_kb())
        return TYPE
    result = get_stats(period, update.effective_user.id)
    await update.message.reply_text(result, reply_markup=stats_kb())
    return STATS

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
    await update.message.reply_text("Валюта?", reply_markup=currencies_kb())
    return CURRENCY

async def pick_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "↩️ Назад":
        await update.message.reply_text("Введи суму ще раз:")
        return AMOUNT
    if text not in CURRENCIES:
        await update.message.reply_text("Обери валюту:", reply_markup=currencies_kb())
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
    save_tx(
        update.effective_user.id,
        ud["type"],
        ud["category"],
        ud.get("subcategory"),
        ud["amount"],
        ud["currency"],
        comment,
        date_str
    )
    await update.message.reply_text(
        f"✅ Записано: {ud['type']} → {ud['category']} → {ud.get('subcategory', '')}\n"
        f"Сума: {ud['amount']} {ud['currency']}\nДата: {date_str}"
    )
    ud.clear()
    await update.message.reply_text("Що далі?", reply_markup=main_menu_kb())
    return TYPE

# ====== APP START ======
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_type)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_category)],
            SUBCATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_subcategory)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_amount)],
            CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_currency)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_comment)],
            STATS: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_stats)],
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
