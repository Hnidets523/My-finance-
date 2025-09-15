import os
import sqlite3
import calendar
import random
from datetime import datetime
from collections import defaultdict

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Charts
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ====== CONFIG ======
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Railway → Variables
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено у змінних середовища (Railway → Variables).")

pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

DB_PATH = "finance.db"

# ====== DB ======
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

# ====== DATA ======
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
MONTHS_BY_NAME = {v: k for k, v in MONTHS.items()}

TIPS = [
    "Не заощаджуй те, що залишилось після витрат — витрачай те, що залишилось після заощаджень. — Уоррен Баффет",
    "Бюджет — це те, що змушує ваші гроші робити те, що ви хочете. — Дейв Ремзі",
    "Записуй витрати щодня — дисципліна перемагає інтуїцію.",
    "Плати спочатку собі: відкладайте 10–20% від кожного доходу.",
    "Сніжний ком: гасіть найменші борги першими, щоб набирати темп.",
    "Диверсифікуй інвестиції — не клади всі яйця в один кошик.",
    "Великих результатів досягає той, хто мислить довгою дистанцією.",
    "Купуй активи, а не статус. Статус згорає, активи працюють.",
    "Те, що не вимірюєш — тим не керуєш. Статистика = контроль.",
    "Найкращий час почати інвестувати був учора. Другий найкращий — сьогодні.",
    "Гроші люблять тишу. Приймай рішення раціонально, не імпульсивно."
]

# ====== STATES ======
(
    NAME, CURRENCY_SETUP,
    TYPE, CATEGORY, SUBCATEGORY, AMOUNT, COMMENT,
    STAT_MODE, STAT_YEAR, STAT_MONTH, STAT_DAY, STAT_ACTION,
    PROFILE_MENU, PROFILE_EDIT_NAME, PROFILE_EDIT_CURRENCY
) = range(15)

# ====== KEYBOARDS ======
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

def stat_mode_kb():
    return kb([["📅 За день", "📅 За місяць"], ["↩️ Назад"]])

def years_kb():
    y = datetime.now().year
    return kb([[str(y), str(y-1)], ["↩️ Назад"]])

def months_kb():
    rows, row = [], []
    for m in range(1, 13):
        row.append(MONTHS[m])
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append(["↩️ Назад"])
    return kb(rows)

def days_kb(year: int, month: int):
    ndays = calendar.monthrange(year, month)[1]
    rows, row = [], []
    for d in range(1, ndays+1):
        row.append(str(d))
        if len(row) == 7:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append(["↩️ Назад"])
    return kb(rows)

def stats_actions_kb():
    return kb([["📄 PDF", "🥧 Діаграма"], ["↩️ Назад"], ["🏠 Головне меню"]])

def profile_menu_kb():
    return kb([["✏️ Змінити ім’я", "💱 Змінити валюту"],
               ["📜 Увесь історичний PDF"],
               ["🏠 Головне меню"]])

# ====== HELPERS ======
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

def fetch_day(user_id, y, m, d):
    date_str = f"{y:04d}-{m:02d}-{d:02d}"
    cur.execute("""SELECT type, category, subcategory, amount, currency, comment
                   FROM transactions WHERE user_id=? AND date=?""", (user_id, date_str))
    return cur.fetchall(), date_str

def fetch_month(user_id, y, m):
    cur.execute("""SELECT type, category, subcategory, amount, currency, comment
                   FROM transactions
                   WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?""",
                (user_id, str(y), f"{m:02d}"))
    return cur.fetchall()

def build_stats_text(rows, title):
    if not rows:
        return f"{title}\n📭 Немає записів."
    sums = {"💸 Витрати": 0.0, "💰 Надходження": 0.0, "📈 Інвестиції": 0.0}
    lines = []
    for t, c, s, a, curx, com in rows:
        a = float(a or 0)
        if t not in sums:
            sums[t] = 0.0
        sums[t] += a
        lines.append(f"• {t} | {c}/{s or '-'} — {a:.2f} {curx} ({com or '-'})")
    total = "\n".join([f"{k}: {v:.2f}" for k, v in sums.items()])
    tip = random.choice(TIPS)
    return f"{title}\n\n" + "\n".join(lines) + f"\n\nПідсумок:\n{total}\n\n💡 {tip}"

def make_pdf(rows, title, filename):
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    if "Ukr" not in styles:
        styles.add(ParagraphStyle(name="Ukr", fontName="DejaVu", fontSize=12, leading=15))
    elements = [Paragraph(title, styles["Ukr"])]
    data = [["Тип", "Категорія", "Підкатегорія", "Сума", "Валюта", "Коментар"]]
    totals = defaultdict(float)
    for t, c, s, a, curx, com in rows:
        a = float(a or 0)
        totals[t] += a
        data.append([t, c, s or "-", f"{a:.2f}", curx, com or "-"])
    data.append(["", "", "", "", "", ""])
    for k in ["💸 Витрати", "💰 Надходження", "📈 Інвестиції"]:
        data.append([k, "", "", f"{totals[k]:.2f}", "", ""])
    table = Table(data, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements.append(table)
    doc.build(elements)

def make_pie_expenses(rows, title, path_png):
    sums_by_cat = defaultdict(float)
    for t, c, s, a, curx, com in rows:
        if t == "💸 Витрати":
            sums_by_cat[c] += float(a or 0)
    if not sums_by_cat:
        return False
    labels = list(sums_by_cat.keys())
    values = list(sums_by_cat.values())
    plt.figure()
    plt.pie(values, labels=labels, autopct="%1.1f%%")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(path_png)
    plt.close()
    return True

def profile_summary(user_id):
    cur.execute("SELECT name, currency, created_at FROM users WHERE user_id=?", (user_id,))
    u = cur.fetchone()
    if not u:
        return None, None
    name, currency, created = u
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN type='💸 Витрати' THEN amount ELSE 0 END), SUM(CASE WHEN type='💰 Надходження' THEN amount ELSE 0 END) FROM transactions WHERE user_id=?", (user_id,))
    cnt, exp_sum, inc_sum = cur.fetchone()
    exp_sum = exp_sum or 0
    inc_sum = inc_sum or 0
    text = (
        "📇 ОСОБИСТИЙ КАБІНЕТ\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Ім’я: {name}\n"
        f"💱 Валюта: {currency}\n"
        f"📅 Зареєстровано: {(created or '')[:10]}\n"
        f"🧾 Записів: {cnt}\n"
        f"💸 Усього витрат: {exp_sum:.2f} {currency}\n"
        f"💰 Усього надходжень: {inc_sum:.2f} {currency}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {random.choice(TIPS)}"
    )
    return text, currency

# ====== INTRO TEXT ======
INTRO_TEXT = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 ФІНАНСОВИЙ БОТ — ТВІЙ ОСОБИСТИЙ КАБІНЕТ\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Що вмію:\n"
    "• Записувати 💸 витрати, 💰 доходи, 📈 інвестиції\n"
    "• Показувати статистику за день або місяць (з деталями)\n"
    "• Будувати 🥧 діаграми витрат та генерувати 📄 PDF-звіти\n"
    "• Зберігати історію транзакцій і профіль (ім’я, валюта)\n\n"
    "Починай із додавання запису або відкрий «📊 Статистика». Готовий? 🙂\n"
)

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        await update.message.reply_text("👋 Привіт! Як до тебе звертатись?")
        return NAME
    u = get_user(user_id)
    await update.message.reply_text(f"👋 Привіт, {u[1]}!\n\n{INTRO_TEXT}", reply_markup=main_menu_kb())
    return TYPE

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи ім'я 🙂")
        return NAME
    context.user_data["name"] = name
    await update.message.reply_text("Оберіть валюту:", reply_markup=currencies_kb())
    return CURRENCY_SETUP

async def save_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    curx = update.message.text
    if curx not in CURRENCIES:
        await update.message.reply_text("Будь ласка, обери валюту з кнопок:", reply_markup=currencies_kb())
        return CURRENCY_SETUP
    create_or_update_user(update.effective_user.id, context.user_data["name"], curx)
    await update.message.reply_text(f"✅ Профіль створено!\n\n{INTRO_TEXT}", reply_markup=main_menu_kb())
    return TYPE

async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t not in TYPES:
        await update.message.reply_text("Будь ласка, користуйся кнопками нижче 👇", reply_markup=main_menu_kb())
        return TYPE
    if t == "📊 Статистика":
        await update.message.reply_text("Оберіть режим:", reply_markup=stat_mode_kb())
        return STAT_MODE
    if t == "👤 Мій профіль":
        txt, _ = profile_summary(update.effective_user.id)
        if txt:
            await update.message.reply_text(txt, reply_markup=profile_menu_kb())
            return PROFILE_MENU
        else:
            await update.message.reply_text("Профіль ще не створено. Напиши /start", reply_markup=main_menu_kb())
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
    if t is None or text not in CATEGORIES[t]:
        await update.message.reply_text("Обери категорію:", reply_markup=categories_kb(t or "💸 Витрати"))
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
    u = get_user(user_id)
    currency = u[2] if u else "грн"
    ud = context.user_data
    date_str = datetime.now().strftime("%Y-%m-%d")
    save_tx(user_id, ud["type"], ud["category"], ud.get("subcategory"), ud["amount"], currency, comment, date_str)
    await update.message.reply_text(
        f"✅ Записано: {ud['type']} → {ud['category']} → {ud.get('subcategory', '-')}\n"
        f"Сума: {ud['amount']} {currency}\nДата: {date_str}",
        reply_markup=main_menu_kb()
    )
    ud.clear()
    return TYPE

# ====== STATS ======
async def stat_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "↩️ Назад":
        await update.message.reply_text("Меню:", reply_markup=main_menu_kb())
        return TYPE
    if t not in ["📅 За день", "📅 За місяць"]:
        await update.message.reply_text("Оберіть режим:", reply_markup=stat_mode_kb())
        return STAT_MODE
    context.user_data["stat_mode"] = t
    await update.message.reply_text("Оберіть рік:", reply_markup=years_kb())
    return STAT_YEAR

async def stat_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "↩️ Назад":
        await update.message.reply_text("Оберіть режим:", reply_markup=stat_mode_kb())
        return STAT_MODE
    if not text.isdigit():
        await update.message.reply_text("Введи рік числом або обери кнопку:", reply_markup=years_kb())
        return STAT_YEAR
    context.user_data["year"] = int(text)
    await update.message.reply_text("Оберіть місяць:", reply_markup=months_kb())
    return STAT_MONTH

async def stat_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "↩️ Назад":
        await update.message.reply_text("Оберіть рік:", reply_markup=years_kb())
        return STAT_YEAR
    if text not in MONTHS_BY_NAME:
        await update.message.reply_text("Оберіть місяць з кнопок:", reply_markup=months_kb())
        return STAT_MONTH
    m = MONTHS_BY_NAME[text]
    context.user_data["month"] = m
    if context.user_data.get("stat_mode") == "📅 За день":
        y = context.user_data["year"]
        await update.message.reply_text("Оберіть день:", reply_markup=days_kb(y, m))
        return STAT_DAY
    user_id = update.effective_user.id
    rows = fetch_month(user_id, context.user_data["year"], m)
    title = f"📆 {MONTHS[m]} {context.user_data['year']}"
    context.user_data["last_report"] = ("month", rows, title)
    await update.message.reply_text(build_stats_text(rows, title), reply_markup=stats_actions_kb())
    return STAT_ACTION

async def stat_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "↩️ Назад":
        await update.message.reply_text("Оберіть місяць:", reply_markup=months_kb())
        return STAT_MONTH
    if not text.isdigit():
        await update.message.reply_text("Оберіть день:",
                                        reply_markup=days_kb(context.user_data["year"], context.user_data["month"]))
        return STAT_DAY
    d = int(text)
    y, m = context.user_data["year"], context.user_data["month"]
    rows, date_str = fetch_day(update.effective_user.id, y, m, d)
    title = f"📅 {d} {MONTHS[m]} {y}"
    context.user_data["last_report"] = ("day", rows, title)
    await update.message.reply_text(build_stats_text(rows, title), reply_markup=stats_actions_kb())
    return STAT_ACTION

async def stat_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "🏠 Головне меню":
        await update.message.reply_text("Меню:", reply_markup=main_menu_kb())
        return TYPE
    if text == "↩️ Назад":
        # повертаємось у вибір дня або місяця
        mode = context.user_data.get("stat_mode")
        if mode == "📅 За день":
            await update.message.reply_text("Оберіть день:",
                                            reply_markup=days_kb(context.user_data["year"], context.user_data["month"]))
            return STAT_DAY
        else:
            await update.message.reply_text("Оберіть місяць:", reply_markup=months_kb())
            return STAT_MONTH

    payload = context.user_data.get("last_report")
    if not payload:
        await update.message.reply_text("Спершу сформуй звіт.", reply_markup=main_menu_kb())
        return TYPE
    _, rows, title = payload

    if text == "📄 PDF":
        fname = "report.pdf"
        make_pdf(rows, title, fname)
        with open(fname, "rb") as f:
            await update.message.reply_document(document=InputFile(f, filename=fname), caption=title)
        return STAT_ACTION

    if text == "🥧 Діаграма":
        img = "pie.png"
        ok = make_pie_expenses(rows, f"Розподіл витрат — {title}", img)
        if not ok:
            await update.message.reply_text("Немає даних по витратах для діаграми.")
            return STAT_ACTION
        with open(img, "rb") as f:
            await update.message.reply_photo(photo=f, caption=f"Розподіл витрат — {title}")
        return STAT_ACTION

    # Якщо невідома команда — залишаємося тут
    return STAT_ACTION

# ====== PROFILE ======
async def profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "🏠 Головне меню":
        await update.message.reply_text("Меню:", reply_markup=main_menu_kb())
        return TYPE
    if t == "✏️ Змінити ім’я":
        await update.message.reply_text("Введи нове ім’я:")
        return PROFILE_EDIT_NAME
    if t == "💱 Змінити валюту":
        await update.message.reply_text("Оберіть нову валюту:", reply_markup=currencies_kb())
        return PROFILE_EDIT_CURRENCY
    if t == "📜 Увесь історичний PDF":
        user_id = update.effective_user.id
        cur.execute("""SELECT type, category, subcategory, amount, currency, comment
                       FROM transactions WHERE user_id=? ORDER BY date ASC, id ASC""", (user_id,))
        rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("Поки що немає жодного запису.")
            return PROFILE_MENU
        title = "Повний звіт за всі роки"
        fname = "all_history.pdf"
        make_pdf(rows, title, fname)
        with open(fname, "rb") as f:
            await update.message.reply_document(InputFile(f, filename=fname), caption=title)
        return PROFILE_MENU
    # Невідома команда — знову покажемо профіль
    txt, _ = profile_summary(update.effective_user.id)
    await update.message.reply_text(txt or "Профіль не знайдено", reply_markup=profile_menu_kb())
    return PROFILE_MENU

async def profile_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи коректне ім’я 🙂")
        return PROFILE_EDIT_NAME
    cur.execute("UPDATE users SET name=? WHERE user_id=?", (name, update.effective_user.id))
    conn.commit()
    txt, _ = profile_summary(update.effective_user.id)
    await update.message.reply_text("✅ Ім’я оновлено.\n\n" + (txt or ""), reply_markup=profile_menu_kb())
    return PROFILE_MENU

async def profile_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    curx = update.message.text
    if curx not in CURRENCIES:
        await update.message.reply_text("Будь ласка, обери валюту з кнопок:", reply_markup=currencies_kb())
        return PROFILE_EDIT_CURRENCY
    cur.execute("UPDATE users SET currency=? WHERE user_id=?", (curx, update.effective_user.id))
    conn.commit()
    txt, _ = profile_summary(update.effective_user.id)
    await update.message.reply_text("✅ Валюту оновлено.\n\n" + (txt or ""), reply_markup=profile_menu_kb())
    return PROFILE_MENU

# ====== APP ======
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

            STAT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, stat_mode)],
            STAT_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, stat_year)],
            STAT_MONTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, stat_month)],
            STAT_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, stat_day)],
            STAT_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, stat_action)],

            PROFILE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_menu)],
            PROFILE_EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_name)],
            PROFILE_EDIT_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_currency)],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
