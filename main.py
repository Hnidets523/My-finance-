import sqlite3
from datetime import datetime
import calendar
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
    ConversationHandler
)

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph

# ====== CONFIG ======
BOT_TOKEN = "8420371366:AAG9UfAnEqKyrk5v1DOPHvh7hlp1ZDtHJy8"  # твій токен
ONLY_USER_ID = None  # за бажанням: вкажи свій Telegram ID, щоб обмежити доступ

TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції", "📊 Статистика"]

MONTH_NAMES = {
    "01": "Січень", "02": "Лютий", "03": "Березень", "04": "Квітень",
    "05": "Травень", "06": "Червень", "07": "Липень", "08": "Серпень",
    "09": "Вересень", "10": "Жовтень", "11": "Листопад", "12": "Грудень"
}

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
PDF_OPTION = ["📄 Завантажити PDF-звіт", "↩️ Назад"]

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
TYPE, CATEGORY, SUBCATEGORY, AMOUNT, CURRENCY, COMMENT, STATS_MODE, YEAR, MONTH, DAY, PDF = range(11)

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
        ["Січень", "Лютий", "Березень"],
        ["Квітень", "Травень", "Червень"],
        ["Липень", "Серпень", "Вересень"],
        ["Жовтень", "Листопад", "Грудень"]
    ]
    months.append(["↩️ Назад"])
    return kb(months)

def month_to_number(name):
    for num, n in MONTH_NAMES.items():
        if n == name:
            return num
    return "01"

def days_kb(year, month):
    days_in_month = calendar.monthrange(int(year), int(month))[1]
    days = [str(i) for i in range(1, days_in_month + 1)]
    rows = [days[i:i+7] for i in range(0, len(days), 7)]
    rows.append(["↩️ Назад"])
    return kb(rows)

# ====== DB HELPERS ======
def fetch_transactions(user_id, year, month=None, day=None):
    if day:
        date_str = f"{year}-{month}-{day.zfill(2)}"
        query = "SELECT type, category, subcategory, amount, currency, comment FROM transactions WHERE user_id=? AND date=?"
        params = (user_id, date_str)
    else:
        query = """
            SELECT type, category, subcategory, amount, currency, comment FROM transactions
            WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?
        """
        params = (user_id, str(year), str(month).zfill(2))
    cur.execute(query, params)
    return cur.fetchall()

def save_tx(user_id, ttype, cat, sub, amount, currency, comment, date_str):
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, ttype, cat, sub, amount, currency, comment, date_str, datetime.utcnow().isoformat()))
    conn.commit()

# ====== PDF ======
def generate_pdf(transactions, filename, title):
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Heading1"])]

    data = [["Тип", "Категорія", "Підкатегорія", "Сума", "Валюта", "Коментар"]]
    total = {"💸 Витрати": 0, "💰 Надходження": 0, "📈 Інвестиції": 0}

    for t, cat, sub, amt, curr, com in transactions:
        total[t] += amt
        data.append([t, cat, sub if sub else "-", f"{amt:.2f}", curr, com if com else "-"])

    # Порожній рядок і підсумки
    data.append(["", "", "", "", "", ""])
    for t in total:
        data.append([t, "", "", f"{total[t]:.2f}", "", ""])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ]))
    elements.append(table)
    doc.build(elements)

# ====== STATS TEXT ======
def get_detailed_stats_text(user_id, year, month=None, day=None):
    transactions = fetch_transactions(user_id, year, month, day)

    if day:
        title = f"📅 Детальна статистика за {day.zfill(2)} {MONTH_NAMES[month]} {year}:"
    else:
        title = f"📆 Детальна статистика за {MONTH_NAMES[month]} {year}:"

    if not transactions:
        return title + "\n📭 Немає записів.", transactions

    summary = {t: 0 for t in ["💸 Витрати", "💰 Надходження", "📈 Інвестиції"]}
    lines = []
    for t, cat, sub, amt, curr, com in transactions:
        summary[t] += amt
        lines.append(f"- {t} | {cat} / {sub if sub else '-'}: {amt:.2f} {curr} ({com if com else '-'})")

    totals = "\n".join([f"{t}: {summary[t]:.2f}" for t in summary])
    text = f"{title}\n\n" + "\n".join(lines) + f"\n\nПідсумок:\n{totals}"
    return text, transactions

# ====== GUARDS (опційно обмеження користувача) ======
def is_allowed(user_id: int) -> bool:
    return (ONLY_USER_ID is None) or (user_id == ONLY_USER_ID)

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ обмежено.")
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привіт! Я — фінансовий бот для обліку витрат, доходів та інвестицій.\n"
        "💸 Додавай витрати\n💰 Фіксуй доходи\n📈 Облік інвестицій\n📊 Переглядай статистику\n\n"
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
        await update.message.reply_text("Головне меню:", reply_markup=main_menu_kb())
        return TYPE
    context.user_data["stats_mode"] = mode
    await update.message.reply_text("Оберіть рік:", reply_markup=years_kb())
    return YEAR

async def choose_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = update.message.text
    if year == "↩️ Назад":
        await update.message.reply_text("Повернувся до режимів:", reply_markup=stats_modes_kb())
        return STATS_MODE
    context.user_data["year"] = year
    await update.message.reply_text("Оберіть місяць:", reply_markup=months_kb())
    return MONTH

async def choose_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_name = update.message.text
    if month_name == "↩️ Назад":
        await update.message.reply_text("Повернувся до вибору року:", reply_markup=years_kb())
        return YEAR

    month_num = month_to_number(month_name)
    context.user_data["month"] = month_num

    if context.user_data.get("stats_mode") == "📆 За місяць":
        text, transactions = get_detailed_stats_text(update.effective_user.id, context.user_data["year"], month_num)
        context.user_data["transactions"] = transactions
        context.user_data["day"] = None
        await update.message.reply_text(text, reply_markup=kb([PDF_OPTION]))
        return PDF

    await update.message.reply_text("Оберіть день:", reply_markup=days_kb(context.user_data["year"], month_num))
    return DAY

async def choose_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = update.message.text
    if day == "↩️ Назад":
        await update.message.reply_text("Повернувся до вибору місяця:", reply_markup=months_kb())
        return MONTH

    text, transactions = get_detailed_stats_text(
        update.effective_user.id,
        context.user_data["year"],
        context.user_data["month"],
        day
    )
    context.user_data["transactions"] = transactions
    context.user_data["day"] = day
    await update.message.reply_text(text, reply_markup=kb([PDF_OPTION]))
    return PDF

async def pdf_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == "↩️ Назад":
        await update.message.reply_text("Повернувся до режимів:", reply_markup=stats_modes_kb())
        return STATS_MODE

    if choice != "📄 Завантажити PDF-звіт":
        await update.message.reply_text("Оберіть дію:", reply_markup=kb([PDF_OPTION]))
        return PDF

    transactions = context.user_data.get("transactions", [])
    if not transactions:
        await update.message.reply_text("📭 Немає даних для PDF.")
        return STATS_MODE

    year = context.user_data.get("year")
    month = context.user_data.get("month")
    day = context.user_data.get("day")

    title = (
        f"Звіт за {day.zfill(2)} {MONTH_NAMES[month]} {year}"
        if day else f"Звіт за {MONTH_NAMES[month]} {year}"
    )
    filename = "report.pdf"
    generate_pdf(transactions, filename, title)

    with open(filename, "rb") as f:
        await update.message.reply_document(InputFile(f, filename))
    await update.message.reply_text("✅ Ось ваш PDF-звіт", reply_markup=stats_modes_kb())
    return STATS_MODE

# ==== Додавання транзакцій ====
async def pick_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    t = context.user_data.get("type")
    if text == "↩️ Назад":
        await update.message.reply_text("Головне меню:", reply_markup=main_menu_kb())
        return TYPE
    if t not in CATEGORIES or text not in CATEGORIES[t]:
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
            PDF: [MessageHandler(filters.TEXT & ~filters.COMMAND, pdf_menu)],
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
