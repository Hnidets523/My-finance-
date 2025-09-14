import sqlite3
from datetime import datetime
import calendar
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
    ConversationHandler
)

# ====== CONFIG ======
BOT_TOKEN = "8420371366:AAG9UfAnEqKyrk5v1DOPHvh7hlp1ZDtHJy8"
ONLY_USER_ID = None

TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції", "📊 Статистика"]

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
STATS_MODES = ["📆 За місяць", "📅 За день", "↩️ Назад"]

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
TYPE, CATEGORY, SUBCATEGORY, AMOUNT, CURRENCY, COMMENT, STATS_MODE, YEAR, MONTH, DAY = range(10)

# ====== KEYBOARDS ======
def kb(rows):
    return ReplyKeyboardMarkup([[KeyboardButton(x) for x in row] for row in rows], resize_keyboard=True)

def main_menu_kb():
    return kb([TYPES])

def categories_kb(for_type):
    cats = list(CATEGORIES[for_type].keys())
    rows, row = [], []
    for c in cats:
        row.append(c)
        if len(row) == 2:
            rows.append(row); row = []
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
                rows.append(row); row = []
        if row: rows.append(row)
    rows.append(["(без підкатегорії)", "↩️ Назад"])
    return kb(rows)

def currencies_kb():
    return kb([CURRENCIES, ["↩️ Назад"]])

def stats_modes_kb():
    return kb([STATS_MODES])

def years_kb():
    now = datetime.now()
    years = [str(y) for y in range(now.year - 2, now.year + 1)]
    return kb([years, ["↩️ Назад"]])

def months_kb():
    months = [
        ["01", "02", "03"],
        ["04", "05", "06"],
        ["07", "08", "09"],
        ["10", "11", "12"]
    ]
    months.append(["↩️ Назад"])
    return kb(months)

def days_kb(year, month):
    days_in_month = calendar.monthrange(int(year), int(month))[1]
    days = [str(i) for i in range(1, days_in_month + 1)]
    rows = [days[i:i+7] for i in range(0, len(days), 7)]
    rows.append(["↩️ Назад"])
    return kb(rows)

# ====== DB FUNCTIONS ======
def save_tx(user_id, ttype, cat, sub, amount, currency, comment, date_str):
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, ttype, cat, sub, amount, currency, comment, date_str, datetime.utcnow().isoformat()))
    conn.commit()

def get_detailed_stats(user_id, year, month=None, day=None):
    if day:
        date_str = f"{year}-{month}-{day.zfill(2)}"
        query = "SELECT type, category, subcategory, amount, currency, comment FROM transactions WHERE user_id=? AND date=?"
        params = (user_id, date_str)
        title = f"📅 Детальна статистика за {date_str}:"
    else:
        query = """
            SELECT type, category, subcategory, amount, currency, comment FROM transactions
            WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?
        """
        params = (user_id, str(year), str(month).zfill(2))
        title = f"📆 Детальна статистика за {year}-{month.zfill(2)}:"

    cur.execute(query, params)
    rows = cur.fetchall()
    if not rows:
        return f"{title}\n📭 Немає записів."

    summary = {t: 0 for t in ["💸 Витрати", "💰 Надходження", "📈 Інвестиції"]}
    details = []
    for t, cat, sub, amt, curr, com in rows:
        summary[t] += amt
        details.append(f"- {t} | {cat} / {sub if sub else '-'}: {amt:.2f} {curr} ({com if com else '-'})")

    totals = "\n".join([f"{t}: {summary[t]:.2f}" for t in summary])
    return f"{title}\n\n" + "\n".join(details) + f"\n\nПідсумок:\n{totals}"

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Я — фінансовий бот для обліку витрат, доходів та інвестицій.\n"
        "Тут ти можеш:\n"
        "💸 Додавати витрати\n💰 Фіксувати доходи\n📈 Облік інвестицій\n📊 Переглядати статистику\n\n"
        "Засновник: @hnidets011",
        reply_markup=main_menu_kb()
    )
    return TYPE

async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "📊 Статистика":
        await update.message.reply_text("Оберіть режим:", reply_markup=stats_modes_kb())
        return STATS_MODE
    if t not in TYPES:
        await update.message.reply_text("Будь ласка, оберіть кнопку:", reply_markup=main_menu_kb())
        return TYPE
    context.user_data["type"] = t
    await update.message.reply_text("Виберіть категорію:", reply_markup=categories_kb(t))
    return CATEGORY

async def choose_stats_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = update.message.text
    if mode == "↩️ Назад":
        await update.message.reply_text("Повернувся в головне меню:", reply_markup=main_menu_kb())
        return TYPE
    context.user_data["stats_mode"] = mode
    await update.message.reply_text("Оберіть рік:", reply_markup=years_kb())
    return YEAR

async def choose_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = update.message.text
    if year == "↩️ Назад":
        await update.message.reply_text("Повернувся до вибору режиму:", reply_markup=stats_modes_kb())
        return STATS_MODE
    context.user_data["year"] = year
    await update.message.reply_text("Оберіть місяць:", reply_markup=months_kb())
    return MONTH

async def choose_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month = update.message.text
    if month == "↩️ Назад":
        await update.message.reply_text("Повернувся до вибору року:", reply_markup=years_kb())
        return YEAR
    context.user_data["month"] = month
    if context.user_data["stats_mode"] == "📆 За місяць":
        stats = get_detailed_stats(update.effective_user.id, context.user_data["year"], month)
        await update.message.reply_text(stats, reply_markup=stats_modes_kb())
        return STATS_MODE
    await update.message.reply_text("Оберіть день:", reply_markup=days_kb(context.user_data["year"], month))
    return DAY

async def choose_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = update.message.text
    if day == "↩️ Назад":
        await update.message.reply_text("Повернувся до вибору місяця:", reply_markup=months_kb())
        return MONTH
    stats = get_detailed_stats(update.effective_user.id, context.user_data["year"], context.user_data["month"], day)
    await update.message.reply_text(stats, reply_markup=stats_modes_kb())
    return STATS_MODE

# ==== решта логіки додавання витрат ====
async def pick_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    t = context.user_data.get("type")
    if text == "↩️ Назад":
        await update.message.reply_text("Головне меню:", reply_markup=main_menu_kb())
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
        await update.message.reply_text("Категорії:", reply_markup=categories_kb(t))
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
    await update.message.reply_text("💱 Обери валюту:", reply_markup=currencies_kb())
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
    await update.message.reply_text("📝 Додай коментар або напиши '-' якщо без:", reply_markup=kb([["-"]]))
    return COMMENT

async def pick_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    if comment.strip() == "-":
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
        f"✅ Записано:\n{ud['type']} → {ud['category']} → {ud.get('subcategory', '-')}\n"
        f"Сума: {ud['amount']} {ud['currency']}\nДата: {date_str}\nКоментар: {comment if comment else '-'}"
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
            STATS_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_stats_mode)],
            YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_year)],
            MONTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_month)],
            DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_day)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_category)],
            SUBCATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_subcategory)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_amount)],
            CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_currency)],
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
