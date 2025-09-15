import os
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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")  # з Railway → Variables
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено. Додай у Railway → Variables.")

# Зареєструємо кириличний шрифт (файл DejaVuSans.ttf має лежати поряд із main.py)
pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

TYPE_CODES = {"exp": "💸 Витрати", "inc": "💰 Надходження", "inv": "📈 Інвестиції"}
CURRENCIES = {"UAH": "грн", "USD": "$"}
CURRENCY_LIST = [("грн", "UAH"), ("$", "USD")]  # (label, code)

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

# Користувачі (особистий кабінет)
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    currency TEXT DEFAULT 'грн',
    monthly_budget REAL,
    created_at TEXT
)
""")

# Транзакції
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
    # Профіль / онбординг
    ASK_NAME = auto()
    ASK_CURRENCY = auto()
    PROFILE = auto()
    PROFILE_EDIT_NAME = auto()

# ========= LOGGING =========
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finance-bot")

# ========= HELPERS (DB) =========
def get_user(user_id: int):
    cur.execute("SELECT user_id, name, currency, monthly_budget, created_at FROM users WHERE user_id=?", (user_id,))
    return cur.fetchone()

def create_or_update_user(user_id: int, name: str, currency: str):
    cur.execute("""
        INSERT INTO users (user_id, name, currency, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, currency=excluded.currency
    """, (user_id, name, currency, datetime.utcnow().isoformat()))
    conn.commit()

def update_user_name(user_id: int, name: str):
    cur.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
    conn.commit()

def update_user_currency(user_id: int, currency: str):
    cur.execute("UPDATE users SET currency=? WHERE user_id=?", (currency, user_id))
    conn.commit()

def user_currency(user_id: int) -> str:
    u = get_user(user_id)
    return u[2] if u and u[2] else "грн"

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

# ========= KEYBOARDS =========
def ikb(rows):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d) for (t, d) in row] for row in rows]
    )

def main_menu_kb():
    return ikb([
        [("💸 Витрати", "type:exp"), ("💰 Надходження", "type:inc")],
        [("📈 Інвестиції", "type:inv")],
        [("📊 Статистика", "stats:open"), ("👤 Мій профіль", "profile:open")]
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

def currencies_kb_inline():
    rows = [[(label, f"cur:{code}") for (label, code) in CURRENCY_LIST]]
    return ikb(rows)

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

# ========= TEXT/REPORT =========
def stats_text(user_id, year, month=None, day=None):
    tx = fetch_transactions(user_id, year, month, day)
    title = f"📅 {day} {MONTH_NAMES[month]} {year}" if day else f"📆 {MONTH_NAMES[month]} {year}"
    if not tx:
        return f"{title}\n📭 Немає записів.", tx

    sums = {"💸 Витрати": 0, "💰 Надходження": 0, "📈 Інвестиції": 0}
    lines = []
    for t, cat, sub, amt, curr, com in tx:
        sums[t] += float(amt or 0)
        lines.append(f"- {t} | {cat}/{sub or '-'}: {amt:.2f} {curr} ({com or '-'})")
    totals = "\n".join([f"{t}: {sums[t]:.2f}" for t in sums])
    return f"{title}\n\n" + "\n".join(lines) + f"\n\nПідсумок:\n{totals}", tx

def generate_pdf(transactions, filename, title):
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='NormalUkr', fontName='DejaVu', fontSize=11, leading=14))
    elements = [Paragraph(title, styles["NormalUkr"])]

    data = [["Тип", "Категорія", "Підкатегорія", "Сума", "Валюта", "Коментар"]]
    totals = {"💸 Витрати": 0, "💰 Надходження": 0, "📈 Інвестиції": 0}

    for t, cat, sub, amt, curr, com in transactions:
        a = float(amt or 0)
        totals[t] += a
        data.append([t, cat, sub or "-", f"{a:.2f}", curr, com or "-"])

    data.append(["", "", "", "", "", ""])
    for t in totals:
        data.append([t, "", "", f"{totals[t]:.2f}", "", ""])

    table = Table(data, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(table)
    doc.build(elements)

# ========= UTIL =========
async def edit_or_send(q, text, kb=None):
    try:
        await q.message.edit_text(text, reply_markup=kb)
    except:
        await q.message.reply_text(text, reply_markup=kb)

# ========= START / ONBOARDING =========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text(
            "👋 Привіт! Я — фінансовий бот. Давай познайомимось.\nЯк до тебе звертатись?"
        )
        return S.ASK_NAME
    await update.message.reply_text(f"👋 Привіт, {u[1]}!", reply_markup=main_menu_kb())
    return S.TYPE

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи ім'я, будь ласка 🙂")
        return S.ASK_NAME
    context.user_data["new_name"] = name
    await update.message.reply_text("💱 Обери валюту за замовчуванням:", reply_markup=currencies_kb_inline())
    return S.ASK_CURRENCY

async def ask_currency_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data  # cur:UAH / cur:USD
    code = data.split(":")[1]
    label = CURRENCIES[code]
    name = context.user_data.get("new_name", update.effective_user.first_name or "Користувач")

    create_or_update_user(update.effective_user.id, name, label)
    await edit_or_send(q, f"✅ Профіль створено!\nІм'я: {name}\nВалюта: {label}", main_menu_kb())
    context.user_data.pop("new_name", None)
    return S.TYPE

# ========= PROFILE =========
async def profile_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = get_user(update.effective_user.id)
    if not u:
        await edit_or_send(q, "Спершу запусти /start для створення профілю.")
        return S.TYPE
    text = (f"👤 Профіль\n\n"
            f"Ім'я: {u[1]}\n"
            f"Валюта: {u[2]}\n"
            f"Місячний бюджет: {u[3] or 'Не задано'}\n"
            f"Зареєстрований: {u[4][:10] if u[4] else '-'}")
    kb = ikb([
        [("✏️ Змінити ім'я", "profile:edit_name"), ("💱 Змінити валюту", "profile:edit_currency")],
        [("⬅ Назад", "back:main")]
    ])
    await edit_or_send(q, text, kb)
    return S.PROFILE

async def profile_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "profile:edit_name":
        await edit_or_send(q, "Введи нове ім'я:")
        return S.PROFILE_EDIT_NAME
    if data == "profile:edit_currency":
        await edit_or_send(q, "Обери валюту:", currencies_kb_inline())
        return S.ASK_CURRENCY
    if data == "back:main":
        await edit_or_send(q, "Меню:", main_menu_kb())
        return S.TYPE
    return S.PROFILE

async def profile_set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи коректне ім'я 🙂")
        return S.PROFILE_EDIT_NAME
    update_user_name(update.effective_user.id, name)
    await update.message.reply_text("✅ Ім'я змінено.", reply_markup=main_menu_kb())
    return S.TYPE

# ========= CORE FLOW (тип → категорія → підкатегорія → сума → валюта → коментар) =========
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # Головне меню: тип операції
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
        tname = context.user_data.get("type")
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

    # Валюта (з кнопки)
    if data.startswith("cur:"):
        code = data.split(":")[1]  # UAH / USD
        label = CURRENCIES[code]
        context.user_data["currency"] = label
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

    # Профіль відкривається окремим хендлером (profile:open),
    # а цей on_cb обробляє решту callback-кнопок.
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

    # Пропонуємо вибір валюти або беремо валюту користувача за замовчуванням
    u_curr = user_currency(update.effective_user.id)
    kb = ikb([[("Використати валюту профілю", f"cur_profile:{u_curr}")],
              [(CURRENCIES["UAH"], "cur:UAH"), (CURRENCIES["USD"], "cur:USD")]])
    await update.message.reply_text(f"Обери валюту (або тисни 'Використати валюту профілю: {u_curr}'):", reply_markup=kb)
    return S.CURRENCY

async def on_currency_from_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # cur_profile:грн  — зберігаємо як є (рядок-лейбл)
    label = q.data.split(":", 1)[1]
    context.user_data["currency"] = label
    await edit_or_send(q, "📝 Додай коментар або '-' якщо без:")
    return S.COMMENT

async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = (update.message.text or "").strip()
    if comment == "-":
        comment = None
    ud = context.user_data
    # Якщо не обрали валюту кнопкою — беремо валюту профілю
    currency = ud.get("currency", user_currency(update.effective_user.id))
    date_str = datetime.now().strftime("%Y-%m-%d")

    save_tx(
        update.effective_user.id,
        ud["type"],
        ud["category"],
        ud.get("subcategory"),
        ud["amount"],
        currency,
        comment,
        date_str
    )
    await update.message.reply_text(
        "✅ Записано:\n"
        f"{ud['type']} → {ud['category']} → {ud.get('subcategory','-')}\n"
        f"Сума: {ud['amount']} {currency}\n"
        f"Дата: {date_str}\n"
        f"Коментар: {comment or '-'}",
        reply_markup=main_menu_kb()
    )
    ud.clear()
    return S.TYPE

# ========= APP =========
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            # Онбординг
            S.ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            S.ASK_CURRENCY: [
                CallbackQueryHandler(ask_currency_cb, pattern=r"^cur:(UAH|USD)$")
            ],

            # Профіль
            S.PROFILE: [
                CallbackQueryHandler(profile_router, pattern=r"^(profile:edit_name|profile:edit_currency|back:main)$")
            ],
            S.PROFILE_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_set_name)
            ],

            # Основний флоу
            S.TYPE: [
                CallbackQueryHandler(on_cb, pattern=r"^(type:|back:main|stats:open)$"),
                CallbackQueryHandler(profile_open, pattern=r"^profile:open$")
            ],
            S.CATEGORY: [CallbackQueryHandler(on_cb, pattern=r"^(cat:|back:main)$")],
            S.SUBCATEGORY: [CallbackQueryHandler(on_cb, pattern=r"^(sub:|back:cats)$")],
            S.AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_amount)],
            S.CURRENCY: [
                CallbackQueryHandler(on_cb, pattern=r"^cur:(UAH|USD)$"),
                CallbackQueryHandler(on_currency_from_profile, pattern=r"^cur_profile:")
            ],
            S.COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_comment)],

            # Статистика / PDF
            S.STATS_MODE: [CallbackQueryHandler(on_cb, pattern=r"^(stats:mode:|back:main|back:stats)$")],
            S.YEAR: [CallbackQueryHandler(on_cb, pattern=r"^(stats:year:|back:stats)$")],
            S.MONTH: [CallbackQueryHandler(on_cb, pattern=r"^(stats:month:|back:year)$")],
            S.DAY: [CallbackQueryHandler(on_cb, pattern=r"^(stats:day:|back:month)$")],
            S.PDF: [CallbackQueryHandler(on_cb, pattern=r"^(stats:pdf|back:stats)$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(conv)
    # Додатково окремо ловимо відкриття профілю зі стартового меню
    app.add_handler(CallbackQueryHandler(profile_open, pattern=r"^profile:open$"))
    return app

def main():
    app = build_app()
    app.run_polling()

if __name__ == "__main__":
    main()
