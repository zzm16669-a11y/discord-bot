"""
bank.py — نظام البنك (وحدة داخل بوت الكنترول bot.py)
====================================================
كل شي بالأزرار: اكتب "بنك" في روم البنك وتطلع لك لوحة الأزرار (حساب، إيداع/سحب/حوالة/فائدة، الذهب،
الوظائف والعمل، يومي بستريك، جريمة، سرقة، المتجر، الأغنياء، توب حرامية، استثمار).
واكتب "بنك @عضو" تشوف حساب أي عضو.

الربط داخل bot.py (نفس طريقة tickets / protection / ajr):
    import bank
    bank.setup_bank(bot)

ملاحظات:
  - ملف البيانات: bank.json (الحسابات القديمة تشتغل، والحقول الجديدة تنضاف لحالها).
  - الوحدة ما تسجل أي events (on_message / on_ready / ...) عشان ما تتعارض مع bot.py.
    اللي يحتاجه البنك من bot.py شيئين بس:
      1) bank.try_dispatch_bank_admin(message)  ← كلمة "بنك" (لوحة الأزرار) + "بنك @عضو" + أوامر بنك_اضافة / بنك_خصم
      2) bank.BankChannelRequired               ← رسالة "أوامر البنك تشتغل بس في روم البنك"
  - أوامر الإدارة (بنك_اضافة / بنك_خصم):
      * ما عنده صلاحية ← رياكشن ❌ بدون رد
      * نجح الأمر       ← رياكشن ✅
      * كتبه غلط        ← رد "استخدم الأمر بطريقة صحيحة" مع مثال
  - bank.get_bank_balance(guild_id, user_id) ← يستخدمها أمر p بالبوت الأساسي (بطاقة البروفايل).
  - ردود البنك صور (Pillow): الخلفيات من مجلد assets (أو bank_images أو bank، جنب bank.py أو جنب البوت)
    والخط من مجلد fonts (أي ملف Tajawal .ttf). الامتداد png أو jpg أو jpeg أو webp وحالة الأحرف ما تفرق:
      assets/account.png  ← حسابي (+ بنك @عضو)
      assets/receipt.png  ← إيداع / سحب / حوالة / فائدة
      assets/market.png   ← سوق الذهب
      assets/trade.png    ← شراء وبيع الذهب
      assets/result.png   ← عمل / سرقة / جريمة / يومي / استقالة / توظيف / شراء وبيع الأسهم
      assets/leaderboard.png ← الأغنياء / توب حرامية / الوظائف / سوق الأسهم / محفظتي
      fonts/Tajawal-Regular.ttf و fonts/Tajawal-Bold.ttf
    لو أي صورة أو الخط أو المكتبات ناقصة أو فشل الرسم: البنك يرد بالنص (embed) زي أول وما يتعطل الأمر.
  - مستقلة بالكامل: ما تستورد شي من bot.py (ما فيه استيراد دائري).
"""

import asyncio
import io
import json
import os
import random
import re
from datetime import datetime, timezone, timedelta
from functools import lru_cache

import discord
from discord.ext import commands

# مكتبات رسم الصور — لو ناقصة البنك يكمل بالنص القديم بدل ما يتعطل
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    import arabic_reshaper
    try:
        from bidi import get_display
    except ImportError:
        from bidi.algorithm import get_display
    _IMAGES_AVAILABLE = True
except ImportError as _import_error:
    _IMAGES_AVAILABLE = False
    print(f"[بنك] ⚠️ مكتبات الصور ناقصة ({_import_error}) — البنك بيرد بالنص")


# ============================================================
# أدوات عامة (منسوخة من bot.py لأن البنك يحتاجها)
# ============================================================
def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize(text: str) -> str:
    """تطبيع النص عشان المقارنة تكون متسامحة مع الهمزات والتاء المربوطة والتشكيل."""
    text = text.strip()
    text = re.sub(r"[إأآا]", "ا", text)
    text = text.replace("ى", "ي")
    text = text.replace("ة", "ه")
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return text.strip().lower()


def strip_mentions(content: str, mentions) -> str:
    for m in mentions:
        content = content.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
    return content.strip()


EXPLICIT_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


def filter_explicit_mentions(message: discord.Message) -> list:
    """يرجع بس الأعضاء المنشنين صراحة بنص الرسالة (مو بس لأنه رد على رسالتهم)."""
    ids_in_order = []
    seen = set()
    for raw_id in EXPLICIT_MENTION_PATTERN.findall(message.content):
        uid = int(raw_id)
        if uid not in seen:
            seen.add(uid)
            ids_in_order.append(uid)
    by_id = {m.id: m for m in message.mentions}
    return [by_id[uid] for uid in ids_in_order if uid in by_id]


# ---------- الرتب (بالآيدي — نفس آيديات البوت الأساسي) ----------
FOUNDER = 1557117850508992552
OWNER = 1524910780875673652
CO_OWNER = 1524916030718214325
VICE_OWNER = 1544178168678580234
ADMIN = 1524915462943801374

ADMIN_LABEL = "Admin"   # اسم العرض بس (للنصوص)

TOP_ROLES = [VICE_OWNER, CO_OWNER, OWNER, FOUNDER]
ADMIN_ROLES = [ADMIN] + TOP_ROLES


def has_role(member: discord.Member, allowed: list[int]) -> bool:
    ids = {r.id for r in member.roles}
    return any(rid in ids for rid in allowed)


async def reply(message: discord.Message, text: str):
    await message.channel.send(text)


async def react(message: discord.Message, emoji: str) -> None:
    """يحط رياكشن على رسالة الأمر (يتجاهل الأخطاء بصمت)."""
    try:
        await message.add_reaction(emoji)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass


async def usage_error(message: discord.Message, example: str) -> None:
    """يرد إن الأمر انكتب غلط ويعطي مثال صحيح."""
    await message.channel.send(
        f"{message.author.mention} ⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`{example}`")


# ---------- اللوقات (mod-logs / bot-logs) ----------
LOG_CHANNEL_IDS = {
    "mod": 1538326815142060072,
    "bot": 1538327078162927716,
}

LOG_CHANNEL_NAMES = {
    "mod": ["mod-logs"],
    "bot": ["bot-logs"],
}


def find_log_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    channel_id = LOG_CHANNEL_IDS.get(key)
    if channel_id:
        ch = guild.get_channel(channel_id)
        if ch is not None:
            return ch
    names = LOG_CHANNEL_NAMES.get(key, [])
    for ch in guild.text_channels:
        normalized_name = ch.name.lower().replace("_", "-")
        for target_name in names:
            if target_name.lower() in normalized_name:
                return ch
    return None


async def send_log(guild: discord.Guild | None, key: str, embed: discord.Embed) -> None:
    if guild is None:
        return
    channel = find_log_channel(guild, key)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def log_mod_action(guild: discord.Guild, title: str, moderator: discord.Member,
                          target=None, reason: str | None = None, extra: dict | None = None) -> None:
    embed = discord.Embed(title=title, color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="بواسطة", value=moderator.mention, inline=True)
    if target is not None:
        embed.add_field(name="العضو", value=getattr(target, "mention", str(target)), inline=True)
    if reason:
        embed.add_field(name="السبب", value=reason, inline=False)
    if extra:
        for k, v in extra.items():
            embed.add_field(name=k, value=str(v), inline=True)
    await send_log(guild, "mod", embed)


# ============================================================
# نظام البنك — منفصل تمامًا عن النقاط (ملف bank.json وعملة اسمها "ريال")
# ============================================================
# كل البنك يشتغل بس داخل روم البنك (بالآيدي، ولو ما لقيناه نبحث باسم فيه "bank").
# الأقسام: حساب + بنك (إيداع/سحب/حوالة/فائدة) + ذهب (سعر متغير) + وظائف + يومي + جريمة + سرقة + متجر + أغنياء
#          + توب حرامية + استثمار (أسهم شركات عالمية بأسعار داخل البوت).
BANK_FILE = "bank.json"
BANK_CHANNEL_ID = 1539151569826877450
BANK_CHANNEL_NAMES = ["bank"]
CURRENCY = "ريال"

# لون الـ embed (نفس لون هوية السيرفر #394047) — كل رسائل البنك بنفس اللون
BANK_COLOR = discord.Color.from_rgb(57, 64, 71)

# مجلدات صور البنك: الخلفيات + الخط (لو ناقصة يرد بالنص القديم)
BANK_ASSETS_DIR = "assets"
BANK_FONTS_DIR = "fonts"
BANK_EXTRA_DIRS = ("bank_images", "bank", "images")   # أماكن ثانية يدور فيها على الصور والخط
BANK_FONT_REGULAR = "Tajawal-Regular.ttf"
BANK_FONT_BOLD = "Tajawal-Bold.ttf"

BANK_START_CASH = 1000            # كاش البداية لأي حساب جديد
BANK_TRANSFER_FEE = 0.02          # رسوم الحوالة (2%)
BANK_TRANSFER_MIN = 10            # أقل مبلغ حوالة
BANK_INTEREST_RATE = 0.01         # فائدة يومية 1% من رصيد البنك
BANK_INTEREST_MAX = 5000          # أقصى فائدة بالمرة الوحدة
BANK_INTEREST_MIN_BALANCE = 100   # أقل رصيد بنك يستحق فائدة
BANK_INTEREST_COOLDOWN = 86400    # مرة كل 24 ساعة

DAILY_COOLDOWN = 86400            # يومي مرة كل 24 ساعة
DAILY_STREAK_WINDOW = 172800      # لو فاتك أكثر من 48 ساعة الستريك يرجع 1
DAILY_BASE = 300                  # مكافأة اليوم الأول
DAILY_STREAK_STEP = 50            # كل يوم متتالي يزيد 50
DAILY_STREAK_MAX_STEPS = 14       # أقصى زيادة (بعد 15 يوم تثبت المكافأة)

WORK_COOLDOWN = 3600              # عمل مرة كل ساعة
WORK_PER_LEVEL = 5                # كل 5 مرات عمل = مستوى جديد
WORK_BONUS_CHANCE = 0.10          # 10% فرصة مكافأة x1.5

CRIME_COOLDOWN = 3600             # جريمة مرة كل ساعة
CRIME_SUCCESS_CHANCE = 0.50
CRIME_MIN_CASH = 100              # أقل كاش عشان تجرب (للغرامة)
CRIME_REWARD_MIN, CRIME_REWARD_MAX = 200, 900
CRIME_FINE_PERCENT = 0.15         # غرامة الفشل: 15% من كاشك

ROB_COOLDOWN = 3600               # سرقة مرة كل ساعة
ROB_SUCCESS_CHANCE = 0.40
ROB_LOCKPICK_BONUS = 0.25         # أداة فتح الأقفال تزيد النجاح 25%
ROB_MIN_VICTIM_CASH = 200         # أقل كاش عند الضحية عشان تستاهل السرقة
ROB_MIN_THIEF_CASH = 100          # أقل كاش عند السارق (عشان الغرامة)
ROB_MAX_STEAL = 3000
ROB_FINE_PERCENT = 0.15           # غرامة الفشل: 15% من كاش السارق (تروح للضحية)

GOLD_BASE_PRICE = 400             # السعر المتوسط لجرام الذهب
GOLD_MIN_PRICE, GOLD_MAX_PRICE = 150, 1000
GOLD_STEP_SECONDS = 1800          # السعر يتغير كل 30 دقيقة
GOLD_MAX_STEPS = 48               # أقصى عدد تغييرات تتجمع لو البوت كان واقف
GOLD_VOLATILITY = 0.06            # أقصى تغير بالخطوة (±6%)
GOLD_SELL_FEE = 0.02              # عمولة البيع 2%
GOLD_HISTORY_SIZE = 24

# الاستثمار: شركات عالمية، الأسعار داخل البوت (مو الأسعار الحقيقية) وتتحرك مثل الذهب
STOCK_STEP_SECONDS = 1800         # السعر يتغير كل 30 دقيقة
STOCK_MAX_STEPS = 48              # أقصى عدد تغييرات تتجمع لو البوت كان واقف
STOCK_SELL_FEE = 0.01             # عمولة البيع 1%
STOCK_HISTORY_SIZE = 24
# الرمز -> (الاسم, السعر المتوسط, أقصى تغير بالخطوة)
STOCKS = {
    "AAPL": ("أبل", 190, 0.05),
    "MSFT": ("مايكروسوفت", 320, 0.045),
    "NVDA": ("إنفيديا", 600, 0.08),
    "TSLA": ("تسلا", 250, 0.09),
    "AMZN": ("أمازون", 180, 0.055),
    "GOOGL": ("جوجل", 170, 0.05),
    "META": ("ميتا", 400, 0.065),
    "NFLX": ("نتفليكس", 450, 0.07),
    "2222": ("أرامكو", 30, 0.03),
    "KO": ("كوكاكولا", 60, 0.025),
}

# (الاسم, أقل مستوى, أقل راتب, أعلى راتب, ايموجي)
BANK_JOBS = [
    ("عامل نظافة", 1, 80, 160, "🧹"),
    ("سائق توصيل", 3, 150, 260, "🛵"),
    ("موظف مبيعات", 5, 250, 400, "🛍️"),
    ("مهندس", 8, 400, 650, "👷"),
    ("مبرمج", 12, 600, 950, "💻"),
    ("طبيب", 16, 900, 1400, "🩺"),
]

# المتجر: المفتاح -> (الاسم, ايموجي, السعر, الوصف)
SHOP_ITEMS = {
    "lock": ("قفل", "🔒", 2000, "يصد أول محاولة سرقة عليك (مرة وحدة)"),
    "lockpick": ("أداة فتح الأقفال", "🗝️", 1500,
                 f"تزيد نجاح سرقتك {int(ROB_LOCKPICK_BONUS * 100)}% (مرة وحدة)"),
    "multiplier": ("مضاعف راتب", "⚡", 1000, "يضاعف راتب أول عمل (مرة وحدة)"),
    "chest": ("صندوق مفاجأة", "🎁", 1200, "يفتح فورًا وفيه مبلغ عشوائي"),
}
# صندوق المفاجأة: (المبلغ, الوزن)
CHEST_REWARDS = [(200, 30), (600, 30), (1200, 25), (3000, 12), (6000, 3)]

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")


class BankChannelRequired(commands.CheckFailure):
    pass


def find_bank_channel(guild: discord.Guild) -> discord.TextChannel | None:
    ch = guild.get_channel(BANK_CHANNEL_ID)
    if ch is not None:
        return ch
    for ch in guild.text_channels:
        name = ch.name.lower().replace("_", "-")
        if any(target in name for target in BANK_CHANNEL_NAMES):
            return ch
    return None


def _in_bank_channel(channel, guild: discord.Guild | None) -> bool:
    if guild is None:
        return False
    bank_ch = find_bank_channel(guild)
    if bank_ch is None:
        return True  # ما فيه روم bank: نسمح بأي روم
    return channel.id == bank_ch.id or getattr(channel, "parent_id", None) == bank_ch.id


# ---------- تخزين وحسابات ----------
def fmt(n) -> str:
    return f"{int(n):,}"


def parse_amount(text: str | None, maximum: int | None = None) -> int | None:
    """يفهم مبلغ (يدعم الأرقام العربية والفواصل) أو كلمة 'كل' (ترجع maximum). يرجع None لو غلط."""
    t = (text or "").strip().translate(_ARABIC_DIGITS).replace(",", "").lower()
    if t in ("كل", "الكل", "all", "max"):
        return maximum
    if not t.isdigit():
        return None
    value = int(t)
    if value <= 0 or value > 10 ** 12:
        return None
    return value


def _gold_advance(data: dict) -> bool:
    """يحدّث سعر الذهب حسب الوقت اللي مر (كل GOLD_STEP_SECONDS خطوة عشوائية). يرجع True لو تغير شي."""
    now = datetime.now(timezone.utc)
    gold = data.get("_gold")
    if not isinstance(gold, dict) or "price" not in gold:
        data["_gold"] = {"price": GOLD_BASE_PRICE, "updated": now.isoformat(), "history": [GOLD_BASE_PRICE]}
        return True
    try:
        updated = datetime.fromisoformat(gold["updated"])
    except (KeyError, ValueError, TypeError):
        gold["updated"] = now.isoformat()
        return True
    steps = int((now - updated).total_seconds() // GOLD_STEP_SECONDS)
    if steps <= 0:
        return False
    price = gold["price"]
    history = gold.setdefault("history", [price])
    for _ in range(min(steps, GOLD_MAX_STEPS)):
        drift = (GOLD_BASE_PRICE - price) * 0.03  # يرجّع السعر تدريجيًا للمتوسط
        price = price * (1 + random.uniform(-GOLD_VOLATILITY, GOLD_VOLATILITY)) + drift
        price = int(max(GOLD_MIN_PRICE, min(GOLD_MAX_PRICE, round(price))))
        history.append(price)
    gold["price"] = price
    gold["history"] = history[-GOLD_HISTORY_SIZE:]
    gold["updated"] = (updated + timedelta(seconds=GOLD_STEP_SECONDS * steps)).isoformat()
    return True


def _stocks_advance(data: dict) -> bool:
    """يحدّث أسعار أسهم الشركات حسب الوقت اللي مر (نفس فكرة الذهب). يرجع True لو تغير شي."""
    now = datetime.now(timezone.utc)
    stocks = data.get("_stocks")
    if not isinstance(stocks, dict) or not isinstance(stocks.get("prices"), dict):
        data["_stocks"] = {"updated": now.isoformat(),
                           "prices": {sym: info[1] for sym, info in STOCKS.items()},
                           "history": {sym: [info[1]] for sym, info in STOCKS.items()}}
        return True
    changed = False
    prices = stocks["prices"]
    history = stocks.setdefault("history", {})
    for sym, (_name, base, _vol) in STOCKS.items():
        if sym not in prices:
            prices[sym] = base
            history[sym] = [base]
            changed = True
    try:
        updated = datetime.fromisoformat(stocks["updated"])
    except (KeyError, ValueError, TypeError):
        stocks["updated"] = now.isoformat()
        return True
    steps = int((now - updated).total_seconds() // STOCK_STEP_SECONDS)
    if steps <= 0:
        return changed
    for sym, (_name, base, vol) in STOCKS.items():
        price = prices[sym]
        hist = history.setdefault(sym, [price])
        for _ in range(min(steps, STOCK_MAX_STEPS)):
            drift = (base - price) * 0.02  # يرجّع السعر تدريجيًا للمتوسط
            price = price * (1 + random.uniform(-vol, vol)) + drift
            price = int(max(max(1, base * 0.3), min(base * 3, round(price))))
            hist.append(price)
        prices[sym] = price
        history[sym] = hist[-STOCK_HISTORY_SIZE:]
    stocks["updated"] = (updated + timedelta(seconds=STOCK_STEP_SECONDS * steps)).isoformat()
    return True


def bank_load() -> dict:
    """يقرأ ملف البنك ويحدّث سعر الذهب والأسهم (ويحفظه فورًا لو تغير، عشان الكل يشوف نفس السعر)."""
    data = load_json(BANK_FILE)
    changed = _gold_advance(data)
    if _stocks_advance(data):
        changed = True
    if changed:
        save_json(BANK_FILE, data)
    return data


def bank_save(data: dict) -> None:
    save_json(BANK_FILE, data)


def bank_acct(data: dict, guild_id: int, user_id: int) -> dict:
    guild_accounts = data.setdefault(str(guild_id), {})
    acct = guild_accounts.get(str(user_id))
    if acct is None:
        acct = {"cash": BANK_START_CASH, "bank": 0, "gold": 0, "job": None, "works": 0,
                "last_work": None, "last_interest": None, "last_rob": None}
        guild_accounts[str(user_id)] = acct
    # حقول جديدة (الحسابات القديمة تاخذها تلقائيًا)
    acct.setdefault("last_crime", None)
    acct.setdefault("last_daily", None)
    acct.setdefault("streak", 0)
    acct.setdefault("robs", 0)       # عدد السرقات الناجحة (لتوب حرامية)
    acct.setdefault("stolen", 0)     # مجموع اللي سرقه (لتوب حرامية)
    if not isinstance(acct.get("items"), dict):
        acct["items"] = {}
    if not isinstance(acct.get("stocks"), dict):
        acct["stocks"] = {}          # الأسهم: {الرمز: {"shares": عدد, "cost": مجموع اللي دفعه}}
    return acct


def get_bank_balance(guild_id: int, user_id: int) -> int:
    """رصيد العضو بالبنك (بدون الكاش) — للقراءة فقط، ما ينشئ حساب ولا يغيّر شي. يستخدمها أمر p بالبوت الأساسي.
    لو تبي الكاش يدخل معه غيّر السطر الأخير إلى: acct.get("bank", 0) + acct.get("cash", 0)"""
    data = load_json(BANK_FILE)
    acct = data.get(str(guild_id), {}).get(str(user_id))
    if not isinstance(acct, dict):
        return 0
    return int(acct.get("bank", 0))


def _level(acct: dict) -> int:
    return acct.get("works", 0) // WORK_PER_LEVEL + 1


def _stock_value(acct: dict, stock_prices: dict) -> int:
    total = 0
    for sym, holding in acct.get("stocks", {}).items():
        if isinstance(holding, dict):
            total += holding.get("shares", 0) * stock_prices.get(sym, 0)
    return total


def _net_worth(acct: dict, gold_price: int, stock_prices: dict | None = None) -> int:
    worth = acct.get("cash", 0) + acct.get("bank", 0) + acct.get("gold", 0) * gold_price
    if stock_prices:
        worth += _stock_value(acct, stock_prices)
    return worth


def _cooldown_left(last_iso: str | None, seconds: int) -> int:
    if not last_iso:
        return 0
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_iso)).total_seconds()
    except (ValueError, TypeError):
        return 0
    return max(0, int(seconds - elapsed))


def _fmt_wait(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ساعة و{minutes} دقيقة"
    if minutes:
        return f"{minutes} دقيقة"
    return f"{secs} ثانية"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_job(text: str | None):
    t = normalize(text or "")
    if not t:
        return None
    for job in BANK_JOBS:
        if normalize(job[0]) == t:
            return job
    for job in BANK_JOBS:
        if t in normalize(job[0]):
            return job
    return None


def _bank_embed(title: str, description: str | None = None, color: discord.Color | None = None) -> discord.Embed:
    # كل رسائل البنك بلون واحد (BANK_COLOR) — الباراميتر color يتجاهل عشان ما تطلع ألوان مزعجة
    return discord.Embed(title=title, description=description, color=BANK_COLOR)


def _items_text(acct: dict) -> str:
    lines = []
    for key, (name, emoji, _price, _desc) in SHOP_ITEMS.items():
        count = acct["items"].get(key, 0)
        if count > 0:
            lines.append(f"{emoji} {name} × {count}")
    return "\n".join(lines)


def _open_chest() -> int:
    amounts = [a for a, _ in CHEST_REWARDS]
    weights = [w for _, w in CHEST_REWARDS]
    return random.choices(amounts, weights=weights, k=1)[0]


def _money(n, sign: str = "") -> str:
    return f"{sign}{fmt(n)} {CURRENCY}"


def _pct_change(history: list) -> float | None:
    if len(history) < 2 or not history[-2]:
        return None
    return (history[-1] - history[-2]) / history[-2] * 100


def _holdings(acct: dict, stock_prices: dict) -> list:
    """أسهم العضو: [(الرمز, الاسم, العدد, التكلفة, القيمة الحالية, الربح/الخسارة)]."""
    rows = []
    for sym, holding in acct.get("stocks", {}).items():
        if sym not in STOCKS or not isinstance(holding, dict) or holding.get("shares", 0) <= 0:
            continue
        shares, cost = holding["shares"], holding.get("cost", 0)
        value = shares * stock_prices.get(sym, 0)
        rows.append((sym, STOCKS[sym][0], shares, cost, value, value - cost))
    return rows


# ============================================================
# صور البنك (Pillow) — الخلفيات من assets والخط من fonts
# ============================================================
# الإحداثيات مقاسة على الخلفيات اللي ولّدتها، وتتحول تلقائيًا لو مقاس الصورة اختلف.
_REF_WIDE = (1376, 768)    # حسابي / إيصال / سوق الذهب / بيع وشراء / نتيجة
_REF_TALL = (896, 1200)    # القوائم

C_TEXT = (238, 236, 230)
C_MUTED = (176, 176, 170)
C_GOLD = (212, 190, 140)
C_GREEN = (92, 200, 140)
C_RED = (226, 98, 98)

_BOARD_ROWS_Y = [200, 302, 402, 521, 620, 714, 805, 894, 981, 1068]

_EMOJI_PATTERN = re.compile("[\U00010000-\U0010FFFF\u2190-\u2BFF\uFE00-\uFE0F\u200b-\u200f\u202a-\u202e]")


def _clean_name(name: str) -> str:
    """يشيل الايموجي والرموز اللي الخط ما يدعمها (تطلع مربعات بالصورة)."""
    cleaned = _EMOJI_PATTERN.sub("", name or "").strip()
    return cleaned or "عضو"


def _shape(text, ltr: bool = False) -> str:
    """يوصّل الحروف العربية ويرتبها يمين لشمال عشان Pillow يرسمها صح."""
    shaped = arabic_reshaper.reshape(str(text))
    if ltr:
        try:
            return get_display(shaped, base_dir="L")
        except TypeError:
            return get_display(shaped)
    return get_display(shaped)


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_BANK_BG_NAMES = ("account", "receipt", "market", "trade", "result", "leaderboard")
_SYSTEM_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
)


def _candidate_dirs(primary: str) -> list:
    """المجلدات اللي ندور فيها: جنب bank.py وجنب مكان تشغيل البوت، بالاسم الأساسي ثم الأسماء البديلة."""
    bases = [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]
    names = [primary, *BANK_EXTRA_DIRS, ""]
    seen, result = set(), []
    for base in bases:
        for name in names:
            folder = os.path.join(base, name) if name else base
            if folder not in seen and os.path.isdir(folder):
                seen.add(folder)
                result.append(folder)
    return result


def _find_asset(stem: str) -> str | None:
    """يلقى صورة الخلفية باسمها (account / receipt ...) بأي امتداد وأي حالة أحرف."""
    for folder in _candidate_dirs(BANK_ASSETS_DIR):
        try:
            files = {f.lower(): f for f in os.listdir(folder)}
        except OSError:
            continue
        for ext in _IMAGE_EXTS:
            found = files.get((stem + ext).lower())
            if found:
                return os.path.join(folder, found)
    return None


@lru_cache(maxsize=4)
def _find_font(bold: bool) -> str | None:
    wanted = (BANK_FONT_BOLD if bold else BANK_FONT_REGULAR).lower()
    candidates = []
    for folder in _candidate_dirs(BANK_FONTS_DIR):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        candidates += [(folder, f) for f in names if f.lower().endswith((".ttf", ".otf"))]
    for folder, f in candidates:
        if f.lower() == wanted:
            return os.path.join(folder, f)
    style_words = ("bold",) if bold else ("regular", "medium")
    tajawal = [(d, f) for d, f in candidates if "tajawal" in f.lower()]
    for pool in (tajawal, candidates):
        for folder, f in pool:
            if any(w in f.lower() for w in style_words):
                return os.path.join(folder, f)
        if pool:
            return os.path.join(pool[0][0], pool[0][1])
    for path in _SYSTEM_FONTS:      # آخر حل: خط النظام (يدعم العربي) لو ما حطيت Tajawal
        if os.path.isfile(path):
            return path
    return None


@lru_cache(maxsize=64)
def _load_font(size: int, bold: bool):
    path = _find_font(bold)
    if path is None:
        raise FileNotFoundError("ما لقيت ملف الخط Tajawal (.ttf) — حطه بمجلد fonts")
    # BASIC لأن التشكيل والترتيب سويناهم بالكود (لو raqm اشتغل يعكس النص مرتين)
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)


def _images_report() -> list:
    """يرجع قائمة مشاكل الصور (فاضية = كل شي تمام). يطبعها setup_bank باللوق عشان تعرف وش ناقص."""
    problems = []
    if not _IMAGES_AVAILABLE:
        problems.append("مكتبات الصور مو مثبتة (Pillow / arabic-reshaper / python-bidi)")
        return problems
    for stem in _BANK_BG_NAMES:
        if _find_asset(stem) is None:
            problems.append(f"ناقصة الخلفية: {stem}.png")
    if _find_font(True) is None:
        problems.append("ما لقيت ملف الخط Tajawal (.ttf) بمجلد fonts")
    if problems:
        folders = ", ".join(_candidate_dirs(BANK_ASSETS_DIR)) or "(ما لقيت أي مجلد)"
        problems.append(f"المجلدات اللي دورت فيها: {folders}")
    return problems


class _Canvas:
    """لوحة رسم فوق خلفية جاهزة. كل الإحداثيات بمقاس الخلفية الأصلي وتتحول تلقائيًا."""

    def __init__(self, bg_name: str, ref: tuple):
        path = _find_asset(os.path.splitext(bg_name)[0])
        if path is None:
            raise FileNotFoundError(f"ما لقيت صورة الخلفية {bg_name} (مجلد assets أو bank_images)")
        self.img = Image.open(path).convert("RGBA")
        width, height = self.img.size
        self.sx, self.sy = width / ref[0], height / ref[1]
        self.k = (self.sx + self.sy) / 2
        self.draw = ImageDraw.Draw(self.img)

    def pt(self, x, y):
        return (x * self.sx, y * self.sy)

    def font(self, size, bold=True):
        return _load_font(max(8, int(round(size * self.k))), bold)

    def text(self, x, y, text, size=34, fill=C_TEXT, bold=True, anchor="mm", max_w=None, ltr=False):
        shaped = _shape(text, ltr)
        current = size
        font = self.font(current, bold)
        if max_w:
            limit = max_w * self.sx
            while current > 14 and self.draw.textlength(shaped, font=font) > limit:
                current -= 2
                font = self.font(current, bold)
        self.draw.text(self.pt(x, y), shaped, font=font, fill=fill, anchor=anchor)

    def avatar(self, data, cx, cy, r, label="", label_size=None):
        rad = max(4, int(round(r * self.k)))
        size = rad * 2
        px, py = self.pt(cx, cy)
        tile = None
        if data:
            try:
                tile = Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            except Exception:
                tile = None
        if tile is None:
            tile = Image.new("RGBA", (size, size), (44, 47, 52, 255))
            if label:
                fsize = label_size or r * (0.95 if len(label) <= 2 else 0.5)
                font = _load_font(max(8, int(round(fsize * self.k))), True)
                ImageDraw.Draw(tile).text((rad, rad), _shape(label, True), font=font, fill=C_MUTED, anchor="mm")
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        mask = mask.resize((size, size), Image.Resampling.LANCZOS)
        self.img.paste(tile, (int(round(px - rad)), int(round(py - rad))), mask)

    def stat(self, box, label, value, sub=None, color=C_TEXT):
        """خانة فيها عنوان صغير وقيمة كبيرة وسطر تحتها (حسابي / سوق الذهب)."""
        x0, y0, x1, y1 = box
        cx, width = (x0 + x1) / 2, (x1 - x0) - 36
        self.text(cx, y0 + 46, label, 30, C_MUTED, False, max_w=width)
        self.text(cx, y0 + 108, value, 56, color, True, max_w=width, ltr=True)
        if sub:
            self.text(cx, y0 + 160, sub, 28, C_MUTED, False, max_w=width, ltr=True)

    def chart(self, box, values, color):
        x0, y0, x1, y1 = box
        vals = list(values) if len(values) >= 2 else [values[0], values[0]]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        count = len(vals)
        pts = []
        for i, v in enumerate(vals):
            y = (y0 + y1) / 2 if hi == lo else y1 - (y1 - y0) * (v - lo) / span
            pts.append(self.pt(x0 + (x1 - x0) * i / (count - 1), y))
        self.draw.line(pts, fill=color, width=max(2, int(4 * self.k)), joint="curve")
        ex, ey = pts[-1]
        dot = 8 * self.k
        self.draw.ellipse((ex - dot, ey - dot, ex + dot, ey + dot), fill=color)
        self.text(x0 - 12, y0, fmt(hi), 22, C_MUTED, False, "rm")
        self.text(x0 - 12, y1, fmt(lo), 22, C_MUTED, False, "rm")

    def patch(self, src, dst):
        """ينسخ جزء نظيف من الخلفية فوق بقعة (يخفي الرسمة الباهتة أو المربع اللي طلع من المولّد)."""
        region = self.img.crop((int(src[0] * self.sx), int(src[1] * self.sy),
                                int(src[2] * self.sx), int(src[3] * self.sy)))
        width, height = region.size
        margin = max(2, min(width, height) // 5)
        mask = Image.new("L", region.size, 0)
        ImageDraw.Draw(mask).rectangle((margin, margin, width - margin - 1, height - margin - 1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(margin / 2))   # حواف ناعمة عشان ما يبان الترقيع
        self.img.paste(region, (int(dst[0] * self.sx), int(dst[1] * self.sy)), mask)

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.img.convert("RGB").save(buf, "PNG", optimize=True)
        return buf.getvalue()


def _render_account(avatar, name, cash, bank, gold, gold_value, worth, job_text, streak):
    c = _Canvas("account.png", _REF_WIDE)
    c.avatar(avatar, 312, 384, 164, name[:1])
    c.text(312, 622, name, 46, C_TEXT, max_w=500)
    c.text(312, 672, job_text, 30, C_MUTED, False, max_w=500)
    if streak > 0:
        c.text(312, 712, f"ستريك {streak} يوم", 28, C_GOLD, False, max_w=500)
    c.stat((602, 172, 917, 363), "الكاش", fmt(cash), CURRENCY)
    c.stat((956, 172, 1271, 363), "البنك", fmt(bank), CURRENCY)
    c.stat((602, 405, 917, 596), "الذهب", f"{fmt(gold)} جرام", f"قيمته {fmt(gold_value)} {CURRENCY}")
    c.stat((956, 405, 1271, 596), "صافي الثروة", fmt(worth), CURRENCY, C_GOLD)
    return c.to_bytes()


def _render_receipt(avatar, name, title, amount_text, amount_color, rows):
    c = _Canvas("receipt.png", _REF_WIDE)
    c.avatar(avatar, 687, 127, 58, name[:1])
    c.text(687, 232, name, 42, C_TEXT, max_w=520)
    c.text(687, 305, amount_text, 80, amount_color, True, max_w=620, ltr=True)
    c.text(688, 397, title, 34, C_GOLD, True, max_w=560)
    for cy, (label, value, color) in zip((500, 563, 627), rows[:3]):
        c.text(990, cy, label, 28, C_MUTED, False, "rm", max_w=200)
        c.text(386, cy, value, 34, color or C_TEXT, True, "lm", max_w=420, ltr=True)
    return c.to_bytes()


def _render_market(avatar, name, buy_price, sell_price, history, gold_grams, gold_value):
    c = _Canvas("market.png", _REF_WIDE)
    c.avatar(avatar, 103, 100, 62, name[:1])
    c.text(103, 205, name, 26, C_TEXT, max_w=150)
    c.text(775, 98, "سوق الذهب", 56, C_TEXT, max_w=760)
    c.stat((1043, 263, 1321, 503), "سعر الشراء", fmt(buy_price), f"{CURRENCY} للجرام")
    c.stat((55, 263, 333, 503), "سعر البيع", fmt(sell_price), f"{CURRENCY} للجرام")
    pct = _pct_change(history)
    if pct is None or round(pct, 1) == 0:
        trend_text, trend_color = "ثابت", C_GOLD
    else:
        trend_text, trend_color = f"{pct:+.1f}%", (C_GREEN if pct > 0 else C_RED)
    c.patch((620, 420, 810, 525), (395, 420))   # يخفي خط الرسم الباهت اللي بالخلفية
    c.text(688, 238, "حركة السعر", 28, C_MUTED, False)
    c.text(688, 284, trend_text, 44, trend_color, True, ltr=True)
    line_color = C_GREEN if len(history) > 1 and history[-1] >= history[0] else C_RED
    c.chart((445, 330, 960, 520), history, line_color)
    c.text(688, 650, f"ذهبك: {fmt(gold_grams)} جرام - قيمته {fmt(gold_value)} {CURRENCY}", 36, C_GOLD, True,
           max_w=640)
    return c.to_bytes()


def _render_trade(avatar, name, title, rows, footer):
    c = _Canvas("trade.png", _REF_WIDE)
    c.patch((598, 24, 642, 56), (518, 24))      # يخفي المربع الرمادي الصغير اللي بالخلفية
    c.avatar(avatar, 193, 384, 113, name[:1])
    c.text(193, 548, name, 40, C_TEXT, max_w=330)
    c.text(688, 92, title, 56, C_TEXT, max_w=760)
    for cy, (label, value, color) in zip((235, 380, 525), rows[:3]):
        c.text(1115, cy - 30, label, 26, C_MUTED, False, max_w=340)
        c.text(1115, cy + 16, value, 44, color or C_TEXT, True, max_w=340, ltr=True)
    if footer:
        c.text(688, 680, footer, 32, C_MUTED, False, max_w=760)
    return c.to_bytes()


def _render_result(avatar, name, headline, amount_text, amount_color, lines):
    c = _Canvas("result.png", _REF_WIDE)
    c.avatar(avatar, 338, 383, 182, name[:1])
    c.text(338, 628, name, 46, C_TEXT, max_w=480)
    cx = 962
    if amount_text:
        c.text(cx, 268, headline, 44, C_TEXT, max_w=520)
        c.text(cx, 360, amount_text, 84, amount_color, True, max_w=520, ltr=True)
        y, limit = 442, 2
    else:
        c.text(cx, 300, headline, 56, C_TEXT, max_w=520)
        y, limit = 392, 3
    for text, color in lines[:limit]:
        c.text(cx, y, text, 30, color, False, max_w=520, ltr=True)
        y += 48
    return c.to_bytes()


def _render_board(title, rows, footer):
    c = _Canvas("leaderboard.png", _REF_TALL)
    c.text(448, 62, title, 56, C_TEXT, max_w=700)
    for cy, row in zip(_BOARD_ROWS_Y, rows[:10]):
        c.avatar(row.get("avatar"), 135, cy, 29, row.get("ring", ""), row.get("ring_size"))
        sub = row.get("name_sub")
        c.text(190, cy - (14 if sub else 0), row["name"], 34, row.get("name_color", C_TEXT), True, "lm", max_w=380)
        if sub:
            c.text(190, cy + 24, sub, 22, C_MUTED, False, "lm", max_w=380)
        value_sub = row.get("value_sub")
        c.text(790, cy - (14 if value_sub else 0), row["value"], 32, row.get("value_color", C_GOLD), True, "rm",
               max_w=230, ltr=True)
        if value_sub:
            c.text(790, cy + 24, value_sub, 22, row.get("value_sub_color", C_MUTED), False, "rm", max_w=230, ltr=True)
    if footer:
        text, color = footer
        c.text(448, 1152, text, 28, color, False, max_w=760, ltr=True)
    return c.to_bytes()


# ---------- مساعدات الرسم (async) — أي فشل يرجع None والأمر يطلع بالنص القديم ----------
async def _avatar_bytes(user, size: int = 256):
    try:
        return await asyncio.wait_for(user.display_avatar.replace(size=size, format="png").read(), timeout=2.0)
    except Exception:
        return None


async def _no_avatar():
    return None


async def _card(render, *args):
    if not _IMAGES_AVAILABLE:
        return None
    try:
        return await asyncio.to_thread(render, *args)
    except Exception as e:
        print(f"[بنك] ⚠️ فشل رسم الصورة ({render.__name__}): {e!r} — رجعنا للنص")
        return None


def _make_file(img: bytes | None) -> discord.File | None:
    if img is None:
        return None
    return discord.File(io.BytesIO(img), filename="bank.png")


async def _account_card(data: dict, member, acct: dict):
    price = data["_gold"]["price"]
    job = _find_job(acct["job"]) if acct.get("job") else None
    job_text = f"{job[0]} - المستوى {_level(acct)}" if job else f"عاطل - المستوى {_level(acct)}"
    worth = _net_worth(acct, price, data["_stocks"]["prices"])
    avatar = await _avatar_bytes(member)
    return await _card(_render_account, avatar, _clean_name(member.display_name), acct["cash"], acct["bank"],
                       acct["gold"], acct["gold"] * price, worth, job_text, acct.get("streak", 0))


async def _receipt_card(user, title, amount_text, amount_color, rows):
    avatar = await _avatar_bytes(user)
    return await _card(_render_receipt, avatar, _clean_name(user.display_name), title, amount_text,
                       amount_color, rows)


async def _market_card(data: dict, user, acct: dict):
    gold = data["_gold"]
    price = gold["price"]
    sell_price = int(price * (1 - GOLD_SELL_FEE))
    avatar = await _avatar_bytes(user)
    return await _card(_render_market, avatar, _clean_name(user.display_name), price, sell_price,
                       list(gold["history"]), acct["gold"], acct["gold"] * sell_price)


async def _trade_card(user, title, rows, footer):
    avatar = await _avatar_bytes(user)
    return await _card(_render_trade, avatar, _clean_name(user.display_name), title, rows, footer)


async def _result_card(user, headline, amount_text, amount_color, lines):
    avatar = await _avatar_bytes(user)
    return await _card(_render_result, avatar, _clean_name(user.display_name), headline, amount_text,
                       amount_color, lines)


async def _board_card(title, rows, footer=None):
    members = [r.get("member") for r in rows[:10]]
    avatars = await asyncio.gather(*[_avatar_bytes(m, 128) if m is not None else _no_avatar() for m in members])
    prepared = []
    for row, avatar in zip(rows[:10], avatars):
        item = {k: v for k, v in row.items() if k != "member"}
        item["avatar"] = avatar
        prepared.append(item)
    return await _card(_render_board, title, prepared, footer)


# ============================================================
# الـ embeds (الرد بالنص — يستخدم لو الصورة ما اشتغلت)
# ============================================================
def _account_embed(data: dict, member: discord.abc.User, acct: dict) -> discord.Embed:
    price = data["_gold"]["price"]
    stock_prices = data["_stocks"]["prices"]
    embed = _bank_embed(f"🏦 حساب {member.display_name}")
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="💵 الكاش", value=f"{fmt(acct['cash'])} {CURRENCY}", inline=True)
    embed.add_field(name="🏦 البنك", value=f"{fmt(acct['bank'])} {CURRENCY}", inline=True)
    embed.add_field(name="🪙 الذهب",
                    value=f"{fmt(acct['gold'])} جرام (≈ {fmt(acct['gold'] * price)} {CURRENCY})", inline=True)
    job = _find_job(acct["job"]) if acct.get("job") else None
    job_text = f"{job[4]} {job[0]} • مستوى {_level(acct)}" if job else f"عاطل • مستوى {_level(acct)}"
    embed.add_field(name="💼 الوظيفة", value=job_text, inline=True)
    embed.add_field(name="💎 صافي الثروة", value=f"{fmt(_net_worth(acct, price, stock_prices))} {CURRENCY}", inline=True)
    if acct.get("streak", 0) > 0:
        embed.add_field(name="🔥 ستريك اليومي", value=f"{acct['streak']} يوم", inline=True)
    stocks_value = _stock_value(acct, stock_prices)
    if stocks_value > 0:
        embed.add_field(name="📊 الأسهم", value=f"{fmt(stocks_value)} {CURRENCY}", inline=True)
    items = _items_text(acct)
    if items:
        embed.add_field(name="🎒 الأغراض", value=items, inline=False)
    embed.set_footer(text="الكاش ممكن ينسرق — فلوس البنك بأمان 🔒")
    return embed


def _gold_trend(history: list) -> str:
    if len(history) < 2 or not history[-2]:
        return "—"
    change = (history[-1] - history[-2]) / history[-2] * 100
    if change > 0:
        return f"▲ +{change:.1f}%"
    if change < 0:
        return f"▼ {change:.1f}%"
    return "● ثابت"


def _gold_embed(data: dict, acct: dict) -> discord.Embed:
    gold = data["_gold"]
    price = gold["price"]
    sell_price = int(price * (1 - GOLD_SELL_FEE))
    embed = _bank_embed("🪙 سوق الذهب")
    embed.add_field(name="سعر الشراء (للجرام)", value=f"{fmt(price)} {CURRENCY}", inline=True)
    embed.add_field(name="سعر البيع (للجرام)", value=f"{fmt(sell_price)} {CURRENCY}", inline=True)
    embed.add_field(name="الحركة", value=_gold_trend(gold["history"]), inline=True)
    embed.add_field(name="آخر الأسعار", value=" ← ".join(str(p) for p in gold["history"][-8:]), inline=False)
    embed.add_field(name="ذهبك", value=f"{fmt(acct['gold'])} جرام (≈ {fmt(acct['gold'] * sell_price)} {CURRENCY})",
                    inline=False)
    embed.set_footer(text=f"السعر يتغير كل {GOLD_STEP_SECONDS // 60} دقيقة")
    return embed


def _jobs_embed(acct: dict) -> discord.Embed:
    level = _level(acct)
    lines = []
    for name, min_level, low, high, emoji in BANK_JOBS:
        lock = "" if level >= min_level else " 🔒"
        current = " ✅" if acct.get("job") == name else ""
        lines.append(f"{emoji} **{name}** — مستوى {min_level}+ — {fmt(low)}–{fmt(high)} {CURRENCY}{lock}{current}")
    embed = _bank_embed("💼 الوظائف", "\n".join(lines))
    embed.set_footer(text=f"مستواك: {level} • اختر وظيفة من القائمة تحت للتوظف • كل {WORK_PER_LEVEL} مرات عمل = مستوى")
    return embed


def _shop_embed(acct: dict) -> discord.Embed:
    lines = []
    for key, (name, emoji, price, desc) in SHOP_ITEMS.items():
        owned = acct["items"].get(key, 0)
        owned_text = f" (عندك {owned})" if owned else ""
        lines.append(f"{emoji} **{name}** — {fmt(price)} {CURRENCY}{owned_text}\n{desc}")
    embed = _bank_embed("🛍️ المتجر", "\n\n".join(lines))
    embed.set_footer(text=f"كاشك: {fmt(acct['cash'])} {CURRENCY} • اختر غرض من القائمة تحت")
    return embed


def _items_embed(acct: dict) -> discord.Embed:
    text = _items_text(acct)
    return _bank_embed("🎒 أغراضي", text or "ما عندك أغراض. اشتر من 🛍️ المتجر.")


def _stocks_embed(data: dict, acct: dict) -> discord.Embed:
    prices = data["_stocks"]["prices"]
    history = data["_stocks"]["history"]
    lines = []
    for sym, (name, _base, _vol) in STOCKS.items():
        pct = _pct_change(history.get(sym, []))
        trend = "—" if pct is None else f"{pct:+.1f}%"
        owned = acct["stocks"].get(sym, {}).get("shares", 0)
        owned_text = f" (عندك {owned})" if owned else ""
        lines.append(f"**{name}** ({sym}) — {fmt(prices[sym])} {CURRENCY} — {trend}{owned_text}")
    embed = _bank_embed("📊 سوق الأسهم", "\n".join(lines))
    embed.set_footer(text=f"الأسعار تتغير كل {STOCK_STEP_SECONDS // 60} دقيقة • اختر شركة من القوائم تحت للشراء أو البيع")
    return embed


def _portfolio_embed(data: dict, acct: dict) -> discord.Embed:
    rows = _holdings(acct, data["_stocks"]["prices"])
    lines = []
    for sym, name, shares, cost, value, pnl in rows:
        sign = "+" if pnl > 0 else ""
        lines.append(f"**{name}** ({sym}) — {fmt(shares)} سهم — {fmt(value)} {CURRENCY} ({sign}{fmt(pnl)})")
    return _bank_embed("💼 محفظتي", "\n".join(lines) or "ما عندك أسهم لين الحين.")


async def _err(interaction: discord.Interaction, text: str) -> None:
    await interaction.response.send_message(text, ephemeral=True)


async def _out(interaction: discord.Interaction, panel, embed: discord.Embed | None,
               content: str | None = None, ping=None, file: discord.File | None = None,
               img: bytes | None = None) -> None:
    """لو فيه لوحة: يعدّل رسالة اللوحة. لو لا: يرسل رسالة عامة (للحوالة والسرقة).
    img = الصورة المرسومة؛ لو None يطلع الرد بالنص (embed) زي أول."""
    if img is not None:
        file = _make_file(img)
        embed = None
    if panel is not None:
        await interaction.response.edit_message(embed=embed, view=panel, attachments=[file] if file else [])
    else:
        mentions = discord.AllowedMentions(users=[ping]) if ping is not None else discord.AllowedMentions.none()
        kwargs = {"allowed_mentions": mentions}
        if embed is not None:
            kwargs["embed"] = embed
        if content:
            kwargs["content"] = content
        if file:
            kwargs["file"] = file
        await interaction.response.send_message(**kwargs)


# ============================================================
# منطق الأزرار
# ============================================================
async def _act_account(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    bank_save(data)
    img = await _account_card(data, interaction.user, acct)
    await _out(interaction, panel, _account_embed(data, interaction.user, acct), img=img)


async def _act_deposit(interaction, text, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    n = parse_amount(text, acct["cash"])
    if not n:
        return await _err(interaction, "⚠️ اكتب رقم أكبر من صفر أو كلمة `كل` (وكاشك لازم يكون أكبر من صفر).")
    if n > acct["cash"]:
        return await _err(interaction, f"❌ كاشك ما يكفي. معك **{fmt(acct['cash'])}** {CURRENCY} كاش.")
    acct["cash"] -= n
    acct["bank"] += n
    bank_save(data)
    embed = _bank_embed("🏦 تم الإيداع", f"أودعت **{fmt(n)}** {CURRENCY} بالبنك.")
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.add_field(name="🏦 البنك", value=fmt(acct["bank"]), inline=True)
    img = await _receipt_card(interaction.user, "إيصال إيداع", _money(n), C_TEXT, [
        ("الكاش", _money(acct["cash"]), None),
        ("البنك", _money(acct["bank"]), None),
        ("الإجمالي", _money(acct["cash"] + acct["bank"]), C_GOLD)])
    await _out(interaction, panel, embed, img=img)


async def _act_withdraw(interaction, text, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    n = parse_amount(text, acct["bank"])
    if not n:
        return await _err(interaction, "⚠️ اكتب رقم أكبر من صفر أو كلمة `كل` (ورصيدك بالبنك لازم يكون أكبر من صفر).")
    if n > acct["bank"]:
        return await _err(interaction, f"❌ رصيدك بالبنك ما يكفي. عندك **{fmt(acct['bank'])}** {CURRENCY}.")
    acct["bank"] -= n
    acct["cash"] += n
    bank_save(data)
    embed = _bank_embed("🏦 تم السحب", f"سحبت **{fmt(n)}** {CURRENCY} للكاش.")
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.add_field(name="🏦 البنك", value=fmt(acct["bank"]), inline=True)
    img = await _receipt_card(interaction.user, "إيصال سحب", _money(n), C_TEXT, [
        ("الكاش", _money(acct["cash"]), None),
        ("البنك", _money(acct["bank"]), None),
        ("الإجمالي", _money(acct["cash"] + acct["bank"]), C_GOLD)])
    await _out(interaction, panel, embed, img=img)


async def _act_transfer(interaction, member, text):
    if member.bot or member.id == interaction.user.id:
        return await _err(interaction, "⚠️ ما تقدر تحول لنفسك أو لبوت.")
    data = bank_load()
    sender = bank_acct(data, interaction.guild.id, interaction.user.id)
    n = parse_amount(text, sender["bank"])
    if not n or n < BANK_TRANSFER_MIN:
        return await _err(interaction, f"⚠️ اكتب مبلغ صحيح (أقل مبلغ {BANK_TRANSFER_MIN} {CURRENCY}).")
    if n > sender["bank"]:
        return await _err(interaction, f"❌ رصيدك بالبنك ما يكفي. عندك **{fmt(sender['bank'])}** {CURRENCY}.")
    receiver = bank_acct(data, interaction.guild.id, member.id)
    fee = max(1, round(n * BANK_TRANSFER_FEE))
    received = n - fee
    sender["bank"] -= n
    receiver["bank"] += received
    bank_save(data)
    embed = _bank_embed("💸 حوالة بنكية ناجحة")
    embed.add_field(name="من", value=interaction.user.mention, inline=True)
    embed.add_field(name="إلى", value=member.mention, inline=True)
    embed.add_field(name="المبلغ", value=f"{fmt(n)} {CURRENCY}", inline=True)
    embed.add_field(name="الرسوم", value=f"{fmt(fee)} {CURRENCY}", inline=True)
    embed.add_field(name="وصل للمستلم", value=f"{fmt(received)} {CURRENCY}", inline=True)
    img = await _receipt_card(interaction.user, "حوالة بنكية", _money(n, "-"), C_RED, [
        ("إلى", _clean_name(member.display_name), None),
        ("الرسوم", _money(fee), None),
        ("وصل للمستلم", _money(received), C_GREEN)])
    await _out(interaction, None, embed, content=member.mention, ping=member, img=img)


async def _act_interest(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    wait = _cooldown_left(acct["last_interest"], BANK_INTEREST_COOLDOWN)
    if wait:
        return await _err(interaction, f"⏳ استلمت فائدتك اليوم. ارجع بعد **{_fmt_wait(wait)}**.")
    if acct["bank"] < BANK_INTEREST_MIN_BALANCE:
        return await _err(interaction, f"⚠️ لازم يكون رصيدك بالبنك **{BANK_INTEREST_MIN_BALANCE}** {CURRENCY} على الأقل عشان تاخذ فائدة.")
    interest = min(BANK_INTEREST_MAX, max(1, int(acct["bank"] * BANK_INTEREST_RATE)))
    acct["bank"] += interest
    acct["last_interest"] = _now_iso()
    bank_save(data)
    embed = _bank_embed("📈 فائدة البنك",
                        f"انضاف لرصيدك **{fmt(interest)}** {CURRENCY} ({BANK_INTEREST_RATE * 100:.0f}% من رصيدك).")
    embed.add_field(name="🏦 رصيدك الحين", value=f"{fmt(acct['bank'])} {CURRENCY}", inline=True)
    img = await _receipt_card(interaction.user, "فائدة البنك", _money(interest, "+"), C_GREEN, [
        ("نسبة الفائدة", f"{BANK_INTEREST_RATE * 100:.0f}%", None),
        ("رصيدك الحين", _money(acct["bank"]), None),
        ("الفائدة القادمة", "بعد 24 ساعة", C_MUTED)])
    await _out(interaction, panel, embed, img=img)


async def _act_daily(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    wait = _cooldown_left(acct["last_daily"], DAILY_COOLDOWN)
    if wait:
        return await _err(interaction, f"⏳ استلمت مكافأتك اليومية. ارجع بعد **{_fmt_wait(wait)}**.")
    # الستريك: لو استلمت خلال 48 ساعة من آخر مرة يكمل، وإلا يرجع 1
    if acct["last_daily"] and _cooldown_left(acct["last_daily"], DAILY_STREAK_WINDOW) > 0:
        acct["streak"] += 1
    else:
        acct["streak"] = 1
    reward = DAILY_BASE + DAILY_STREAK_STEP * min(acct["streak"] - 1, DAILY_STREAK_MAX_STEPS)
    acct["cash"] += reward
    acct["last_daily"] = _now_iso()
    bank_save(data)
    embed = _bank_embed("🎁 المكافأة اليومية", f"أخذت **{fmt(reward)}** {CURRENCY} كاش.")
    embed.add_field(name="🔥 الستريك", value=f"{acct['streak']} يوم", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.set_footer(text="ارجع كل يوم عشان الستريك يكمل وتزيد المكافأة")
    img = await _result_card(interaction.user, "المكافأة اليومية", _money(reward, "+"), C_GREEN, [
        (f"الستريك: {acct['streak']} يوم", C_GOLD),
        (f"الكاش: {_money(acct['cash'])}", C_MUTED)])
    await _out(interaction, panel, embed, img=img)


async def _act_gold(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    img = await _market_card(data, interaction.user, acct)
    await _out(interaction, panel, _gold_embed(data, acct), img=img)


async def _act_buy_gold(interaction, text, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    price = data["_gold"]["price"]
    n = parse_amount(text, acct["cash"] // price)
    if not n:
        if acct["cash"] < price:
            return await _err(interaction, f"❌ كاشك ما يكفي لجرام واحد (السعر **{fmt(price)}** {CURRENCY}).")
        return await _err(interaction, "⚠️ اكتب عدد الجرامات (رقم) أو كلمة `كل`.")
    cost = n * price
    if cost > acct["cash"]:
        return await _err(interaction, f"❌ كاشك ما يكفي. تكلفة {fmt(n)} جرام = **{fmt(cost)}** {CURRENCY} وكاشك **{fmt(acct['cash'])}**.")
    acct["cash"] -= cost
    acct["gold"] += n
    bank_save(data)
    embed = _bank_embed("🪙 تم شراء الذهب",
                        f"اشتريت **{fmt(n)}** جرام بسعر {fmt(price)} للجرام = **{fmt(cost)}** {CURRENCY}.")
    embed.add_field(name="🪙 ذهبك", value=f"{fmt(acct['gold'])} جرام", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    img = await _trade_card(interaction.user, "تم شراء الذهب", [
        ("الكمية", f"{fmt(n)} جرام", None),
        ("سعر الجرام", _money(price), None),
        ("الإجمالي", _money(cost), C_GOLD)],
        f"ذهبك الحين: {fmt(acct['gold'])} جرام - الكاش: {_money(acct['cash'])}")
    await _out(interaction, panel, embed, img=img)


async def _act_sell_gold(interaction, text, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    price = data["_gold"]["price"]
    n = parse_amount(text, acct["gold"])
    if not n:
        if acct["gold"] == 0:
            return await _err(interaction, "❌ ما عندك ذهب تبيعه.")
        return await _err(interaction, "⚠️ اكتب عدد الجرامات (رقم) أو كلمة `كل`.")
    if n > acct["gold"]:
        return await _err(interaction, f"❌ ما عندك كفاية. معك **{fmt(acct['gold'])}** جرام.")
    revenue = int(n * price * (1 - GOLD_SELL_FEE))
    acct["gold"] -= n
    acct["cash"] += revenue
    bank_save(data)
    embed = _bank_embed("🪙 تم بيع الذهب",
                        f"بعت **{fmt(n)}** جرام بسعر {fmt(price)} للجرام (بعد عمولة {GOLD_SELL_FEE * 100:.0f}%) "
                        f"وأخذت **{fmt(revenue)}** {CURRENCY}.")
    embed.add_field(name="🪙 ذهبك", value=f"{fmt(acct['gold'])} جرام", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    img = await _trade_card(interaction.user, "تم بيع الذهب", [
        ("الكمية", f"{fmt(n)} جرام", None),
        ("سعر الجرام", _money(price), None),
        ("المبلغ المستلم", _money(revenue, "+"), C_GREEN)],
        f"ذهبك الحين: {fmt(acct['gold'])} جرام - الكاش: {_money(acct['cash'])}")
    await _out(interaction, panel, embed, img=img)


async def _act_jobs(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    level = _level(acct)
    rows = []
    for name, min_level, low, high, _emoji in BANK_JOBS:
        unlocked = level >= min_level
        if acct.get("job") == name:
            sub, name_color = "وظيفتك الحالية", C_GOLD
        elif unlocked:
            sub, name_color = None, C_TEXT
        else:
            sub, name_color = f"مقفلة - تحتاج مستوى {min_level}", C_MUTED
        rows.append({"ring": f"{min_level}+", "name": name, "name_color": name_color, "name_sub": sub,
                     "value": f"{fmt(low)}-{fmt(high)} {CURRENCY}",
                     "value_color": C_GOLD if unlocked else C_MUTED})
    img = await _board_card("الوظائف", rows,
                            (f"مستواك: {level} - كل {WORK_PER_LEVEL} مرات عمل = مستوى", C_MUTED))
    await _out(interaction, panel, _jobs_embed(acct), img=img)


async def _act_apply_job(interaction, job_name, panel):
    job = _find_job(job_name)
    if job is None:
        return await _err(interaction, "⚠️ ما لقيت هذي الوظيفة.")
    name, min_level, low, high, emoji = job
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    if _level(acct) < min_level:
        return await _err(interaction, f"🔒 وظيفة **{name}** تحتاج مستوى **{min_level}** ومستواك **{_level(acct)}**. اشتغل أكثر بزر ⚒️ عمل.")
    if acct.get("job") == name:
        return await _err(interaction, f"⚠️ أنت أصلًا شغال **{name}**.")
    acct["job"] = name
    bank_save(data)
    embed = _bank_embed("💼 تم التوظيف", f"مبروك! صرت **{emoji} {name}**.\nالراتب: {fmt(low)}–{fmt(high)} {CURRENCY} بالمرة.")
    img = await _result_card(interaction.user, "تم التوظيف", None, C_TEXT, [
        (name, C_GOLD),
        (f"الراتب: {fmt(low)}-{fmt(high)} {CURRENCY}", C_MUTED)])
    await _out(interaction, panel, embed, img=img)


async def _act_quit(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    if not acct.get("job"):
        return await _err(interaction, "⚠️ أنت عاطل أصلًا.")
    old = acct["job"]
    acct["job"] = None
    bank_save(data)
    img = await _result_card(interaction.user, "استقالة", None, C_TEXT, [
        (f"تركت وظيفة {old}", C_GOLD),
        ("مستواك محفوظ", C_MUTED)])
    await _out(interaction, panel, _bank_embed("📝 استقالة", f"تركت وظيفة **{old}**. مستواك محفوظ."), img=img)


async def _act_work(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    job = _find_job(acct["job"]) if acct.get("job") else None
    if job is None:
        return await _err(interaction, "⚠️ ما عندك وظيفة. اضغط 💼 الوظائف واختر وظيفة من القائمة.")
    wait = _cooldown_left(acct["last_work"], WORK_COOLDOWN)
    if wait:
        return await _err(interaction, f"⏳ تعبان! ارجع للشغل بعد **{_fmt_wait(wait)}**.")
    name, _, low, high, emoji = job
    pay = random.randint(low, high)
    bonus = random.random() < WORK_BONUS_CHANCE
    if bonus:
        pay = int(pay * 1.5)
    used_multiplier = False
    if acct["items"].get("multiplier", 0) > 0:
        acct["items"]["multiplier"] -= 1
        pay *= 2
        used_multiplier = True
    old_level = _level(acct)
    acct["cash"] += pay
    acct["works"] += 1
    acct["last_work"] = _now_iso()
    new_level = _level(acct)
    bank_save(data)
    desc = f"اشتغلت **{emoji} {name}** وأخذت **{fmt(pay)}** {CURRENCY} كاش."
    if bonus:
        desc += "\n🎉 جاك مكافأة من المدير (x1.5)!"
    if used_multiplier:
        desc += "\n⚡ استخدمت مضاعف الراتب (x2)."
    embed = _bank_embed("💼 يوم عمل", desc)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.add_field(name="⭐ المستوى", value=str(new_level), inline=True)
    if new_level > old_level:
        embed.add_field(name="🆙 ترقية!", value=f"وصلت مستوى **{new_level}** — شوف 💼 الوظائف للوظايف الجديدة.", inline=False)
    extras = []
    if new_level > old_level:
        extras.append((f"ترقية! وصلت مستوى {new_level}", C_GOLD))
    if bonus:
        extras.append(("مكافأة من المدير x1.5", C_GOLD))
    if used_multiplier:
        extras.append(("مضاعف الراتب x2", C_GOLD))
    if not extras:
        extras.append((f"المستوى {new_level}", C_MUTED))
    img = await _result_card(interaction.user, f"يوم عمل - {name}", _money(pay, "+"), C_GREEN,
                             [(f"الكاش: {_money(acct['cash'])}", C_MUTED), extras[0]])
    await _out(interaction, panel, embed, img=img)


async def _act_crime(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    wait = _cooldown_left(acct["last_crime"], CRIME_COOLDOWN)
    if wait:
        return await _err(interaction, f"⏳ الشرطة تراقبك! حاول بعد **{_fmt_wait(wait)}**.")
    if acct["cash"] < CRIME_MIN_CASH:
        return await _err(interaction, f"❌ لازم يكون معك **{CRIME_MIN_CASH}** {CURRENCY} كاش على الأقل (عشان الغرامة لو انمسكت).")
    acct["last_crime"] = _now_iso()
    if random.random() < CRIME_SUCCESS_CHANCE:
        reward = random.randint(CRIME_REWARD_MIN, CRIME_REWARD_MAX)
        acct["cash"] += reward
        embed = _bank_embed("🦹 نجحت الجريمة", f"نفذت العملية وأخذت **{fmt(reward)}** {CURRENCY} كاش.")
        headline, amount_text, amount_color = "نجحت الجريمة", _money(reward, "+"), C_GREEN
    else:
        fine = min(acct["cash"], max(CRIME_MIN_CASH, int(acct["cash"] * CRIME_FINE_PERCENT)))
        acct["cash"] -= fine
        embed = _bank_embed("🚔 فشلت الجريمة", f"انمسكت ودفعت غرامة **{fmt(fine)}** {CURRENCY}.")
        headline, amount_text, amount_color = "فشلت الجريمة", _money(fine, "-"), C_RED
    bank_save(data)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    img = await _result_card(interaction.user, headline, amount_text, amount_color,
                             [(f"الكاش: {_money(acct['cash'])}", C_MUTED)])
    await _out(interaction, panel, embed, img=img)


async def _act_rob(interaction, member):
    if member.bot or member.id == interaction.user.id:
        return await _err(interaction, "⚠️ ما تقدر تسرق نفسك أو بوت.")
    data = bank_load()
    thief = bank_acct(data, interaction.guild.id, interaction.user.id)
    victim = bank_acct(data, interaction.guild.id, member.id)
    wait = _cooldown_left(thief["last_rob"], ROB_COOLDOWN)
    if wait:
        return await _err(interaction, f"⏳ الشرطة تدور عليك! حاول بعد **{_fmt_wait(wait)}**.")
    if thief["cash"] < ROB_MIN_THIEF_CASH:
        return await _err(interaction, f"❌ لازم يكون معك **{ROB_MIN_THIEF_CASH}** {CURRENCY} كاش على الأقل (عشان الغرامة لو انمسكت).")
    if victim["cash"] < ROB_MIN_VICTIM_CASH:
        return await _err(interaction, f"⚠️ كاش {member.display_name} قليل ما يستاهل السرقة (وفلوس البنك محمية).")
    thief["last_rob"] = _now_iso()

    chance = ROB_SUCCESS_CHANCE
    if thief["items"].get("lockpick", 0) > 0:
        thief["items"]["lockpick"] -= 1
        chance += ROB_LOCKPICK_BONUS

    locked = victim["items"].get("lock", 0) > 0
    if locked:
        victim["items"]["lock"] -= 1

    victim_name = _clean_name(member.display_name)
    if not locked and random.random() < chance:
        stolen = min(ROB_MAX_STEAL, max(1, int(victim["cash"] * random.uniform(0.10, 0.30))))
        victim["cash"] -= stolen
        thief["cash"] += stolen
        thief["robs"] += 1
        thief["stolen"] += stolen
        embed = _bank_embed("🦹 سرقة ناجحة",
                            f"{interaction.user.mention} سرق **{fmt(stolen)}** {CURRENCY} من {member.mention}!")
        headline, amount_text, amount_color = "سرقة ناجحة", _money(stolen, "+"), C_GREEN
    else:
        fine = min(thief["cash"], max(ROB_MIN_THIEF_CASH, int(thief["cash"] * ROB_FINE_PERCENT)))
        thief["cash"] -= fine
        victim["cash"] += fine
        if locked:
            embed = _bank_embed("🔒 القفل صدّ السرقة",
                                f"{interaction.user.mention} حاول يسرق {member.mention} بس القفل صدّه، ودفع غرامة **{fmt(fine)}** {CURRENCY} للضحية.")
            headline = "القفل صدّ السرقة"
        else:
            embed = _bank_embed("🚔 انمسكت!",
                                f"{interaction.user.mention} حاول يسرق {member.mention} وانمسك، ودفع غرامة **{fmt(fine)}** {CURRENCY} للضحية.")
            headline = "انمسكت!"
        amount_text, amount_color = _money(fine, "-"), C_RED
    bank_save(data)
    embed.set_footer(text="تنبيه: حط فلوسك بالبنك عشان ما تنسرق")
    img = await _result_card(interaction.user, headline, amount_text, amount_color, [
        (f"الضحية: {victim_name}", C_MUTED),
        (f"الكاش: {_money(thief['cash'])}", C_MUTED)])
    await _out(interaction, None, embed, content=member.mention, ping=member, img=img)


async def _act_rich(interaction, panel):
    data = bank_load()
    price = data["_gold"]["price"]
    stock_prices = data["_stocks"]["prices"]
    rows = []
    for uid, acct in data.get(str(interaction.guild.id), {}).items():
        if not uid.isdigit() or not isinstance(acct, dict):
            continue
        member = interaction.guild.get_member(int(uid))
        if member is None or member.bot:
            continue
        rows.append((member, _net_worth(acct, price, stock_prices)))
    rows.sort(key=lambda r: r[1], reverse=True)
    if not rows:
        return await _err(interaction, "📉 ما فيه حسابات بنكية لين الحين.")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, worth) in enumerate(rows[:10]):
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{rank} {member.mention} — **{fmt(worth)}** {CURRENCY}")
    board = [{"member": member, "ring": member.display_name[:1], "name": _clean_name(member.display_name),
              "value": _money(worth)} for member, worth in rows[:10]]
    img = await _board_card("أغنى الأعضاء", board)
    await _out(interaction, panel, _bank_embed("💎 أغنى الأعضاء", "\n".join(lines)), img=img)


async def _act_thieves(interaction, panel):
    data = bank_load()
    rows = []
    for uid, acct in data.get(str(interaction.guild.id), {}).items():
        if not uid.isdigit() or not isinstance(acct, dict) or acct.get("robs", 0) <= 0:
            continue
        member = interaction.guild.get_member(int(uid))
        if member is None or member.bot:
            continue
        rows.append((member, acct["robs"], acct.get("stolen", 0)))
    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    if not rows:
        return await _err(interaction, "🕵️ ما فيه حرامية لين الحين، ما أحد سرق بنجاح.")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, robs, stolen) in enumerate(rows[:10]):
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{rank} {member.mention} — **{fmt(robs)}** سرقة ({fmt(stolen)} {CURRENCY})")
    board = [{"member": member, "ring": member.display_name[:1], "name": _clean_name(member.display_name),
              "value": f"{fmt(robs)} سرقة", "value_sub": _money(stolen)} for member, robs, stolen in rows[:10]]
    img = await _board_card("توب الحرامية", board)
    await _out(interaction, panel, _bank_embed("🕵️ توب الحرامية", "\n".join(lines)), img=img)


async def _act_items(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    await _out(interaction, panel, _items_embed(acct))


async def _act_buy_item(interaction, key):
    if key not in SHOP_ITEMS:
        return await _err(interaction, "⚠️ ما لقيت هذا الغرض.")
    name, emoji, price, _desc = SHOP_ITEMS[key]
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    if acct["cash"] < price:
        return await _err(interaction, f"❌ كاشك ما يكفي. {name} بـ **{fmt(price)}** {CURRENCY} وكاشك **{fmt(acct['cash'])}**.")
    acct["cash"] -= price
    if key == "chest":
        reward = _open_chest()
        acct["cash"] += reward
        embed = _bank_embed("🎁 صندوق المفاجأة", f"فتحت الصندوق وطلع فيه **{fmt(reward)}** {CURRENCY}!")
    else:
        acct["items"][key] = acct["items"].get(key, 0) + 1
        embed = _bank_embed("🛍️ تم الشراء", f"اشتريت **{emoji} {name}** بـ {fmt(price)} {CURRENCY}.")
    bank_save(data)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    await interaction.response.edit_message(embed=embed, view=ShopView(interaction.user.id))


# ---------- الاستثمار (أسهم شركات عالمية) ----------
async def _stocks_card(data: dict, acct: dict):
    prices = data["_stocks"]["prices"]
    history = data["_stocks"]["history"]
    rows = []
    for sym, (name, _base, _vol) in STOCKS.items():
        pct = _pct_change(history.get(sym, []))
        if pct is None or round(pct, 1) == 0:
            trend, trend_color = "ثابت", C_MUTED
        else:
            trend, trend_color = f"{pct:+.1f}%", (C_GREEN if pct > 0 else C_RED)
        owned = acct["stocks"].get(sym, {}).get("shares", 0)
        rows.append({"ring": sym, "ring_size": 15, "name": name,
                     "name_sub": f"عندك {fmt(owned)} سهم" if owned else None,
                     "value": _money(prices[sym]), "value_sub": trend, "value_sub_color": trend_color})
    return await _board_card("سوق الأسهم", rows,
                             (f"الأسعار تتغير كل {STOCK_STEP_SECONDS // 60} دقيقة", C_MUTED))


async def _portfolio_card(data: dict, acct: dict):
    rows, total_pnl = [], 0
    for sym, name, shares, _cost, value, pnl in _holdings(acct, data["_stocks"]["prices"]):
        total_pnl += pnl
        sign = "+" if pnl > 0 else ("-" if pnl < 0 else "")
        pnl_color = C_GREEN if pnl > 0 else (C_RED if pnl < 0 else C_MUTED)
        rows.append({"ring": sym, "ring_size": 15, "name": name, "name_sub": f"{fmt(shares)} سهم",
                     "value": _money(value), "value_sub": f"{sign}{fmt(abs(pnl))} {CURRENCY}",
                     "value_sub_color": pnl_color})
    sign = "+" if total_pnl > 0 else ("-" if total_pnl < 0 else "")
    color = C_GREEN if total_pnl > 0 else (C_RED if total_pnl < 0 else C_MUTED)
    return await _board_card("محفظتي", rows, (f"إجمالي الربح والخسارة: {sign}{fmt(abs(total_pnl))} {CURRENCY}", color))


async def _act_invest_open(interaction, owner_id):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    bank_save(data)
    img = await _stocks_card(data, acct)
    kwargs = {"view": InvestView(owner_id), "ephemeral": True}
    if img is not None:
        kwargs["file"] = _make_file(img)
    else:
        kwargs["embed"] = _stocks_embed(data, acct)
    await interaction.response.send_message(**kwargs)


async def _act_stocks_list(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    img = await _stocks_card(data, acct)
    await _out(interaction, panel, _stocks_embed(data, acct), img=img)


async def _act_portfolio(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    if not _holdings(acct, data["_stocks"]["prices"]):
        return await _err(interaction, "📊 ما عندك أسهم لين الحين. اشتر من القائمة اللي فوق.")
    img = await _portfolio_card(data, acct)
    await _out(interaction, panel, _portfolio_embed(data, acct), img=img)


async def _act_buy_stock(interaction, sym, text, panel):
    if sym not in STOCKS:
        return await _err(interaction, "⚠️ ما لقيت هذي الشركة.")
    name = STOCKS[sym][0]
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    price = data["_stocks"]["prices"][sym]
    n = parse_amount(text, acct["cash"] // price)
    if not n:
        if acct["cash"] < price:
            return await _err(interaction, f"❌ كاشك ما يكفي لسهم واحد (سعر سهم {name} **{fmt(price)}** {CURRENCY}).")
        return await _err(interaction, "⚠️ اكتب عدد الأسهم (رقم) أو كلمة `كل`.")
    cost = n * price
    if cost > acct["cash"]:
        return await _err(interaction, f"❌ كاشك ما يكفي. تكلفة {fmt(n)} سهم = **{fmt(cost)}** {CURRENCY} وكاشك **{fmt(acct['cash'])}**.")
    holding = acct["stocks"].setdefault(sym, {"shares": 0, "cost": 0})
    holding["shares"] += n
    holding["cost"] += cost
    acct["cash"] -= cost
    bank_save(data)
    embed = _bank_embed(f"📊 تم شراء أسهم {name}",
                        f"اشتريت **{fmt(n)}** سهم بسعر {fmt(price)} للسهم = **{fmt(cost)}** {CURRENCY}.")
    embed.add_field(name="📊 أسهمك", value=f"{fmt(holding['shares'])} سهم", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    img = await _result_card(interaction.user, f"شراء أسهم {name}", _money(cost), C_GOLD, [
        (f"{fmt(n)} سهم بسعر {_money(price)}", C_MUTED),
        (f"الكاش: {_money(acct['cash'])}", C_MUTED)])
    await _out(interaction, panel, embed, img=img)


async def _act_sell_stock(interaction, sym, text, panel):
    if sym not in STOCKS:
        return await _err(interaction, "⚠️ ما لقيت هذي الشركة.")
    name = STOCKS[sym][0]
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    holding = acct["stocks"].get(sym)
    shares = holding["shares"] if isinstance(holding, dict) else 0
    n = parse_amount(text, shares)
    if not n:
        if shares == 0:
            return await _err(interaction, f"❌ ما عندك أسهم في {name}.")
        return await _err(interaction, "⚠️ اكتب عدد الأسهم (رقم) أو كلمة `كل`.")
    if n > shares:
        return await _err(interaction, f"❌ ما عندك كفاية. معك **{fmt(shares)}** سهم في {name}.")
    price = data["_stocks"]["prices"][sym]
    revenue = int(n * price * (1 - STOCK_SELL_FEE))
    cost_part = round(holding["cost"] * n / shares)
    pnl = revenue - cost_part
    holding["shares"] -= n
    holding["cost"] -= cost_part
    if holding["shares"] <= 0:
        del acct["stocks"][sym]
    acct["cash"] += revenue
    bank_save(data)
    sign = "+" if pnl > 0 else ("-" if pnl < 0 else "")
    embed = _bank_embed(f"📊 تم بيع أسهم {name}",
                        f"بعت **{fmt(n)}** سهم بسعر {fmt(price)} للسهم (بعد عمولة {STOCK_SELL_FEE * 100:.0f}%) "
                        f"وأخذت **{fmt(revenue)}** {CURRENCY}.")
    embed.add_field(name="الربح / الخسارة", value=f"{sign}{fmt(abs(pnl))} {CURRENCY}", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    pnl_color = C_GREEN if pnl > 0 else (C_RED if pnl < 0 else C_GOLD)
    img = await _result_card(interaction.user, f"بيع أسهم {name}", _money(abs(pnl), sign), pnl_color, [
        (f"المبلغ المستلم: {_money(revenue)}", C_MUTED),
        (f"الكاش: {_money(acct['cash'])}", C_MUTED)])
    await _out(interaction, panel, embed, img=img)


# ============================================================
# مودال المبلغ (نافذة صغيرة تكتب فيها الرقم)
# ============================================================
class AmountModal(discord.ui.Modal):
    def __init__(self, title: str, label: str, handler, panel=None):
        super().__init__(title=title)
        self.handler = handler
        self.panel = panel
        self.amount = discord.ui.TextInput(label=label, placeholder="مثال: 500 أو كل", max_length=15, required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        await self.handler(interaction, str(self.amount.value), self.panel)


# ---------- اختيار عضو (للحوالة والسرقة) ----------
class TransferSelectView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="اختر العضو اللي تحول له", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        if member.bot or member.id == interaction.user.id:
            return await _err(interaction, "⚠️ ما تقدر تحول لنفسك أو لبوت.")

        async def handler(inter, text, _panel):
            await _act_transfer(inter, member, text)

        await interaction.response.send_modal(
            AmountModal(f"حوالة إلى {member.display_name}"[:45], "المبلغ (من رصيد البنك)", handler))


class RobSelectView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="اختر الضحية", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        await _act_rob(interaction, select.values[0])


# ---------- قائمة الوظائف (للتوظف) ----------
class JobSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=name, value=name, emoji=emoji,
                                 description=f"مستوى {lvl}+ • {low}–{high} {CURRENCY}")
            for name, lvl, low, high, emoji in BANK_JOBS
        ]
        super().__init__(placeholder="💼 اختر وظيفة للتوظف", options=options, min_values=1, max_values=1, row=3)

    async def callback(self, interaction: discord.Interaction):
        await _act_apply_job(interaction, self.values[0], self.view)


# ---------- المتجر ----------
class ShopSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=f"{name} — {fmt(price)} {CURRENCY}", value=key, emoji=emoji,
                                 description=desc[:100])
            for key, (name, emoji, price, desc) in SHOP_ITEMS.items()
        ]
        super().__init__(placeholder="🛍️ اختر غرض للشراء", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await _act_buy_item(interaction, self.values[0])


class ShopView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.add_item(ShopSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⚠️ هذا المتجر مو لك، اكتب `بنك` وتطلع لك لوحتك.", ephemeral=True)
            return False
        return True


# ---------- الاستثمار ----------
class StockSelect(discord.ui.Select):
    """قائمة الشركات: mode = buy أو sell."""

    def __init__(self, mode: str, row: int):
        options = [discord.SelectOption(label=name, value=sym, description=sym)
                   for sym, (name, _base, _vol) in STOCKS.items()]
        placeholder = "📈 اشتر أسهم من شركة" if mode == "buy" else "📉 بيع أسهم من شركة"
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1, row=row)
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        sym = self.values[0]
        name = STOCKS[sym][0]
        mode = self.mode

        async def handler(inter, text, panel):
            if mode == "buy":
                await _act_buy_stock(inter, sym, text, panel)
            else:
                await _act_sell_stock(inter, sym, text, panel)

        title = f"شراء أسهم {name}" if mode == "buy" else f"بيع أسهم {name}"
        await interaction.response.send_modal(AmountModal(title[:45], "عدد الأسهم (أو كل)", handler, self.view))


class InvestView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.add_item(StockSelect("buy", 0))
        self.add_item(StockSelect("sell", 1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⚠️ هذي القائمة مو لك، اضغط 💹 استثمار من لوحتك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="الشركات", emoji="📊", style=discord.ButtonStyle.secondary, row=2)
    async def b_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_stocks_list(interaction, self)

    @discord.ui.button(label="محفظتي", emoji="💼", style=discord.ButtonStyle.secondary, row=2)
    async def b_portfolio(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_portfolio(interaction, self)


# ---------- اللوحة الرئيسية (كل الأزرار بلون رمادي طبيعي) ----------
class BankPanel(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.message: discord.Message | None = None
        self.add_item(JobSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⚠️ هذي اللوحة مو لك، اكتب `بنك` وتطلع لك لوحتك.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    # ----- صف 1: الحساب والبنك -----
    @discord.ui.button(label="حسابي", emoji="🏦", style=discord.ButtonStyle.secondary, row=0)
    async def b_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_account(interaction, self)

    @discord.ui.button(label="إيداع", emoji="💰", style=discord.ButtonStyle.secondary, row=0)
    async def b_deposit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AmountModal("إيداع", "المبلغ (أو كل)", _act_deposit, self))

    @discord.ui.button(label="سحب", emoji="💸", style=discord.ButtonStyle.secondary, row=0)
    async def b_withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AmountModal("سحب", "المبلغ (أو كل)", _act_withdraw, self))

    @discord.ui.button(label="حوالة", emoji="📤", style=discord.ButtonStyle.secondary, row=0)
    async def b_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر العضو اللي تبي تحول له:",
                                                view=TransferSelectView(self.owner_id), ephemeral=True)

    @discord.ui.button(label="فائدة", emoji="📈", style=discord.ButtonStyle.secondary, row=0)
    async def b_interest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_interest(interaction, self)

    # ----- صف 2: الذهب واليومي والأغنياء -----
    @discord.ui.button(label="سوق الذهب", emoji="🪙", style=discord.ButtonStyle.secondary, row=1)
    async def b_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_gold(interaction, self)

    @discord.ui.button(label="شراء ذهب", emoji="🛒", style=discord.ButtonStyle.secondary, row=1)
    async def b_buy_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AmountModal("شراء ذهب", "عدد الجرامات (أو كل)", _act_buy_gold, self))

    @discord.ui.button(label="بيع ذهب", emoji="💱", style=discord.ButtonStyle.secondary, row=1)
    async def b_sell_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AmountModal("بيع ذهب", "عدد الجرامات (أو كل)", _act_sell_gold, self))

    @discord.ui.button(label="الأغنياء", emoji="🏆", style=discord.ButtonStyle.secondary, row=1)
    async def b_rich(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_rich(interaction, self)

    @discord.ui.button(label="يومي", emoji="🎁", style=discord.ButtonStyle.secondary, row=1)
    async def b_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_daily(interaction, self)

    # ----- صف 3: الوظائف والجريمة والسرقة -----
    @discord.ui.button(label="الوظائف", emoji="💼", style=discord.ButtonStyle.secondary, row=2)
    async def b_jobs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_jobs(interaction, self)

    @discord.ui.button(label="عمل", emoji="⚒️", style=discord.ButtonStyle.secondary, row=2)
    async def b_work(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_work(interaction, self)

    @discord.ui.button(label="استقالة", emoji="📝", style=discord.ButtonStyle.secondary, row=2)
    async def b_quit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_quit(interaction, self)

    @discord.ui.button(label="جريمة", emoji="🦹", style=discord.ButtonStyle.secondary, row=2)
    async def b_crime(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_crime(interaction, self)

    @discord.ui.button(label="سرقة", emoji="🥷", style=discord.ButtonStyle.secondary, row=2)
    async def b_rob(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر الضحية:", view=RobSelectView(self.owner_id), ephemeral=True)

    # ----- صف 5: المتجر والأغراض وتوب حرامية واستثمار (صف 4 للقائمة المنسدلة للوظائف) -----
    @discord.ui.button(label="المتجر", emoji="🛍️", style=discord.ButtonStyle.secondary, row=4)
    async def b_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = bank_load()
        acct = bank_acct(data, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=_shop_embed(acct), view=ShopView(self.owner_id), ephemeral=True)

    @discord.ui.button(label="أغراضي", emoji="🎒", style=discord.ButtonStyle.secondary, row=4)
    async def b_items(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_items(interaction, self)

    @discord.ui.button(label="توب حرامية", emoji="🕵️", style=discord.ButtonStyle.secondary, row=4)
    async def b_thieves(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_thieves(interaction, self)

    @discord.ui.button(label="استثمار", emoji="💹", style=discord.ButtonStyle.secondary, row=4)
    async def b_invest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_invest_open(interaction, self.owner_id)


async def _wrong_channel(message: discord.Message) -> None:
    bank_ch = find_bank_channel(message.guild)
    where = f" {bank_ch.mention}" if bank_ch else ""
    await message.channel.send(
        f"{message.author.mention} ❌ مايمديك تستخدم البنك في هذا الروم، فقط في روم البنك{where}",
        delete_after=8,
        allowed_mentions=discord.AllowedMentions(users=[message.author]))


async def open_bank_panel(message: discord.Message) -> None:
    """يفتح لوحة الأزرار لما أحد يكتب "بنك". خارج روم البنك يرد بالتنبيه."""
    if not _in_bank_channel(message.channel, message.guild):
        await _wrong_channel(message)
        return
    data = bank_load()
    acct = bank_acct(data, message.guild.id, message.author.id)
    bank_save(data)
    panel = BankPanel(message.author.id)
    img = await _account_card(data, message.author, acct)
    if img is not None:
        msg = await message.channel.send(file=_make_file(img), view=panel,
                                         allowed_mentions=discord.AllowedMentions.none())
    else:
        msg = await message.channel.send(embed=_account_embed(data, message.author, acct), view=panel,
                                         allowed_mentions=discord.AllowedMentions.none())
    panel.message = msg


async def show_member_account(message: discord.Message, member: discord.Member) -> None:
    """"بنك @عضو" — يطلع حساب العضو (كم معه كاش وبنك وذهب ووظيفته). ما ينشئ له حساب لو ما عنده."""
    if not _in_bank_channel(message.channel, message.guild):
        await _wrong_channel(message)
        return
    if member.bot:
        await message.channel.send("⚠️ البوتات ما عندها حساب بنكي.")
        return
    data = bank_load()
    acct = bank_acct(data, message.guild.id, member.id)
    img = await _account_card(data, member, acct)
    if img is not None:
        await message.channel.send(file=_make_file(img), allowed_mentions=discord.AllowedMentions.none())
    else:
        await message.channel.send(embed=_account_embed(data, member, acct),
                                   allowed_mentions=discord.AllowedMentions.none())


# ============================================================
# أوامر الإدارة الخاصة بالبنك — بدون بريفكس (Admin وفوق)
# ============================================================
# كل دالة ترجع:
#   True  ← نجح الأمر (رياكشن ✅)
#   False ← فشل الأمر (رياكشن ❌)
#   None  ← كتب الأمر غلط وانرسل له مثال (بدون رياكشن)
async def cmd_bank_add(message: discord.Message, args: str):
    """بنك_اضافة @عضو <مبلغ> ← يضيف كاش لحساب عضو بالبنك."""
    if not message.mentions:
        await usage_error(message, "بنك_اضافة @العضو 500")
        return None
    target = message.mentions[0]
    amount = parse_amount(strip_mentions(args, message.mentions))
    if target.bot or not amount:
        await usage_error(message, "بنك_اضافة @العضو 500")
        return None
    data = bank_load()
    acct = bank_acct(data, message.guild.id, target.id)
    acct["cash"] += amount
    bank_save(data)
    await log_mod_action(message.guild, "🏦 إضافة رصيد بنكي", message.author, target, None,
                         {"المبلغ": f"{fmt(amount)} {CURRENCY}"})
    return True


async def cmd_bank_remove(message: discord.Message, args: str):
    """بنك_خصم @عضو <مبلغ> ← يخصم من كاش العضو أولًا ثم من رصيده بالبنك (ما ينزل تحت صفر)."""
    if not message.mentions:
        await usage_error(message, "بنك_خصم @العضو 500")
        return None
    target = message.mentions[0]
    amount = parse_amount(strip_mentions(args, message.mentions))
    if target.bot or not amount:
        await usage_error(message, "بنك_خصم @العضو 500")
        return None
    data = bank_load()
    acct = bank_acct(data, message.guild.id, target.id)
    from_cash = min(acct["cash"], amount)
    acct["cash"] -= from_cash
    from_bank = min(acct["bank"], amount - from_cash)
    acct["bank"] -= from_bank
    taken = from_cash + from_bank
    bank_save(data)
    await log_mod_action(message.guild, "🏦 خصم رصيد بنكي", message.author, target, None,
                         {"المبلغ": f"{fmt(taken)} {CURRENCY}",
                          "كاش": fmt(from_cash), "بنك": fmt(from_bank)})
    return True


BANK_ADMIN_COMMANDS = {
    "بنك_اضافة": (ADMIN_ROLES, cmd_bank_add),
    "بنك_اضافه": (ADMIN_ROLES, cmd_bank_add),
    "بنك_إضافة": (ADMIN_ROLES, cmd_bank_add),
    "بنك_إضافه": (ADMIN_ROLES, cmd_bank_add),
    "بنك_خصم": (ADMIN_ROLES, cmd_bank_remove),
}
SORTED_TRIGGERS = sorted(BANK_ADMIN_COMMANDS.keys(), key=len, reverse=True)


async def try_dispatch_admin_command(message: discord.Message) -> bool:
    content = message.content.strip()
    for trigger in SORTED_TRIGGERS:
        if content == trigger or content.startswith(trigger + " "):
            allowed_roles, handler = BANK_ADMIN_COMMANDS[trigger]

            # ما عنده صلاحية ← رياكشن ❌ بدون أي رد
            if not isinstance(message.author, discord.Member) or not has_role(message.author, allowed_roles):
                await react(message, "❌")
                return True

            args = content[len(trigger):].strip()
            try:
                result = await handler(message, args)
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"[بنك] فشل تنفيذ '{trigger}': {e}")
                result = False

            if result is True:
                await react(message, "✅")
            elif result is False:
                await react(message, "❌")
            return True
    return False


# ============================================================
# الربط مع بوت الكنترول
# ============================================================
async def try_dispatch_bank_admin(message: discord.Message) -> bool:
    """يرجع True لو الرسالة كانت "بنك" (لوحة الأزرار) أو "بنك @عضو" أو أمر إدارة بنك وتم التعامل معها."""
    if message.author.bot or message.guild is None:
        return False
    content = message.content.strip()
    if content == "بنك":
        await open_bank_panel(message)
        return True
    if content.split(None, 1)[:1] == ["بنك"] and message.mentions:
        await show_member_account(message, message.mentions[0])
        return True
    return await try_dispatch_admin_command(message)


async def handle_bank_channel_error(ctx: commands.Context) -> None:
    """رسالة التنبيه لما أمر بنك ينكتب بغير روم البنك."""
    bank_ch = find_bank_channel(ctx.guild) if ctx.guild else None
    if bank_ch is not None:
        await ctx.send(f"{ctx.author.mention} ❌ مايمديك تستخدم البنك في هذا الروم، فقط في روم البنك {bank_ch.mention}",
                       delete_after=8)


def setup_bank(bot: commands.Bot) -> None:
    """البنك كله بالأزرار (ما فيه أوامر بنقطة). لو أضفت أمر بنقطة بالمستقبل يتسجل هنا تلقائيًا."""
    added = 0
    for obj in list(globals().values()):
        if isinstance(obj, commands.Command):
            try:
                bot.add_command(obj)
                added += 1
            except commands.CommandRegistrationError as e:
                print(f"[بنك] ⚠️ تخطيت أمر مكرر: {e}")
    print(f"[بنك] ✅ تم تحميل نظام البنك (لوحة أزرار + {added} أمر)")
    problems = _images_report()
    if problems:
        print("[بنك] ⚠️ الصور مو جاهزة، البنك بيرد بالنص لين تنحل:")
        for problem in problems:
            print(f"[بنك]    - {problem}")
    else:
        print("[بنك] 🖼️ صور البنك جاهزة")
