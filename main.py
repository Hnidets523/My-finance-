import os
import sqlite3
import calendar
import random
import requests
from collections import defaultdict
from datetime import datetime

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    MessageHandler, CallbackQueryHandler, ContextTypes, filters
)

# ==== PDF ====
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==== Charts ====
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено у змінних середовища (Railway → Variables).")

DB_PATH = "finance.db"
pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

# ===================== DB =====================
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

# ===================== CONSTANTS =====================
MONTHS = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
    5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
    9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"
}
MONTHS_BY_NAME = {v: k for k, v in MONTHS.items()}

TYPES = ["💸 Витрати", "💰 Надходження", "📈 Інвестиції"]
CURRENCIES = ["грн", "$"]

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

# емодзі + кольори для головних категорій (pie chart)
CATEGORY_EMOJI = {
    "Харчування": "🍔",
    "Одяг та взуття": "👕",
    "Оренда/житло": "🏠",
    "Господарчі товари": "🧴",
    "Дорога/подорожі": "🚌",
    "Онлайн підписки": "📲",
    "Поповнення мобільного": "📶",
    "Розваги": "🎉",
    "Vodafone": "📡",
    "Крипта": "🪙",
    "Зарядні пристрої": "🔌",
    "Hub station": "🖥️",
    "Акаунти": "👤",
    "Купівля $": "💵",
    "Зарплата": "💼",
    "Переказ": "🔁",
    "Інше": "➕",
}
CATEGORY_COLORS = {
    "Харчування": "#FF9800",
    "Одяг та взуття": "#3F51B5",
    "Оренда/житло": "#009688",
    "Господарчі товари": "#795548",
    "Дорога/подорожі": "#4CAF50",
    "Онлайн підписки": "#9C27B0",
    "Поповнення мобільного": "#607D8B",
    "Розваги": "#673AB7",
    "Vodafone": "#E91E63",
    # інвест/доходи на всяк:
    "Крипта": "#FBC02D",
    "Зарядні пристрої": "#8BC34A",
    "Hub station": "#00BCD4",
    "Акаунти": "#CDDC39",
    "Купівля $": "#FF5722",
    "Зарплата": "#2196F3",
    "Переказ": "#00ACC1",
    "Інше": "#9E9E9E",
}

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

# ===================== QUIZ (20 питань, рандом) =====================
QUIZ_QUESTIONS_BASE = [
    {
        "q": "Який рекомендований мінімальний розмір фінансової подушки безпеки?",
        "opts": ["1 місяць витрат", "3–6 місяців витрат", "12 місяців витрат", "2 тижні витрат"],
        "ans": 1
    },
    {
        "q": "Що таке правило «Плати спочатку собі»?",
        "opts": ["Плати борги перш ніж витрачати", "Купи потрібне — решта в заощадження", "Спершу відкладай, а потім витрачай", "Спершу оплати підписки"],
        "ans": 2
    },
    {
        "q": "Яке твердження про диверсифікацію вірне?",
        "opts": ["Інвестувати в один актив — безпечніше", "Розподіл інвестицій зменшує ризик", "Диверсифікація знижує прибуток до нуля", "Це про економію, а не інвестиції"],
        "ans": 1
    },
    {
        "q": "Що таке складний процент?",
        "opts": ["Відсоток лише на початкову суму", "Відсоток на відсоток", "Плата банку за обслуговування", "Разова комісія брокера"],
        "ans": 1
    },
    {
        "q": "Який відсоток доходу класти в заощадження — базова порада?",
        "opts": ["1–5%", "10–20%", "30–40%", "50%+"],
        "ans": 1
    },
    {
        "q": "Що робити перед інвестиціями?",
        "opts": ["Оформити кредитну картку", "Скласти подушку безпеки", "Купити нерухомість", "Нічого не потрібно"],
        "ans": 1
    },
    {
        "q": "Що таке бюджет 50/30/20?",
        "opts": ["50% інвестиції, 30% борги, 20% витрати", "50% потреби, 30% бажання, 20% заощадження", "50% бажання, 30% потреби, 20% борги", "50% витрати, 50% інвестиції"],
        "ans": 1
    },
    {
        "q": "Який ризик у “гарячих” криптопроєктах?",
        "opts": ["Гарантований прибуток", "Нульовий ризик", "Висока волатильність і ризик втрат", "Державні гарантії"],
        "ans": 2
    },
    {
        "q": "Що ефективніше проти імпульсивних покупок?",
        "opts": ["Купувати вночі", "Правило 24 годин паузи", "Оплата готівкою", "Позика в друга"],
        "ans": 1
    },
    {
        "q": "Який інструмент найкраще фіксує реальні витрати щодня?",
        "opts": ["Пам’ять", "Щомісячний звіт", "Записи у боті/додатку", "Раз на пів року"],
        "ans": 2
    },
    {
        "q": "Що зменшує боргове навантаження швидше?",
        "opts": ["Платити мінімалки", "Сніжний ком: з найменших боргів", "Взяти новий кредит", "Ігнорувати борги"],
        "ans": 1
    },
    {
        "q": "Що означає «жити нижче своїх можливостей»?",
        "opts": ["Витрачати більше ніж заробляєш", "Завжди купувати найдешевше", "Витрачати менше доходу та інвестувати різницю", "Жити без комфорту"],
        "ans": 2
    },
    {
        "q": "Який головний ризик збереження грошей лише у готівці?",
        "opts": ["Зручність", "Інфляція з’їдає купівельну спроможність", "Високий відсоток", "Державні гарантії"],
        "ans": 1
    },
    {
        "q": "Що важливіше при довгостроковому інвестуванні?",
        "opts": ["Час на ринку", "Таймінг ринку", "Ідеальна точка входу", "Щоденна купівля-продаж"],
        "ans": 0
    },
    {
        "q": "Що з цього — актив?",
        "opts": ["Автомобіль, що щомісяця потребує витрат", "Кафе-кава кожного дня", "Акції/фонди, що генерують дохід", "Підписка на серіали"],
        "ans": 2
    },
    {
        "q": "Оптимальна кількість валют у заощадженнях?",
        "opts": ["Лише одна", "2–3 валюти", "10 валют", "Не має значення"],
        "ans": 1
    },
    {
        "q": "Що таке «резерви на непередбачувані витрати»?",
        "opts": ["Витрати на розваги", "Гроші на бажання", "Фонд для поломок/лікування/штрафів", "Податкова пільга"],
        "ans": 2
    },
    {
        "q": "Чому автоматичні перекази в заощадження — це добре?",
        "opts": ["Бо незручно", "Зменшує дисципліну", "Знімає зусилля: стабільність і звичка", "Не має сенсу"],
        "ans": 2
    },
    {
        "q": "Навіщо відстежувати підписки?",
        "opts": ["Щоб не пропустити серіал", "Щоб не переплачувати щомісяця непомітно", "Щоб заробляти на підписках", "Щоб платити штрафи"],
        "ans": 1
    },
    {
        "q": "Коли починати інвестувати?",
        "opts": ["Коли буде багато грошей", "Одразу після створення подушки", "Ніколи", "Лише в кризу"],
        "ans": 1
    },
]

# ===================== STATES =====================
(
    ASK_NAME,  # онбординг: ім’я
    MAIN,      # головне меню/стан callback
    AMOUNT,    # ввід суми
    COMMENT,   # ввід коментаря
    STAT_YEAR_SELECT,
    STAT_MONTH_SELECT,
    STAT_DAY_SELECT,
    PROFILE_EDIT_NAME,
    QUIZ_ACTIVE,  # гра активна — кліки A/B/C/D
) = range(9)

# ===================== RATES (NBU + CoinGecko) =====================
async def refresh_rates_job(context: ContextTypes.DEFAULT_TYPE):
    # NBU
    try:
        r = requests.get("https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json", timeout=10)
        data = r.json()
        usd = next((x for x in data if str(x.get("r030")) == "840"), None)
        eur = next((x for x in data if str(x.get("r030")) == "978"), None)
        usd_uah = float(usd["rate"]) if usd else None
        eur_uah = float(eur["rate"]) if eur else None
    except Exception:
        usd_uah = eur_uah = None

    # CoinGecko
    try:
        c = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
            timeout=10
        ).json()
        btc_usd = float(c.get("bitcoin", {}).get("usd", 0) or 0)
        eth_usd = float(c.get("ethereum", {}).get("usd", 0) or 0)
    except Exception:
        btc_usd = eth_usd = None

    rates = context.application.bot_data.get("rates", {})
    if usd_uah: rates["usd_uah"] = usd_uah
    if eur_uah: rates["eur_uah"] = eur_uah
    if btc_usd: rates["btc_usd"] = btc_usd
    if eth_usd: rates["eth_usd"] = eth_usd
    context.application.bot_data["rates"] = rates
    context.application.bot_data["rates_updated"] = datetime.utcnow().isoformat()

def fmtn(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")

def fmtd(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")

def rates_block(bot_data: dict) -> str:
    rates = bot_data.get("rates", {})
    usd = rates.get("usd_uah")
    eur = rates.get("eur_uah")
    btc = rates.get("btc_usd")
    eth = rates.get("eth_usd")
    if not (usd and eur and btc and eth):
        return "📡 Котирування недоступні зараз. Спробуй пізніше."
    btc_uah = btc * usd
    eth_uah = eth * usd
    return (
        "📈 КОТИРУВАННЯ (реальний час)\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Долар США: 1 USD = {fmtn(usd)} грн\n"
        f"💶 Євро: 1 EUR = {fmtn(eur)} грн\n"
        f"₿ Біткоїн: ${fmtd(btc)} ≈ {fmtn(btc_uah)} грн\n"
        f"Ξ Ефір: ${fmtd(eth)} ≈ {fmtn(eth_uah)} грн"
    )

# ===================== HELPERS (DB) =====================
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
    ds = f"{y:04d}-{m:02d}-{d:02d}"
    cur.execute("""SELECT type, category, subcategory, amount, currency, comment
                   FROM transactions WHERE user_id=? AND date=?""", (user_id, ds))
    return cur.fetchall(), ds

def fetch_month(user_id, y, m):
    cur.execute("""SELECT type, category, subcategory, amount, currency, comment
                   FROM transactions
                   WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?""",
                (user_id, str(y), f"{m:02d}"))
    return cur.fetchall()

# ===================== HELPERS (TEXT/PDF/CHARTS) =====================
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
        lines.append(f"• {t} | {CATEGORY_EMOJI.get(c, '')} {c}/{s or '-'} — {a:.2f} {curx} ({com or '-'})")
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
        data.append([t, f"{CATEGORY_EMOJI.get(c,'')} {c}", s or "-", f"{a:.2f}", curx, com or "-"])
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
    labels = [f"{CATEGORY_EMOJI.get(k,'')} {k}" for k in sums_by_cat.keys()]
    values = list(sums_by_cat.values())
    colors_list = [CATEGORY_COLORS.get(k, "#999999") for k in sums_by_cat.keys()]
    plt.figure()
    plt.pie(values, labels=labels, autopct="%1.1f%%", colors=colors_list)
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
    cur.execute("""SELECT COUNT(*),
                          SUM(CASE WHEN type='💸 Витрати' THEN amount ELSE 0 END),
                          SUM(CASE WHEN type='💰 Надходження' THEN amount ELSE 0 END)
                   FROM transactions WHERE user_id=?""", (user_id,))
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

# ===================== UI (Inline Keyboards) =====================
def ikb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for (t, d) in row] for row in rows])

def main_menu_ikb():
    return ikb([
        [("💸 Витрати", "type:exp"), ("💰 Надходження", "type:inc")],
        [("📈 Інвестиції", "type:inv"), ("📊 Статистика", "stats:open")],
        [("🎮 Гра", "quiz:start"), ("👤 Мій профіль", "profile:open")]
    ])

def categories_ikb(tname):
    cats = list(CATEGORIES[tname].keys())
    rows, row = [], []
    for i, c in enumerate(cats):
        title = f"{CATEGORY_EMOJI.get(c,'')} {c}"
        row.append((title, f"cat:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("↩️ Назад", "back:main"), ("🏠 Головне меню", "main:open")])
    return ikb(rows)

def subcategories_ikb(tname, cat_name):
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
    rows.append([("↩️ Назад", "back:cats"), ("🏠 Головне меню", "main:open")])
    return ikb(rows)

def stat_mode_ikb():
    return ikb([
        [("📅 За день", "stats:mode:day"), ("📅 За місяць", "stats:mode:mon")],
        [("↩️ Назад", "back:main"), ("🏠 Головне меню", "main:open")]
    ])

def years_ikb():
    y = datetime.now().year
    return ikb([
        [(str(y), f"stats:year:{y}"), (str(y-1), f"stats:year:{y-1}")],
        [("↩️ Назад", "back:statsmode"), ("🏠 Головне меню", "main:open")]
    ])

def months_ikb():
    rows, row = [], []
    for m in range(1, 13):
        row.append((MONTHS[m], f"stats:month:{m:02d}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("↩️ Назад", "back:year"), ("🏠 Головне меню", "main:open")])
    return ikb(rows)

def days_ikb(year: int, month: int):
    nd = calendar.monthrange(year, month)[1]
    rows, row = [], []
    for d in range(1, nd+1):
        row.append((str(d), f"stats:day:{d:02d}"))
        if len(row) == 7:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("↩️ Назад", "back:month"), ("🏠 Головне меню", "main:open")])
    return ikb(rows)

def stats_actions_ikb():
    return ikb([
        [("📄 PDF", "stats:pdf"), ("🥧 Діаграма", "stats:pie")],
        [("↩️ Назад", "back:statselect"), ("🏠 Головне меню", "main:open")]
    ])

def profile_menu_ikb():
    return ikb([
        [("✏️ Змінити ім’я", "profile:editname"), ("💱 Змінити валюту", "profile:editcur")],
        [("📜 Увесь історичний PDF", "profile:allpdf")],
        [("↩️ Назад", "back:main"), ("🏠 Головне меню", "main:open")]
    ])

def currency_pick_ikb(prefix: str):
    return ikb([
        [("грн", f"{prefix}:setcur:грн"), ("$", f"{prefix}:setcur:$")],
        [("↩️ Назад", "back:main"), ("🏠 Головне меню", "main:open")]
    ])

def quiz_answer_ikb(q_idx: int):
    # A/B/C/D з callback
    return ikb([
        [("A", f"quiz:ans:{q_idx}:0"), ("B", f"quiz:ans:{q_idx}:1")],
        [("C", f"quiz:ans:{q_idx}:2"), ("D", f"quiz:ans:{q_idx}:3")],
        [("🏠 Головне меню", "main:open")]
    ])

# ===================== INTRO =====================
INTRO_TEXT = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 ФІНАНСОВИЙ БОТ — ТВІЙ ОСОБИСТИЙ КАБІНЕТ\n"
    "━━━━━━━━━━━━━━━━━━━\n\n"
    "Що вмію:\n"
    "• Записувати 💸 витрати, 💰 доходи, 📈 інвестиції\n"
    "• Показувати статистику за день або місяць (з деталями)\n"
    "• Будувати 🥧 діаграми витрат та генерувати 📄 PDF-звіти\n"
    "• Зберігати історію транзакцій і профіль (ім’я, валюта)\n"
    "• Показувати реальні курси валют/крипти (НБУ + CoinGecko)\n\n"
    "Починай із додавання запису або відкрий «📊 Статистика». Готовий? 🙂\n"
)

# ===================== MAIN MENU SENDER =====================
async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, greeting: str | None = None):
    text = (greeting or "🏠 Головне меню") + "\n\n" + rates_block(context.application.bot_data)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_ikb())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_ikb())

# ===================== START / ONBOARD =====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("👋 Привіт! Як до тебе звертатись?")
        return ASK_NAME
    await send_main_menu(update, context, f"👋 Привіт, {u[1]}!\n\n{INTRO_TEXT}")
    return MAIN

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи ім'я 🙂")
        return ASK_NAME
    context.user_data["pending_name"] = name
    await update.message.reply_text("Оберіть валюту:", reply_markup=currency_pick_ikb("onb"))
    return MAIN  # чекаємо callback onb:setcur:*

# ===================== CALLBACK ROUTER =====================
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()
    uid = update.effective_user.id

    # -------- ГОЛОВНЕ МЕНЮ --------
    if data == "main:open":
        await send_main_menu(update, context, "🏠 Повернувся в головне меню")
        return MAIN

    # -------- ОНБОРДИНГ: валюта --------
    if data.startswith("onb:setcur:"):
        curx = data.split(":", 2)[2]
        name = context.user_data.get("pending_name", "Користувач")
        create_or_update_user(uid, name, curx)
        await send_main_menu(update, context, f"✅ Профіль створено!\n\n{INTRO_TEXT}")
        context.user_data.pop("pending_name", None)
        return MAIN

    # -------- ВИБІР ТИПУ (EXP/INC/INV) --------
    if data.startswith("type:"):
        code = data.split(":")[1]
        tname = {"exp": "💸 Витрати", "inc": "💰 Надходження", "inv": "📈 Інвестиції"}[code]
        context.user_data["tname"] = tname
        context.user_data["cat_list"] = list(CATEGORIES[tname].keys())
        await q.edit_message_text(f"Обери категорію ({tname}):", reply_markup=categories_ikb(tname))
        return MAIN

    # -------- КАТЕГОРІЇ --------
    if data == "back:main":
        await send_main_menu(update, context, "↩️ Повернувся на головне меню")
        return MAIN

    if data.startswith("cat:"):
        idx = int(data.split(":")[1])
        cats = context.user_data.get("cat_list", [])
        if idx < 0 or idx >= len(cats):
            await q.edit_message_text("Обери категорію:", reply_markup=categories_ikb(context.user_data.get("tname", TYPES[0])))
            return MAIN
        cat_name = cats[idx]
        context.user_data["cat_name"] = cat_name
        tname = context.user_data["tname"]
        await q.edit_message_text(f"Обери підкатегорію ({CATEGORY_EMOJI.get(cat_name,'')} {cat_name}):", reply_markup=subcategories_ikb(tname, cat_name))
        return MAIN

    # -------- ПІДКАТЕГОРІЇ --------
    if data == "back:cats":
        tname = context.user_data.get("tname", TYPES[0])
        await q.edit_message_text(f"Обери категорію ({tname}):", reply_markup=categories_ikb(tname))
        return MAIN

    if data.startswith("sub:"):
        val = data.split(":")[1]
        tname = context.user_data.get("tname", TYPES[0])
        cat_name = context.user_data.get("cat_name")
        if val == "none":
            context.user_data["sub_name"] = None
        else:
            subs = CATEGORIES[tname][cat_name] or []
            idx = int(val)
            if idx < 0 or idx >= len(subs):
                await q.edit_message_text("Обери підкатегорію:", reply_markup=subcategories_ikb(tname, cat_name))
                return MAIN
            context.user_data["sub_name"] = subs[idx]
        # просимо суму
        await q.edit_message_text(
            "Введи суму (наприклад 123.45):",
            reply_markup=ikb([[("↩️ Назад", "back:cats"), ("🏠 Головне меню", "main:open")]])
        )
        return AMOUNT

    # -------- СТАТИСТИКА --------
    if data == "stats:open":
        await q.edit_message_text("Оберіть режим:", reply_markup=stat_mode_ikb())
        return MAIN

    if data == "back:statsmode":
        await q.edit_message_text("Оберіть режим:", reply_markup=stat_mode_ikb())
        return MAIN

    if data.startswith("stats:mode:"):
        mode = data.split(":")[2]  # day | mon
        context.user_data["stat_mode"] = mode
        await q.edit_message_text("Оберіть рік:", reply_markup=years_ikb())
        return STAT_YEAR_SELECT

    if data == "back:year":
        await q.edit_message_text("Оберіть рік:", reply_markup=years_ikb())
        return STAT_YEAR_SELECT

    if data.startswith("stats:year:"):
        y = int(data.split(":")[2])
        context.user_data["year"] = y
        await q.edit_message_text("Оберіть місяць:", reply_markup=months_ikb())
        return STAT_MONTH_SELECT

    if data == "back:month":
        await q.edit_message_text("Оберіть місяць:", reply_markup=months_ikb())
        return STAT_MONTH_SELECT

    if data.startswith("stats:month:"):
        m = int(data.split(":")[2])
        context.user_data["month"] = m
        if context.user_data.get("stat_mode") == "day":
            y = context.user_data["year"]
            await q.edit_message_text("Оберіть день:", reply_markup=days_ikb(y, m))
            return STAT_DAY_SELECT
        # за місяць
        rows = fetch_month(uid, context.user_data["year"], m)
        title = f"📆 {MONTHS[m]} {context.user_data['year']}"
        context.user_data["last_report"] = ("month", rows, title)
        await q.edit_message_text(build_stats_text(rows, title), reply_markup=stats_actions_ikb())
        return MAIN

    if data == "back:statselect":
        mode = context.user_data.get("stat_mode")
        if mode == "day":
            y = context.user_data.get("year", datetime.now().year)
            m = context.user_data.get("month", datetime.now().month)
            await q.edit_message_text("Оберіть день:", reply_markup=days_ikb(y, m))
            return STAT_DAY_SELECT
        else:
            await q.edit_message_text("Оберіть місяць:", reply_markup=months_ikb())
            return STAT_MONTH_SELECT

    if data.startswith("stats:day:"):
        d = int(data.split(":")[2])
        y, m = context.user_data["year"], context.user_data["month"]
        rows, _ = fetch_day(uid, y, m, d)
        title = f"📅 {d} {MONTHS[m]} {y}"
        context.user_data["last_report"] = ("day", rows, title)
        await q.edit_message_text(build_stats_text(rows, title), reply_markup=stats_actions_ikb())
        return MAIN

    if data == "stats:pdf":
        payload = context.user_data.get("last_report")
        if not payload:
            await q.answer("Спочатку сформуйте звіт.", show_alert=True)
            return MAIN
        _, rows, title = payload
        fname = "report.pdf"
        make_pdf(rows, title, fname)
        with open(fname, "rb") as f:
            await q.message.reply_document(document=InputFile(f, filename=fname), caption=title)
        await q.message.reply_text("Що далі?", reply_markup=stats_actions_ikb())
        return MAIN

    if data == "stats:pie":
        payload = context.user_data.get("last_report")
        if not payload:
            await q.answer("Спочатку сформуйте звіт.", show_alert=True)
            return MAIN
        _, rows, title = payload
        img = "pie.png"
        ok = make_pie_expenses(rows, f"Розподіл витрат — {title}", img)
        if not ok:
            await q.answer("Немає даних по витратах для діаграми.", show_alert=True)
            return MAIN
        with open(img, "rb") as f:
            await q.message.reply_photo(photo=f, caption=f"Розподіл витрат — {title}")
        await q.message.reply_text("Що далі?", reply_markup=stats_actions_ikb())
        return MAIN

    # -------- ПРОФІЛЬ --------
    if data == "profile:open":
        txt, _ = profile_summary(uid)
        await q.edit_message_text(txt or "Профіль не знайдено", reply_markup=profile_menu_ikb())
        return MAIN

    if data == "profile:editname":
        await q.edit_message_text("Введи нове ім’я:", reply_markup=ikb([[("↩️ Назад", "back:main"), ("🏠 Головне меню", "main:open")]]))
        return PROFILE_EDIT_NAME

    if data == "profile:editcur":
        await q.edit_message_text("Оберіть валюту:", reply_markup=currency_pick_ikb("prof"))
        return MAIN

    if data.startswith("prof:setcur:"):
        curx = data.split(":", 2)[2]
        cur.execute("UPDATE users SET currency=? WHERE user_id=?", (curx, uid))
        conn.commit()
        txt, _ = profile_summary(uid)
        await q.edit_message_text("✅ Валюту оновлено.\n\n" + (txt or ""), reply_markup=profile_menu_ikb())
        return MAIN

    if data == "profile:allpdf":
        cur.execute("""SELECT type, category, subcategory, amount, currency, comment
                       FROM transactions WHERE user_id=? ORDER BY date ASC, id ASC""", (uid,))
        rows = cur.fetchall()
        if not rows:
            await q.answer("Поки що немає жодного запису.", show_alert=True)
            return MAIN
        title = "Повний звіт за всі роки"
        fname = "all_history.pdf"
        make_pdf(rows, title, fname)
        with open(fname, "rb") as f:
            await q.message.reply_document(InputFile(f, filename=fname), caption=title)
        await q.message.reply_text("Готово. Обери наступну дію:", reply_markup=profile_menu_ikb())
        return MAIN

    # -------- ГРА --------
    if data == "quiz:start":
        # Пояснення гри
        explain = (
            "🎮 *Фінансова грамотність — міні-тест*\n"
            "──────────────────────\n"
            "• 20 коротких запитань з варіантами відповідей (A/B/C/D)\n"
            "• Мета — перевірити себе без стресу\n"
            "• В кінці — підсумок, бали і розбір помилок\n\n"
            "Готовий? Натисни будь-яку відповідь, коли з’явиться перше питання 👇"
        )
        # сформуємо рандомні 20
        q_indexes = list(range(len(QUIZ_QUESTIONS_BASE)))
        random.shuffle(q_indexes)
        q_indexes = q_indexes[:20]
        context.user_data["quiz_idx_list"] = q_indexes
        context.user_data["quiz_pos"] = 0
        context.user_data["quiz_score"] = 0
        context.user_data["quiz_mistakes"] = []  # списки (qtxt, chosen_letter, correct_letter)
        # показати перше питання
        await q.edit_message_text(explain, parse_mode="Markdown")
        return await quiz_ask_next(update, context)

    if data.startswith("quiz:ans:"):
        parts = data.split(":")
        qidx = int(parts[2])   # позиція у поточній грі (0..19)
        choice = int(parts[3]) # 0..3

        pos = context.user_data.get("quiz_pos", 0)
        # захист: якщо натисли стару кнопку — ігноруємо
        if qidx != pos:
            await q.answer("Відповідь уже прийнята, рухаємось далі…")
            return QUIZ_ACTIVE

        # отримуємо поточне питання
        idx_list = context.user_data.get("quiz_idx_list", [])
        base_idx = idx_list[pos]
        item = QUIZ_QUESTIONS_BASE[base_idx]

        correct = item["ans"]
        letters = ["A", "B", "C", "D"]
        if choice == correct:
            context.user_data["quiz_score"] = context.user_data.get("quiz_score", 0) + 1
            await q.answer("✅ Правильно!")
        else:
            context.user_data["quiz_mistakes"].append(
                (item["q"], letters[choice], letters[correct], item["opts"][correct])
            )
            await q.answer("❌ Неправильно")

        # рухаємось далі
        context.user_data["quiz_pos"] = pos + 1
        return await quiz_ask_next(update, context)

    # -------- РЕЗЕРВ --------
    await q.answer("Невідома дія.", show_alert=True)
    return MAIN

async def quiz_ask_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати наступне питання або фінальний результат."""
    qobj = update.callback_query
    pos = context.user_data.get("quiz_pos", 0)
    idx_list = context.user_data.get("quiz_idx_list", [])
    if pos >= len(idx_list):
        # фінал
        score = context.user_data.get("quiz_score", 0)
        mistakes = context.user_data.get("quiz_mistakes", [])
        total = len(idx_list)
        # формуємо розбір
        lines = [f"🎯 *Результат*: {score}/{total} правильних\n"]
        if mistakes:
            lines.append("🧾 Де ти помилився:")
            for (qt, ch, corr, corr_text) in mistakes:
                lines.append(f"• {qt}\n   Твоя відповідь: {ch}\n   Правильна: {corr} — {corr_text}")
        else:
            lines.append("Ідеально! Без жодної помилки 🔥")
        # додамо цитату
        lines.append("\n💡 " + random.choice(TIPS))
        text = "\n".join(lines)
        await qobj.edit_message_text(text, parse_mode="Markdown", reply_markup=ikb([[("🏠 Головне меню", "main:open")]]))
        # почистимо стейт гри
        context.user_data.pop("quiz_idx_list", None)
        context.user_data.pop("quiz_pos", None)
        context.user_data.pop("quiz_score", None)
        context.user_data.pop("quiz_mistakes", None)
        return MAIN

    # виводимо питання pos
    base_idx = idx_list[pos]
    item = QUIZ_QUESTIONS_BASE[base_idx]
    q_text = f"❓ *Питання {pos+1}/{len(idx_list)}*\n{item['q']}\n\n" + \
             f"A) {item['opts'][0]}\nB) {item['opts'][1]}\nC) {item['opts'][2]}\nD) {item['opts'][3]}"
    await qobj.message.reply_text(q_text, parse_mode="Markdown", reply_markup=quiz_answer_ikb(pos))
    return QUIZ_ACTIVE

# ===================== TEXT INPUT HANDLERS =====================
async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").replace(",", ".").strip()
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(
            "Сума має бути числом. Спробуй ще раз:",
            reply_markup=ikb([[("↩️ Назад", "back:cats"), ("🏠 Головне меню", "main:open")]])
        )
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text(
        "Додай коментар або '-' якщо без:",
        reply_markup=ikb([[("↩️ Назад", "back:cats"), ("🏠 Головне меню", "main:open")]])
    )
    return COMMENT

async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    if comment == "-":
        comment = None
    uid = update.effective_user.id
    u = get_user(uid)
    currency = u[2] if u else "грн"
    tname = context.user_data.get("tname")
    cat = context.user_data.get("cat_name")
    sub = context.user_data.get("sub_name")
    amount = context.user_data.get("amount")
    if not all([tname, cat]) or amount is None:
        await update.message.reply_text("Щось пішло не так. Повертаю у меню.", reply_markup=main_menu_ikb())
        context.user_data.clear()
        return MAIN
    date_str = datetime.now().strftime("%Y-%m-%d")
    save_tx(uid, tname, cat, sub, amount, currency, comment, date_str)
    context.user_data.clear()
    await send_main_menu(update, context,
        f"✅ Записано: {tname} → {CATEGORY_EMOJI.get(cat,'')} {cat} → {sub or '-'}\n"
        f"Сума: {amount:.2f} {currency}\nДата: {date_str}"
    )
    return MAIN

async def handle_profile_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введи коректне ім’я 🙂",
                                        reply_markup=ikb([[("↩️ Назад", "back:main"), ("🏠 Головне меню", "main:open")]]))
        return PROFILE_EDIT_NAME
    cur.execute("UPDATE users SET name=? WHERE user_id=?", (name, update.effective_user.id))
    conn.commit()
    txt, _ = profile_summary(update.effective_user.id)
    await update.message.reply_text("✅ Ім’я оновлено.\n\n" + (txt or ""), reply_markup=profile_menu_ikb())
    return MAIN

# ===================== APP =====================
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    # JobQueue: автооновлення курсів щохвилини
    app.job_queue.run_repeating(refresh_rates_job, interval=60, first=0)

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name),
                       CallbackQueryHandler(on_cb)],

            MAIN: [CallbackQueryHandler(on_cb)],

            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount),
                     CallbackQueryHandler(on_cb)],

            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comment),
                      CallbackQueryHandler(on_cb)],

            STAT_YEAR_SELECT: [CallbackQueryHandler(on_cb)],
            STAT_MONTH_SELECT: [CallbackQueryHandler(on_cb)],
            STAT_DAY_SELECT: [CallbackQueryHandler(on_cb)],

            PROFILE_EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_edit_name),
                                CallbackQueryHandler(on_cb)],

            QUIZ_ACTIVE: [CallbackQueryHandler(on_cb)]
        },
        fallbacks=[CallbackQueryHandler(on_cb)],
        allow_reentry=True
    )

    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
