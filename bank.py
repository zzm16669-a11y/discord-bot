"""
bank.py — نظام البنك (وحدة داخل بوت الكنترول bot.py)
====================================================
منقول من bank_bot.py كما هو (الحساب، إيداع/سحب/حوالة/فائدة، الذهب، الوظائف، السرقة، الأغنياء)
مع أمرين الإدارة (بنك_اضافة / بنك_خصم).

الربط داخل bot.py (نفس طريقة tickets / protection / ajr):
    import bank
    bank.setup_bank(bot)

ملاحظات:
  - ملف البيانات: bank.json (انقله من مجلد بوت البنك القديم لمجلد بوت الكنترول).
  - الوحدة ما تسجل أي events (on_message / on_ready / ...) عشان ما تتعارض مع bot.py.
    اللي يحتاجه البنك من bot.py شيئين بس:
      1) bank.try_dispatch_bank_admin(message)  ← أوامر بنك_اضافة / بنك_خصم
      2) bank.BankChannelRequired               ← رسالة "أوامر البنك تشتغل بس في روم البنك"
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


# ---------- الرتب (نفس أسماء البوت الأساسي) ----------
OWNER = "Owner"
CO_OWNER = "Co-Owner"
VICE_OWNER = "Vice Owner"
ADMIN = "Admin"

TOP_ROLES = [VICE_OWNER, CO_OWNER, OWNER]
ADMIN_ROLES = [ADMIN] + TOP_ROLES


def has_role(member: discord.Member, allowed: list[str]) -> bool:
    names = {r.name for r in member.roles}
    return any(n in names for n in allowed)


async def reply(message: discord.Message, text: str):
    await message.channel.send(text)


# ---------- اللوقات (mod-logs / bot-logs) ----------
LOG_CHANNEL_NAMES = {
    "mod": ["mod-logs"],
    "bot": ["bot-logs"],
}


def find_log_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
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
# كل أوامر البنك تشتغل بس داخل روم اسمه فيه "bank" (لو ما فيه روم بهذا الاسم تشتغل بأي روم).
# الأقسام: حساب + بنك (إيداع/سحب/حوالة/فائدة) + ذهب (سعر متغير) + وظائف + سرقة + أغنياء.
BANK_FILE = "bank.json"
BANK_CHANNEL_NAMES = ["bank"]
CURRENCY = "ريال"

BANK_START_CASH = 1000            # كاش البداية لأي حساب جديد
BANK_TRANSFER_FEE = 0.02          # رسوم الحوالة (2%)
BANK_TRANSFER_MIN = 10            # أقل مبلغ حوالة
BANK_INTEREST_RATE = 0.01         # فائدة يومية 1% من رصيد البنك
BANK_INTEREST_MAX = 5000          # أقصى فائدة بالمرة الوحدة
BANK_INTEREST_MIN_BALANCE = 100   # أقل رصيد بنك يستحق فائدة
BANK_INTEREST_COOLDOWN = 86400    # مرة كل 24 ساعة

WORK_COOLDOWN = 3600              # .عمل مرة كل ساعة
WORK_PER_LEVEL = 5                # كل 5 مرات عمل = مستوى جديد
WORK_BONUS_CHANCE = 0.10          # 10% فرصة مكافأة x1.5

ROB_COOLDOWN = 3600               # .سرقة مرة كل ساعة
ROB_SUCCESS_CHANCE = 0.40
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

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")


class BankChannelRequired(commands.CheckFailure):
    pass


def find_bank_channel(guild: discord.Guild) -> discord.TextChannel | None:
    for ch in guild.text_channels:
        name = ch.name.lower().replace("_", "-")
        if any(target in name for target in BANK_CHANNEL_NAMES):
            return ch
    return None


async def _bank_channel_check(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        raise BankChannelRequired()
    bank_ch = find_bank_channel(ctx.guild)
    if bank_ch is None:
        return True  # ما فيه روم bank: نسمح بأي روم
    if ctx.channel.id == bank_ch.id or getattr(ctx.channel, "parent_id", None) == bank_ch.id:
        return True
    raise BankChannelRequired()


bank_only = commands.check(_bank_channel_check)


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
    return discord.Embed(title=title, description=description, color=color or discord.Color.gold())


async def _bank_send(ctx: commands.Context, embed: discord.Embed, content: str | None = None, ping=None) -> None:
    mentions = discord.AllowedMentions(users=[ping]) if ping is not None else discord.AllowedMentions.none()
    await ctx.send(content=content, embed=embed, allowed_mentions=mentions)


# ---------- الحساب ----------
@commands.command(name="بنك", aliases=["حسابي"])
@bank_only
async def bank_account_cmd(ctx: commands.Context, member: discord.Member = None):
    """.بنك [@عضو] — بطاقة الحساب: كاش + بنك + ذهب + وظيفة."""
    member = member or ctx.author
    if member.bot:
        await ctx.send("⚠️ البوتات ما عندها حساب بنكي.")
        return
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, member.id)
    if member.id == ctx.author.id:
        bank_save(data)  # يحفظ الحساب الجديد (كاش البداية) لو أول مرة
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
    embed.set_footer(text="الكاش ممكن ينسرق — فلوس البنك بأمان. اكتب .اوامر_البنك لكل الأوامر")
    await _bank_send(ctx, embed)


# ---------- البنك: إيداع / سحب / حوالة / فائدة ----------
@commands.command(name="ايداع")
@bank_only
async def deposit_cmd(ctx: commands.Context, amount: str = None):
    """.ايداع <مبلغ|كل> — تحط الكاش بالبنك (يتحمي من السرقة)."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    n = parse_amount(amount, acct["cash"])
    if not n:
        await ctx.send("⚠️ الصيغة: `.ايداع <المبلغ>` أو `.ايداع كل` (وكاشك لازم يكون أكبر من صفر).")
        return
    if n > acct["cash"]:
        await ctx.send(f"❌ كاشك ما يكفي. معك **{fmt(acct['cash'])}** {CURRENCY} كاش.")
        return
    acct["cash"] -= n
    acct["bank"] += n
    bank_save(data)
    embed = _bank_embed("🏦 تم الإيداع", f"أودعت **{fmt(n)}** {CURRENCY} بالبنك.", discord.Color.green())
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.add_field(name="🏦 البنك", value=fmt(acct["bank"]), inline=True)
    await _bank_send(ctx, embed)


@commands.command(name="سحب")
@bank_only
async def withdraw_cmd(ctx: commands.Context, amount: str = None):
    """.سحب <مبلغ|كل> — تسحب من البنك للكاش."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    n = parse_amount(amount, acct["bank"])
    if not n:
        await ctx.send("⚠️ الصيغة: `.سحب <المبلغ>` أو `.سحب كل` (ورصيدك بالبنك لازم يكون أكبر من صفر).")
        return
    if n > acct["bank"]:
        await ctx.send(f"❌ رصيدك بالبنك ما يكفي. عندك **{fmt(acct['bank'])}** {CURRENCY}.")
        return
    acct["bank"] -= n
    acct["cash"] += n
    bank_save(data)
    embed = _bank_embed("🏦 تم السحب", f"سحبت **{fmt(n)}** {CURRENCY} للكاش.", discord.Color.green())
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.add_field(name="🏦 البنك", value=fmt(acct["bank"]), inline=True)
    await _bank_send(ctx, embed)


@commands.command(name="حوالة")
@bank_only
async def bank_transfer_cmd(ctx: commands.Context, member: discord.Member, amount: str = None):
    """.حوالة @عضو <مبلغ> — حوالة من رصيد البنك لبنك عضو ثاني (رسوم 2%)."""
    if member.bot or member.id == ctx.author.id:
        await ctx.send("⚠️ ما تقدر تحول لنفسك أو لبوت.")
        return
    data = bank_load()
    sender = bank_acct(data, ctx.guild.id, ctx.author.id)
    n = parse_amount(amount, sender["bank"])
    if not n or n < BANK_TRANSFER_MIN:
        await ctx.send(f"⚠️ الصيغة: `.حوالة @عضو <المبلغ>` (أقل مبلغ {BANK_TRANSFER_MIN} {CURRENCY}).")
        return
    if n > sender["bank"]:
        await ctx.send(f"❌ رصيدك بالبنك ما يكفي. عندك **{fmt(sender['bank'])}** {CURRENCY}.")
        return
    receiver = bank_acct(data, ctx.guild.id, member.id)
    fee = max(1, round(n * BANK_TRANSFER_FEE))
    received = n - fee
    sender["bank"] -= n
    receiver["bank"] += received
    bank_save(data)
    embed = _bank_embed("💸 حوالة بنكية ناجحة", color=discord.Color.green())
    embed.add_field(name="من", value=ctx.author.mention, inline=True)
    embed.add_field(name="إلى", value=member.mention, inline=True)
    embed.add_field(name="المبلغ", value=f"{fmt(n)} {CURRENCY}", inline=True)
    embed.add_field(name="الرسوم", value=f"{fmt(fee)} {CURRENCY}", inline=True)
    embed.add_field(name="وصل للمستلم", value=f"{fmt(received)} {CURRENCY}", inline=True)
    await _bank_send(ctx, embed, content=member.mention, ping=member)


@commands.command(name="فائدة", aliases=["فايدة"])
@bank_only
async def bank_interest_cmd(ctx: commands.Context):
    """.فائدة — فائدة يومية على رصيد البنك (1%، مرة كل 24 ساعة)."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    wait = _cooldown_left(acct["last_interest"], BANK_INTEREST_COOLDOWN)
    if wait:
        await ctx.send(f"⏳ استلمت فائدتك اليوم. ارجع بعد **{_fmt_wait(wait)}**.")
        return
    if acct["bank"] < BANK_INTEREST_MIN_BALANCE:
        await ctx.send(f"⚠️ لازم يكون رصيدك بالبنك **{BANK_INTEREST_MIN_BALANCE}** {CURRENCY} على الأقل عشان تاخذ فائدة.")
        return
    interest = min(BANK_INTEREST_MAX, max(1, int(acct["bank"] * BANK_INTEREST_RATE)))
    acct["bank"] += interest
    acct["last_interest"] = _now_iso()
    bank_save(data)
    embed = _bank_embed("📈 فائدة البنك",
                        f"انضاف لرصيدك **{fmt(interest)}** {CURRENCY} ({BANK_INTEREST_RATE * 100:.0f}% من رصيدك).",
                        discord.Color.green())
    embed.add_field(name="🏦 رصيدك الحين", value=f"{fmt(acct['bank'])} {CURRENCY}", inline=True)
    await _bank_send(ctx, embed)


# ---------- الذهب ----------
def _gold_trend(history: list) -> str:
    if len(history) < 2 or not history[-2]:
        return "—"
    change = (history[-1] - history[-2]) / history[-2] * 100
    if change > 0:
        return f"▲ +{change:.1f}%"
    if change < 0:
        return f"▼ {change:.1f}%"
    return "● ثابت"


@commands.command(name="ذهب")
@bank_only
async def gold_cmd(ctx: commands.Context):
    """.ذهب — سعر الذهب الحالي وحركته وكم معك."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
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
    embed.set_footer(text=f"السعر يتغير كل {GOLD_STEP_SECONDS // 60} دقيقة • .شراء_ذهب <جرام> • .بيع_ذهب <جرام>")
    await _bank_send(ctx, embed)


@commands.command(name="شراء_ذهب")
@bank_only
async def buy_gold_cmd(ctx: commands.Context, grams: str = None):
    """.شراء_ذهب <جرام|كل> — تشتري ذهب من الكاش."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    price = data["_gold"]["price"]
    n = parse_amount(grams, acct["cash"] // price)
    if not n:
        if grams and acct["cash"] < price:
            await ctx.send(f"❌ كاشك ما يكفي لجرام واحد (السعر **{fmt(price)}** {CURRENCY}).")
        else:
            await ctx.send("⚠️ الصيغة: `.شراء_ذهب <عدد الجرامات>` أو `.شراء_ذهب كل`")
        return
    cost = n * price
    if cost > acct["cash"]:
        await ctx.send(f"❌ كاشك ما يكفي. تكلفة {fmt(n)} جرام = **{fmt(cost)}** {CURRENCY} وكاشك **{fmt(acct['cash'])}**.")
        return
    acct["cash"] -= cost
    acct["gold"] += n
    bank_save(data)
    embed = _bank_embed("🪙 تم شراء الذهب",
                        f"اشتريت **{fmt(n)}** جرام بسعر {fmt(price)} للجرام = **{fmt(cost)}** {CURRENCY}.",
                        discord.Color.green())
    embed.add_field(name="🪙 ذهبك", value=f"{fmt(acct['gold'])} جرام", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    await _bank_send(ctx, embed)


@commands.command(name="بيع_ذهب")
@bank_only
async def sell_gold_cmd(ctx: commands.Context, grams: str = None):
    """.بيع_ذهب <جرام|كل> — تبيع ذهب وتاخذ كاش (عمولة 2%)."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    price = data["_gold"]["price"]
    n = parse_amount(grams, acct["gold"])
    if not n:
        if grams and acct["gold"] == 0:
            await ctx.send("❌ ما عندك ذهب تبيعه.")
        else:
            await ctx.send("⚠️ الصيغة: `.بيع_ذهب <عدد الجرامات>` أو `.بيع_ذهب كل`")
        return
    if n > acct["gold"]:
        await ctx.send(f"❌ ما عندك كفاية. معك **{fmt(acct['gold'])}** جرام.")
        return
    revenue = int(n * price * (1 - GOLD_SELL_FEE))
    acct["gold"] -= n
    acct["cash"] += revenue
    bank_save(data)
    embed = _bank_embed("🪙 تم بيع الذهب",
                        f"بعت **{fmt(n)}** جرام بسعر {fmt(price)} للجرام (بعد عمولة {GOLD_SELL_FEE * 100:.0f}%) "
                        f"وأخذت **{fmt(revenue)}** {CURRENCY}.",
                        discord.Color.green())
    embed.add_field(name="🪙 ذهبك", value=f"{fmt(acct['gold'])} جرام", inline=True)
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    await _bank_send(ctx, embed)


# ---------- الوظائف ----------
@commands.command(name="وظائف")
@bank_only
async def jobs_list_cmd(ctx: commands.Context):
    """.وظائف — قائمة الوظايف ورواتبها والمستوى المطلوب."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    level = _level(acct)
    lines = []
    for name, min_level, low, high, emoji in BANK_JOBS:
        lock = "" if level >= min_level else " 🔒"
        current = " ✅" if acct.get("job") == name else ""
        lines.append(f"{emoji} **{name}** — مستوى {min_level}+ — {fmt(low)}–{fmt(high)} {CURRENCY}{lock}{current}")
    embed = _bank_embed("💼 الوظائف", "\n".join(lines))
    embed.set_footer(text=f"مستواك: {level} • .توظف <اسم الوظيفة> • .عمل (كل ساعة) • كل {WORK_PER_LEVEL} مرات عمل = مستوى")
    await _bank_send(ctx, embed)


@commands.command(name="توظف")
@bank_only
async def job_apply_cmd(ctx: commands.Context, *, job_name: str = None):
    """.توظف <اسم الوظيفة> — تتوظف (لو مستواك يكفي)."""
    job = _find_job(job_name)
    if job is None:
        await ctx.send("⚠️ ما لقيت هذي الوظيفة. شوف القائمة بـ `.وظائف` ثم اكتب `.توظف <اسم الوظيفة>`.")
        return
    name, min_level, low, high, emoji = job
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    if _level(acct) < min_level:
        await ctx.send(f"🔒 وظيفة **{name}** تحتاج مستوى **{min_level}** ومستواك **{_level(acct)}**. اشتغل أكثر بـ `.عمل`.")
        return
    if acct.get("job") == name:
        await ctx.send(f"⚠️ أنت أصلًا شغال **{name}**.")
        return
    acct["job"] = name
    bank_save(data)
    embed = _bank_embed("💼 تم التوظيف", f"مبروك! صرت **{emoji} {name}**.\nالراتب: {fmt(low)}–{fmt(high)} {CURRENCY} بالمرة.",
                        discord.Color.green())
    await _bank_send(ctx, embed)


@commands.command(name="استقالة")
@bank_only
async def job_quit_cmd(ctx: commands.Context):
    """.استقالة — تترك وظيفتك (مستواك يبقى)."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    if not acct.get("job"):
        await ctx.send("⚠️ أنت عاطل أصلًا.")
        return
    old = acct["job"]
    acct["job"] = None
    bank_save(data)
    await _bank_send(ctx, _bank_embed("📝 استقالة", f"تركت وظيفة **{old}**. مستواك محفوظ."))


@commands.command(name="عمل")
@bank_only
async def work_cmd(ctx: commands.Context):
    """.عمل — تشتغل وتستلم راتب كاش (كل ساعة)."""
    data = bank_load()
    acct = bank_acct(data, ctx.guild.id, ctx.author.id)
    job = _find_job(acct["job"]) if acct.get("job") else None
    if job is None:
        await ctx.send("⚠️ ما عندك وظيفة. شوف `.وظائف` ثم `.توظف <اسم الوظيفة>`.")
        return
    wait = _cooldown_left(acct["last_work"], WORK_COOLDOWN)
    if wait:
        await ctx.send(f"⏳ تعبان! ارجع للشغل بعد **{_fmt_wait(wait)}**.")
        return
    name, _, low, high, emoji = job
    pay = random.randint(low, high)
    bonus = random.random() < WORK_BONUS_CHANCE
    if bonus:
        pay = int(pay * 1.5)
    old_level = _level(acct)
    acct["cash"] += pay
    acct["works"] += 1
    acct["last_work"] = _now_iso()
    new_level = _level(acct)
    bank_save(data)
    desc = f"اشتغلت **{emoji} {name}** وأخذت **{fmt(pay)}** {CURRENCY} كاش."
    if bonus:
        desc += "\n🎉 جاك مكافأة من المدير (x1.5)!"
    embed = _bank_embed("💼 يوم عمل", desc, discord.Color.green())
    embed.add_field(name="💵 الكاش", value=fmt(acct["cash"]), inline=True)
    embed.add_field(name="⭐ المستوى", value=str(new_level), inline=True)
    if new_level > old_level:
        embed.add_field(name="🆙 ترقية!", value=f"وصلت مستوى **{new_level}** — شوف `.وظائف` للوظايف الجديدة.", inline=False)
    await _bank_send(ctx, embed)


# ---------- السرقة ----------
@commands.command(name="سرقة")
@bank_only
async def rob_cmd(ctx: commands.Context, member: discord.Member):
    """.سرقة @عضو — تحاول تسرق من كاشه (فلوس البنك بأمان). نجاح 40%، والفشل غرامة للضحية."""
    if member.bot or member.id == ctx.author.id:
        await ctx.send("⚠️ ما تقدر تسرق نفسك أو بوت.")
        return
    data = bank_load()
    thief = bank_acct(data, ctx.guild.id, ctx.author.id)
    victim = bank_acct(data, ctx.guild.id, member.id)
    wait = _cooldown_left(thief["last_rob"], ROB_COOLDOWN)
    if wait:
        await ctx.send(f"⏳ الشرطة تدور عليك! حاول بعد **{_fmt_wait(wait)}**.")
        return
    if thief["cash"] < ROB_MIN_THIEF_CASH:
        await ctx.send(f"❌ لازم يكون معك **{ROB_MIN_THIEF_CASH}** {CURRENCY} كاش على الأقل (عشان الغرامة لو انمسكت).")
        return
    if victim["cash"] < ROB_MIN_VICTIM_CASH:
        await ctx.send(f"⚠️ كاش {member.display_name} قليل ما يستاهل السرقة (وفلوس البنك محمية).")
        return
    thief["last_rob"] = _now_iso()
    if random.random() < ROB_SUCCESS_CHANCE:
        stolen = min(ROB_MAX_STEAL, max(1, int(victim["cash"] * random.uniform(0.10, 0.30))))
        victim["cash"] -= stolen
        thief["cash"] += stolen
        embed = _bank_embed("🦹 سرقة ناجحة",
                            f"{ctx.author.mention} سرق **{fmt(stolen)}** {CURRENCY} من {member.mention}!",
                            discord.Color.red())
    else:
        fine = min(thief["cash"], max(ROB_MIN_THIEF_CASH, int(thief["cash"] * ROB_FINE_PERCENT)))
        thief["cash"] -= fine
        victim["cash"] += fine
        embed = _bank_embed("🚔 انمسكت!",
                            f"{ctx.author.mention} حاول يسرق {member.mention} وانمسك، ودفع غرامة **{fmt(fine)}** {CURRENCY} للضحية.",
                            discord.Color.dark_grey())
    bank_save(data)
    embed.set_footer(text="تنبيه: حط فلوسك بالبنك (.ايداع) عشان ما تنسرق")
    await _bank_send(ctx, embed, content=member.mention, ping=member)


# ---------- الأغنياء ----------
@commands.command(name="اغنياء", aliases=["ثروات"])
@bank_only
async def rich_cmd(ctx: commands.Context):
    """.اغنياء — أغنى 10 أعضاء (كاش + بنك + ذهب)."""
    data = bank_load()
    price = data["_gold"]["price"]
    rows = []
    for uid, acct in data.get(str(ctx.guild.id), {}).items():
        if not uid.isdigit() or not isinstance(acct, dict):
            continue
        member = ctx.guild.get_member(int(uid))
        if member is None or member.bot:
            continue
        rows.append((member, _net_worth(acct, price)))
    rows.sort(key=lambda r: r[1], reverse=True)
    if not rows:
        await ctx.send("📉 ما فيه حسابات بنكية لين الحين.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, worth) in enumerate(rows[:10]):
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{rank} {member.mention} — **{fmt(worth)}** {CURRENCY}")
    await _bank_send(ctx, _bank_embed("💎 أغنى الأعضاء", "\n".join(lines)))


# ---------- قائمة أوامر البنك ----------
BANK_HELP_SECTIONS = [
    ("🏦 الحساب والبنك",
     "`.بنك [@عضو]` — بطاقة الحساب\n"
     "`.ايداع <مبلغ|كل>` — كاش ← بنك\n"
     "`.سحب <مبلغ|كل>` — بنك ← كاش\n"
     f"`.حوالة @عضو <مبلغ>` — حوالة بنكية (رسوم {BANK_TRANSFER_FEE * 100:.0f}%)\n"
     f"`.فائدة` — فائدة {BANK_INTEREST_RATE * 100:.0f}% يوميًا على رصيد البنك"),
    ("🪙 الذهب",
     "`.ذهب` — السعر والحركة\n"
     "`.شراء_ذهب <جرام|كل>`\n"
     "`.بيع_ذهب <جرام|كل>`"),
    ("💼 الوظائف",
     "`.وظائف` — القائمة والرواتب\n"
     "`.توظف <اسم الوظيفة>`\n"
     "`.عمل` — راتب كل ساعة\n"
     "`.استقالة`"),
    ("🦹 أخرى",
     "`.سرقة @عضو` — تسرق من كاشه (فلوس البنك محمية)\n"
     "`.اغنياء` — أغنى 10 أعضاء"),
]


@commands.command(name="اوامر_البنك", aliases=["اوامر_بنك"])
@bank_only
async def bank_help_cmd(ctx: commands.Context):
    embed = _bank_embed("🏦 أوامر البنك")
    for name, text in BANK_HELP_SECTIONS:
        embed.add_field(name=name, value=text, inline=False)
    # أوامر الإدارة تبان بس لأصحاب رتبة Admin وفوق
    if isinstance(ctx.author, discord.Member) and has_role(ctx.author, ADMIN_ROLES):
        embed.add_field(
            name="🛡️ للإدارة (بدون نقطة)",
            value=("`بنك_اضافة @عضو المبلغ` — إضافة كاش لحساب عضو\n"
                   "`بنك_خصم @عضو المبلغ` — خصم من كاش العضو ثم رصيده بالبنك\n"
                   f"الرتبة: **{ADMIN}** وأعلى"),
            inline=False)
    embed.set_footer(text=f"العملة: {CURRENCY} • منفصلة تمامًا عن نقاط الألعاب")
    await _bank_send(ctx, embed)


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
    """يرجع True لو الرسالة كانت أمر إدارة بنك (بنك_اضافة / بنك_خصم) وتم التعامل معها."""
    return await try_dispatch_admin_command(message)


async def handle_bank_channel_error(ctx: commands.Context) -> None:
    """رسالة التنبيه لما أمر بنك ينكتب بغير روم البنك."""
    bank_ch = find_bank_channel(ctx.guild) if ctx.guild else None
    if bank_ch is not None:
        await ctx.send(f"{ctx.author.mention} 🏦 أوامر البنك تشتغل بس في {bank_ch.mention}", delete_after=8)


def setup_bank(bot: commands.Bot) -> None:
    """يسجل كل أوامر البنك بالبوت. لو اسم أمر مكرر مع أمر ثاني يتخطاه ويطبع تنبيه (ما يطيّح البوت)."""
    added = 0
    for obj in list(globals().values()):
        if isinstance(obj, commands.Command):
            try:
                bot.add_command(obj)
                added += 1
            except commands.CommandRegistrationError as e:
                print(f"[بنك] ⚠️ تخطيت أمر مكرر: {e}")
    print(f"[بنك] ✅ تم تحميل نظام البنك ({added} أمر)")
