"""
bank.py — نظام البنك (وحدة داخل بوت الكنترول bot.py)
====================================================
كل شي بالأزرار: اكتب "بنك" في روم البنك وتطلع لك لوحة الأزرار (حساب، إيداع/سحب/حوالة/فائدة، الذهب،
الوظائف والعمل، يومي بستريك، جريمة، سرقة، المتجر، الأغنياء).
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
  - صور اختيارية من مجلد bank_images (لو الملف موجود يطلع، ولو لا يطلع بدونه):
      work.png / crime_win.png / crime_fail.png / rob_win.png / rob_fail.png
  - مستقلة بالكامل: ما تستورد شي من bot.py (ما فيه استيراد دائري).
"""

import json
import os
import random
import re
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands


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
# الأقسام: حساب + بنك (إيداع/سحب/حوالة/فائدة) + ذهب (سعر متغير) + وظائف + يومي + جريمة + سرقة + متجر + أغنياء.
BANK_FILE = "bank.json"
BANK_CHANNEL_ID = 1539151569826877450
BANK_CHANNEL_NAMES = ["bank"]
CURRENCY = "ريال"

# لون الـ embed (نفس لون هوية السيرفر #394047) — كل رسائل البنك بنفس اللون
BANK_COLOR = discord.Color.from_rgb(57, 64, 71)

# مجلد صور البنك (اختياري — لو الصورة مو موجودة تطلع الرسالة بدونها)
BANK_IMAGES_DIR = "bank_images"

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


def bank_load() -> dict:
    """يقرأ ملف البنك ويحدّث سعر الذهب (ويحفظه فورًا لو تغير، عشان الكل يشوف نفس السعر)."""
    data = load_json(BANK_FILE)
    if _gold_advance(data):
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
    if not isinstance(acct.get("items"), dict):
        acct["items"] = {}
    return acct


def _level(acct: dict) -> int:
    return acct.get("works", 0) // WORK_PER_LEVEL + 1


def _net_worth(acct: dict, gold_price: int) -> int:
    return acct.get("cash", 0) + acct.get("bank", 0) + acct.get("gold", 0) * gold_price


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


def _banner(embed: discord.Embed, filename: str) -> discord.File | None:
    """لو صورة البنر موجودة بمجلد bank_images تنحط بالـ embed. لو مو موجودة يرجع None وتطلع الرسالة بدونها."""
    path = os.path.join(BANK_IMAGES_DIR, filename)
    if not os.path.exists(path):
        return None
    embed.set_image(url=f"attachment://{filename}")
    return discord.File(path, filename=filename)


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


# ============================================================
# الـ embeds
# ============================================================
def _account_embed(data: dict, member: discord.abc.User, acct: dict) -> discord.Embed:
    price = data["_gold"]["price"]
    embed = _bank_embed(f"🏦 حساب {member.display_name}")
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="💵 الكاش", value=f"{fmt(acct['cash'])} {CURRENCY}", inline=True)
    embed.add_field(name="🏦 البنك", value=f"{fmt(acct['bank'])} {CURRENCY}", inline=True)
    embed.add_field(name="🪙 الذهب",
                    value=f"{fmt(acct['gold'])} جرام (≈ {fmt(acct['gold'] * price)} {CURRENCY})", inline=True)
    job = _find_job(acct["job"]) if acct.get("job") else None
    job_text = f"{job[4]} {job[0]} • مستوى {_level(acct)}" if job else f"عاطل • مستوى {_level(acct)}"
    embed.add_field(name="💼 الوظيفة", value=job_text, inline=True)
    embed.add_field(name="💎 صافي الثروة", value=f"{fmt(_net_worth(acct, price))} {CURRENCY}", inline=True)
    if acct.get("streak", 0) > 0:
        embed.add_field(name="🔥 ستريك اليومي", value=f"{acct['streak']} يوم", inline=True)
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


async def _err(interaction: discord.Interaction, text: str) -> None:
    await interaction.response.send_message(text, ephemeral=True)


async def _out(interaction: discord.Interaction, panel, embed: discord.Embed,
               content: str | None = None, ping=None, file: discord.File | None = None) -> None:
    """لو فيه لوحة: يعدّل رسالة اللوحة. لو لا: يرسل رسالة عامة (للحوالة والسرقة)."""
    if panel is not None:
        await interaction.response.edit_message(embed=embed, view=panel, attachments=[file] if file else [])
    else:
        mentions = discord.AllowedMentions(users=[ping]) if ping is not None else discord.AllowedMentions.none()
        kwargs = {"embed": embed, "allowed_mentions": mentions}
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
    await _out(interaction, panel, _account_embed(data, interaction.user, acct))


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
    await _out(interaction, panel, embed)


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
    await _out(interaction, panel, embed)


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
    await _out(interaction, None, embed, content=member.mention, ping=member)


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
    await _out(interaction, panel, embed)


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
    await _out(interaction, panel, embed)


async def _act_gold(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    await _out(interaction, panel, _gold_embed(data, acct))


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
    await _out(interaction, panel, embed)


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
    await _out(interaction, panel, embed)


async def _act_jobs(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    await _out(interaction, panel, _jobs_embed(acct))


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
    await _out(interaction, panel, embed)


async def _act_quit(interaction, panel):
    data = bank_load()
    acct = bank_acct(data, interaction.guild.id, interaction.user.id)
    if not acct.get("job"):
        return await _err(interaction, "⚠️ أنت عاطل أصلًا.")
    old = acct["job"]
    acct["job"] = None
    bank_save(data)
    await _out(interaction, panel, _bank_embed("📝 استقالة", f"تركت وظيفة **{old}**. مستواك محفوظ."))


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
    file = _banner(embed, "work.png")
    await _out(interaction, panel, embed, file=file)


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
        banner = "crime_win.png"
    else:
        fine = min(acct["cash"], max(CRIME_MIN_CASH, int(acct["cash"] * CRIME_FINE_PERCENT)))
        acct["cash"] -= fine
        embed = _bank_embed("🚔 فشلت الجريمة", f"انمسكت ودفعت غرامة **{fmt(fine)}** {CURRENCY}.")
        banner = "crime_fail.png"
    bank_save(data)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    file = _banner(embed, banner)
    await _out(interaction, panel, embed, file=file)


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

    if not locked and random.random() < chance:
        stolen = min(ROB_MAX_STEAL, max(1, int(victim["cash"] * random.uniform(0.10, 0.30))))
        victim["cash"] -= stolen
        thief["cash"] += stolen
        embed = _bank_embed("🦹 سرقة ناجحة",
                            f"{interaction.user.mention} سرق **{fmt(stolen)}** {CURRENCY} من {member.mention}!")
        banner = "rob_win.png"
    else:
        fine = min(thief["cash"], max(ROB_MIN_THIEF_CASH, int(thief["cash"] * ROB_FINE_PERCENT)))
        thief["cash"] -= fine
        victim["cash"] += fine
        if locked:
            embed = _bank_embed("🔒 القفل صدّ السرقة",
                                f"{interaction.user.mention} حاول يسرق {member.mention} بس القفل صدّه، ودفع غرامة **{fmt(fine)}** {CURRENCY} للضحية.")
        else:
            embed = _bank_embed("🚔 انمسكت!",
                                f"{interaction.user.mention} حاول يسرق {member.mention} وانمسك، ودفع غرامة **{fmt(fine)}** {CURRENCY} للضحية.")
        banner = "rob_fail.png"
    bank_save(data)
    embed.set_footer(text="تنبيه: حط فلوسك بالبنك عشان ما تنسرق")
    file = _banner(embed, banner)
    await _out(interaction, None, embed, content=member.mention, ping=member, file=file)


async def _act_rich(interaction, panel):
    data = bank_load()
    price = data["_gold"]["price"]
    rows = []
    for uid, acct in data.get(str(interaction.guild.id), {}).items():
        if not uid.isdigit() or not isinstance(acct, dict):
            continue
        member = interaction.guild.get_member(int(uid))
        if member is None or member.bot:
            continue
        rows.append((member, _net_worth(acct, price)))
    rows.sort(key=lambda r: r[1], reverse=True)
    if not rows:
        return await _err(interaction, "📉 ما فيه حسابات بنكية لين الحين.")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, worth) in enumerate(rows[:10]):
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{rank} {member.mention} — **{fmt(worth)}** {CURRENCY}")
    await _out(interaction, panel, _bank_embed("💎 أغنى الأعضاء", "\n".join(lines)))


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

    # ----- صف 5: المتجر والأغراض (صف 4 للقائمة المنسدلة للوظائف) -----
    @discord.ui.button(label="المتجر", emoji="🛍️", style=discord.ButtonStyle.secondary, row=4)
    async def b_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = bank_load()
        acct = bank_acct(data, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=_shop_embed(acct), view=ShopView(self.owner_id), ephemeral=True)

    @discord.ui.button(label="أغراضي", emoji="🎒", style=discord.ButtonStyle.secondary, row=4)
    async def b_items(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _act_items(interaction, self)


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
    await message.channel.send(embed=_account_embed(data, member, acct),
                               allowed_mentions=discord.AllowedMentions.none())


# ============================================================
# أوامر الإدارة الخاصة بالبنك — بدون بريفكس (Admin وفوق)
# ============================================================
async def cmd_bank_add(message: discord.Message, args: str):
    """بنك_اضافة @عضو <مبلغ> ← يضيف كاش لحساب عضو بالبنك."""
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `بنك_اضافة @العضو المبلغ`")
        return
    target = message.mentions[0]
    amount = parse_amount(strip_mentions(args, message.mentions))
    if target.bot or not amount:
        await reply(message, "⚠️ الصيغة: `بنك_اضافة @العضو المبلغ` (المبلغ رقم أكبر من صفر).")
        return
    data = bank_load()
    acct = bank_acct(data, message.guild.id, target.id)
    acct["cash"] += amount
    bank_save(data)
    await reply(message, f"✅ تمت إضافة **{fmt(amount)}** {CURRENCY} كاش لـ {target.mention}.")
    await log_mod_action(message.guild, "🏦 إضافة رصيد بنكي", message.author, target, None,
                         {"المبلغ": f"{fmt(amount)} {CURRENCY}"})


async def cmd_bank_remove(message: discord.Message, args: str):
    """بنك_خصم @عضو <مبلغ> ← يخصم من كاش العضو أولًا ثم من رصيده بالبنك (ما ينزل تحت صفر)."""
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `بنك_خصم @العضو المبلغ`")
        return
    target = message.mentions[0]
    amount = parse_amount(strip_mentions(args, message.mentions))
    if target.bot or not amount:
        await reply(message, "⚠️ الصيغة: `بنك_خصم @العضو المبلغ` (المبلغ رقم أكبر من صفر).")
        return
    data = bank_load()
    acct = bank_acct(data, message.guild.id, target.id)
    from_cash = min(acct["cash"], amount)
    acct["cash"] -= from_cash
    from_bank = min(acct["bank"], amount - from_cash)
    acct["bank"] -= from_bank
    taken = from_cash + from_bank
    bank_save(data)
    await reply(message, f"✅ تم خصم **{fmt(taken)}** {CURRENCY} من {target.mention} "
                         f"(كاش: {fmt(from_cash)} • بنك: {fmt(from_bank)}).")
    await log_mod_action(message.guild, "🏦 خصم رصيد بنكي", message.author, target, None,
                         {"المبلغ": f"{fmt(taken)} {CURRENCY}"})


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
            if not isinstance(message.author, discord.Member) or not has_role(message.author, allowed_roles):
                await reply(message, f"{message.author.mention} ❌ ما عندك صلاحية لهذا الأمر.")
                return True
            args = content[len(trigger):].strip()
            await handler(message, args)
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
