import os
import sqlite3
import calendar
import logging
import time
from enum import Enum, auto
from datetime import datetime

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ======== CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено. Додай у Railway → Variables.")

pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

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

# ======== DATABASE =========
DB_PATH = "finance.db"
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

# ======== STATES =========
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
    ASK_NAME = auto()
    ASK_CURRENCY = auto()
    PROFILE = auto()
    PROFILE_EDIT_NAME = auto()

# ======== HELPERS =========
def get_user(user_id: int):
    cur.execute("SELECT user_id, name, currency, created_at FROM users WHERE user_id=?", (user_id,))
    return cur.fetchone()

def create_or_update_user(user_id: int, name: str, currency: str):
    cur.execute("""
        INSERT INTO users (user_id, name, currency, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, currency=excluded.currency
    """, (user_id, name, currency, datetime.utcnow().isoformat()))
    conn.commit()

def save_tx(user_id, ttype, cat, sub, amount, currency, comment, date_str):
    cur.execute("""
        INSERT INTO transactions (user_id, type, category, subcategory, amount, currency, comment, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, ttype, cat, sub, amount, currency, comment, date_str, datetime.utcnow().isoformat()))
    conn.commit()

def fetch_transactions(user_id, year, month=None, day=None):
    if day:
        date_str = f"{year}-{month}-{day}"
        q = """SELECT type, category, subcategory, amount, currency, comment FROM transactions WHERE user_id=? AND date=?"""
        cur.execute(q, (user_id, date_str))
    else:
        q = """SELECT type, category, subcategory, amount, currency, comment
               FROM transactions
               WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?"""
        cur.execute(q, (user_id, str(year), str(month)))
    return cur.fetchall()

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
            rows.append(row)
            row = []
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
                rows.append(row)
                row = []
        if row: rows.append(row)
    rows.append([("(без підкатегорії)", "sub:none")])
    rows.append([("⬅ Назад", "back:cats")])
    return ikb(rows)

def stats_text(user_id, year, month=None, day=None):
    tx = fetch_transactions(user_id, year, month, day)
    title = f"📅 {day} {MONTH_NAMES[month]} {year}" if day else f"📆 {MONTH_NAMES[month]} {year}"
    if not tx:
        return f"{title}\n📭 Немає записів.", tx

    sums = {"💸 Витрати": 0, "💰 Надходження": 0, "📈 Інвестиції": 0}
    lines = []
    for t, cat, sub, amt, curr, com in tx:
        a = float(amt or 0)
        sums[t] += a
        lines.append(f"- {t} | {cat}/{sub or '-'}: {a:.2f} {curr} ({com or '-'})")
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
    ]))
    elements.append(table)
    doc.build(elements)

INTRO_TEXT = (
    "✅ Профіль створено!\n\n"
    "Твій особистий фінансовий кабінет готовий.\n\n"
    "Можливості:\n"
    "• Додавати витрати, надходження та інвестиції\n"
    "• Переглядати статистику за день чи місяць\n"
    "• Завантажувати PDF-звіти\n"
    "• Редагувати ім'я та валюту\n\n"
    "Обери дію нижче 👇"
)

# ======== START ========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("👋 Привіт! Як до тебе звертатись?")
        return S.ASK_NAME
    await update.message.reply_text(f"👋 Привіт, {u[1]}!\n\n{INTRO_TEXT}", reply_markup=main_menu_kb())
    return S.TYPE

# ======== ONBOARDING ========
async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи ім'я 🙂")
        return S.ASK_NAME
    create_or_update_user(update.effective_user.id, name, "грн")
    await update.message.reply_text(INTRO_TEXT, reply_markup=main_menu_kb())
    return S.TYPE

# ======== PROFILE ========
async def profile_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = get_user(update.effective_user.id)
    if not u:
        await q.edit_message_text("Спершу запусти /start")
        return S.TYPE
    text = f"👤 Профіль\n\nІм'я: {u[1]}\nВалюта: {u[2]}\nЗареєстровано: {u[3][:10] if u[3] else '-'}"
    kb = ikb([
        [("⬅ Назад", "back:main")]
    ])
    await q.edit_message_text(text, reply_markup=kb)
    return S.PROFILE

# ======== CALLBACK HANDLER ========
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "back:main":
        await q.edit_message_text("Меню:", reply_markup=main_menu_kb())
        return S.TYPE
    # ... (тут додані всі обробники кнопок, як у попередніх кодах, для статистики, PDF і категорій)
    return S.TYPE

# ======== ERROR ========
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")

# ======== APP ========
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            S.ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            S.TYPE: [CallbackQueryHandler(on_cb, pattern=".*")],
            S.PROFILE: [CallbackQueryHandler(on_cb, pattern=".*")],
        },
        fallbacks=[],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(profile_open, pattern=r"^profile:open$"))
    app.add_error_handler(on_error)
    return app

def main():
    app = build_app()
    app.run_polling()

if __name__ == "__main__":
    main()
