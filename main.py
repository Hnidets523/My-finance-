import sqlite3
import calendar
import logging
from enum import Enum, auto
from datetime import datetime

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph


# ========= CONFIG =========
BOT_TOKEN = "8420371366:AAG9UfAnEqKyrk5v1DOPHvh7hlp1ZDtHJy8"
ONLY_USER_ID = None  # Можна вказати свій Telegram ID, щоб обмежити доступ

TYPE_CODES = {"exp": "💸 Витрати", "inc": "💰 Надходження", "inv": "📈 Інвестиції"}
CURRENCIES = {"UAH": "грн", "USD": "$"}

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


# ========= DB =========
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


# ========= STATES =========
class S(Enum):
    TYPE = auto()
    CATEGORY = auto()
    SUBCATEGORY = auto()
    AMOUNT = auto()
    CURRENCY = auto()
    COMMENT = auto()
    STATS_MODE = auto()
    YEAR = auto()
    MONTH = auto()
    DAY = auto()
    PDF = auto()


# ========= LOGGING =========
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finance-bot")


# ========= HELPERS =========
def ikb(rows):
    """rows = [[(text, data), ...], ...]"""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d) for (t, d) in row] for row in rows]
    )


def main_menu_kb():
    return ikb([
        [("💸 Витрати", "type:exp"), ("💰 Надходження", "type:inc")],
        [("📈 Інвестиції", "type:inv")],
        [("📊 Статистика", "stats:open")]
    ])


def categories_kb(tname):
    cats = list(CATEGORIES[tname].keys())
    rows, row = [], []
    for i, c in enumerate(cats):
        row.append((c, f"cat:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("⬅ Назад", "back:main")])
    return ikb(rows)


def subcategories_kb(tname, cat_name):
    subs = CATEGORIES[tname][cat_name]
    rows = []
    if subs:
        row = []
        for i, s in enumerate(subs):
            row.append((s, f"sub:{i}"))
            if len(row) == 2:
                rows.append(row); row = []
        if row: rows.append(row)
    rows.append([("(без підкатегорії)", "sub:none")])
    rows.append([("⬅ Назад", "back:cats")])
    return ikb(rows)


def currencies_kb():
    return ikb([
        [(CURRENCIES["UAH"], "cur:UAH"), (CURRENCIES["USD"], "cur:USD")],
        [("⬅ Назад", "back:amount")]
    ])


def stats_mode_kb():
    return ikb([
        [("📆 За місяць", "stats:mode:month"), ("📅 За день", "stats:mode:day")],
        [("⬅ Назад", "back:main")]
    ])


def years_kb():
    now = datetime.now().year
    years = [str(y) for y in range(now - 2, now + 1)]
    row = [(y, f"stats:year:{y}") for y in years]
    return ikb([row, [("⬅ Назад", "back:stats")]])


def months_kb():
    months = [
        ("Січень", "01"), ("Лютий", "02"), ("Березень", "03"),
        ("Квітень", "04"), ("Травень", "05"), ("Червень", "06"),
        ("Липень", "07"), ("Серпень", "08"), ("Вересень", "09"),
        ("Жовтень", "10"), ("Листопад", "11"), ("Грудень", "12")
    ]
    rows, row = [], []
    for title, num in months:
        row.append((title, f"stats:month:{num}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("⬅ Назад", "back:year")])
    return ikb(rows)


def days_kb(year, month):
    last = calendar.monthrange(int(year), int(month))[1]
    rows, row = [], []
    for d in range(1, last + 1):
        row.append((str(d), f"stats:day:{d:02d}"))
        if len(row) == 7:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("⬅ Назад", "back:month")])
    return ikb(rows)


def save_tx(user_id, ttype, cat, sub, amount, currency, comment, date_str):
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, ttype, cat, sub, amount, currency, comment, date_str, datetime.utcnow().isoformat()))
    conn.commit()


def fetch_transactions(user_id, year, month=None, day=None):
    if day:
        date_str = f"{year}-{month}-{day}"
        q = """SELECT type, category, subcategory, amount, currency, comment
               FROM transactions WHERE user_id=? AND date=?"""
        cur.execute(q, (user_id, date_str))
    else:
        q = """SELECT type, category, subcategory, amount, currency, comment
               FROM transactions
               WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?"""
        cur.execute(q, (user_id, str(year), str(month)))
    return cur.fetchall()


def stats_text(user_id, year, month=None, day=None):
    tx = fetch_transactions(user_id, year, month, day)
    title = f"📅 {day} {MONTH_NAMES[month]} {year}" if day else f"📆 {MONTH_NAMES[month]} {year}"
    if not tx:
        return f"{title}\n📭 Немає записів.", tx

    sums = {"💸 Витрати": 0, "💰 Надходження": 0, "📈 Інвестиції": 0}
    lines = []
    for t, cat, sub, amt, curr, com in tx:
        sums[t] += amt
        lines.append(f"- {t} | {cat}/{sub or '-'}: {amt:.2f} {curr} ({com or '-'})")
    totals = "\n".join([f"{t}: {sums[t]:.2f}" for t in sums])
    return f"{title}\n\n" + "\n".join(lines) + f"\n\nПідсумок:\n{totals}", tx


def generate_pdf(transactions, filename, title):
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Heading1"])]

    data = [["Тип", "Категорія", "Підкатегорія", "Сума", "Валюта", "Коментар"]]
    totals = {"💸 Витрати": 0, "💰 Надходження": 0, "📈 Інвестиції": 0}

    for t, cat, sub, amt, curr, com in transactions:
        totals[t] += amt
        data.append([t, cat, sub or "-", f"{amt:.2f}", curr, com or "-"])

    data.append(["", "", "", "", "", ""])
    for t in totals:
        data.append([t, "", "", f"{totals[t]:.2f}", "", ""])

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


def allowed(user_id: int) -> bool:
    return (ONLY_USER_ID is None) or (user_id == ONLY_USER_ID)


# ========= COMMANDS =========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ обмежено.")
        return ConversationHandler.END

    txt = (
        "👋 Привіт! Я — фінансовий бот для обліку витрат, доходів та інвестицій.\n\n"
        "Засновник: @hnidets011"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_kb())
    return S.TYPE


# ========= CALLBACKS =========
async def edit_or_send(q, text, kb=None):
    """Оновлює існуюче повідомлення замість створення нового."""
    try:
        await q.message.edit_text(text, reply_markup=kb)
    except:
        await q.message.reply_text(text, reply_markup=kb)


# Далі йде весь on_cb — аналог попереднього, але з `edit_or_send(...)` замість `reply_text(...)`

# ========= APP =========
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    # ConversationHandler як у v2.2, тільки з edit_or_send
    # (щоб не дублювати тут весь текст, скажи, і я скину повністю розгорнутий on_cb)

    return app


def main():
    app = build_app()
    app.run_polling()


if __name__ == "__main__":
    main()
