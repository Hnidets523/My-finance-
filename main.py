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

# ---- PDF ----
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph

# ========= CONFIG =========
BOT_TOKEN = "8420371366:AAG9UfAnEqKyrk5v1DOPHvh7hlp1ZDtHJy8"  # твій токен
ONLY_USER_ID = None  # за потреби вкажи свій Telegram ID

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

# ========= KEYBOARDS =========
def ikb(rows):
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

# ========= DATA =========
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

# ========= UTIL =========
async def edit_or_send(q, text, kb=None):
    """Редагує існуюче повідомлення або шле нове (на випадок, якщо старе вже не редагується)."""
    try:
        await q.message.edit_text(text, reply_markup=kb)
    except:
        await q.message.reply_text(text, reply_markup=kb)

# ========= COMMANDS =========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ обмежено.")
        return ConversationHandler.END
    txt = (
        "👋 Привіт! Я — фінансовий бот для обліку витрат, доходів та інвестицій.\n\n"
        "Натискай кнопки нижче.\n"
        "Засновник: @hnidets011"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_kb())
    return S.TYPE

# ========= CALLBACKS =========
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # Головне меню → вибір типу
    if data.startswith("type:"):
        code = data.split(":")[1]
        tname = TYPE_CODES[code]
        context.user_data.clear()
        context.user_data["type"] = tname
        context.user_data["cat_list"] = list(CATEGORIES[tname].keys())
        await edit_or_send(q, "Вибери категорію:", categories_kb(tname))
        return S.CATEGORY

    if data == "back:main":
        await edit_or_send(q, "Меню:", main_menu_kb())
        return S.TYPE

    # Категорії
    if data.startswith("cat:"):
        idx = int(data.split(":")[1])
        tname = context.user_data["type"]
        cats = context.user_data["cat_list"]
        if idx < 0 or idx >= len(cats):
            await edit_or_send(q, "Некоректна категорія. Обери ще раз:", categories_kb(tname))
            return S.CATEGORY
        cat = cats[idx]
        context.user_data["category"] = cat
        subs = CATEGORIES[tname][cat]
        if subs:
            context.user_data["sub_list"] = subs
            await edit_or_send(q, "Підкатегорія:", subcategories_kb(tname, cat))
            return S.SUBCATEGORY
        else:
            context.user_data["subcategory"] = None
            await edit_or_send(q, "Введи суму (наприклад 123.45):")
            return S.AMOUNT

    if data == "back:cats":
        tname = context.user_data["type"]
        await edit_or_send(q, "Вибери категорію:", categories_kb(tname))
        return S.CATEGORY

    # Підкатегорії
    if data.startswith("sub:"):
        if data == "sub:none":
            context.user_data["subcategory"] = None
        else:
            idx = int(data.split(":")[1])
            subs = context.user_data.get("sub_list", [])
            if idx < 0 or idx >= len(subs):
                await edit_or_send(q, "Некоректна підкатегорія. Обери ще раз:",
                                   subcategories_kb(context.user_data["type"], context.user_data["category"]))
                return S.SUBCATEGORY
            context.user_data["subcategory"] = subs[idx]
        await edit_or_send(q, "Введи суму (наприклад 123.45):")
        return S.AMOUNT

    # Валюта
    if data == "back:amount":
        await edit_or_send(q, "Введи суму ще раз:")
        return S.AMOUNT

    if data.startswith("cur:"):
        code = data.split(":")[1]
        context.user_data["currency"] = CURRENCIES[code]
        await edit_or_send(q, "📝 Додай коментар або '-' якщо без:")
        return S.COMMENT

    # Статистика
    if data == "stats:open" or data == "back:stats":
        await edit_or_send(q, "Оберіть режим:", stats_mode_kb())
        return S.STATS_MODE

    if data.startswith("stats:mode:"):
        mode = data.split(":")[2]  # month/day
        context.user_data["stats_mode"] = mode
        await edit_or_send(q, "Оберіть рік:", years_kb())
        return S.YEAR

    if data == "back:year":
        await edit_or_send(q, "Оберіть рік:", years_kb())
        return S.YEAR

    if data.startswith("stats:year:"):
        year = data.split(":")[2]
        context.user_data["year"] = year
        await edit_or_send(q, "Оберіть місяць:", months_kb())
        return S.MONTH

    if data == "back:month":
        await edit_or_send(q, "Оберіть місяць:", months_kb())
        return S.MONTH

    if data.startswith("stats:month:"):
        month = data.split(":")[2]
        context.user_data["month"] = month
        if context.user_data.get("stats_mode") == "month":
            text, tx = stats_text(update.effective_user.id, context.user_data["year"], month)
            context.user_data["tx"] = tx
            context.user_data["day"] = None
            kb = ikb([[("📄 Завантажити PDF", "stats:pdf")], [("⬅ Назад", "back:stats")]])
            await edit_or_send(q, text, kb)
            return S.PDF
        else:
            await edit_or_send(q, "Оберіть день:", days_kb(context.user_data["year"], month))
            return S.DAY

    if data.startswith("stats:day:"):
        day = data.split(":")[2]
        context.user_data["day"] = day
        text, tx = stats_text(update.effective_user.id, context.user_data["year"], context.user_data["month"], day)
        context.user_data["tx"] = tx
        kb = ikb([[("📄 Завантажити PDF", "stats:pdf")], [("⬅ Назад", "back:stats")]])
        await edit_or_send(q, text, kb)
        return S.PDF

    if data == "stats:pdf":
        tx = context.user_data.get("tx", [])
        if not tx:
            await edit_or_send(q, "📭 Немає даних для PDF.")
            return S.STATS_MODE
        year = context.user_data.get("year")
        month = context.user_data.get("month")
        day = context.user_data.get("day")
        title = f"Звіт за {day} {MONTH_NAMES[month]} {year}" if day else f"Звіт за {MONTH_NAMES[month]} {year}"
        filename = "report.pdf"
        generate_pdf(tx, filename, title)
        with open(filename, "rb") as f:
            await q.message.reply_document(InputFile(f, filename))
        await q.message.reply_text("✅ Готово", reply_markup=stats_mode_kb())
        return S.STATS_MODE

    # дефолт
    await edit_or_send(q, "Меню:", main_menu_kb())
    return S.TYPE

# ========= TEXT INPUTS =========
async def on_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").replace(",", ".").strip()
    try:
        amount = float(text)
    except Exception:
        await update.message.reply_text("Сума має бути числом. Приклад: 123.45")
        return S.AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text("Обери валюту:", reply_markup=currencies_kb())
    return S.CURRENCY

async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = (update.message.text or "").strip()
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
        ud.get("currency", CURRENCIES["UAH"]),
        comment,
        date_str
    )
    await update.message.reply_text(
        "✅ Записано:\n"
        f"{ud['type']} → {ud['category']} → {ud.get('subcategory','-')}\n"
        f"Сума: {ud['amount']} {ud.get('currency', CURRENCIES['UAH'])}\n"
        f"Дата: {date_str}\n"
        f"Коментар: {comment or '-'}",
        reply_markup=main_menu_kb()
    )
    ud.clear()
    return S.TYPE

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Скасовано.", reply_markup=main_menu_kb())
    return S.TYPE

# ========= APP =========
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            # callback-кроки
            S.TYPE: [CallbackQueryHandler(on_cb)],
            S.CATEGORY: [CallbackQueryHandler(on_cb)],
            S.SUBCATEGORY: [CallbackQueryHandler(on_cb)],
            S.CURRENCY: [CallbackQueryHandler(on_cb)],
            S.STATS_MODE: [CallbackQueryHandler(on_cb)],
            S.YEAR: [CallbackQueryHandler(on_cb)],
            S.MONTH: [CallbackQueryHandler(on_cb)],
            S.DAY: [CallbackQueryHandler(on_cb)],
            S.PDF: [CallbackQueryHandler(on_cb)],
            # текстові кроки
            S.AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_amount)],
            S.COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_comment)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling()

if __name__ == "__main__":
    main()
