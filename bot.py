from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

def run_web_server():
    server_address = ('0.0.0.0', 10000)
    httpd = HTTPServer(server_address, SimpleHandler)
    httpd.serve_forever()
  """
بوت ديسكورد شامل — نسخة كاملة مدموجة (مع مركز الألعاب الموسّع)
=====================================================================
الأقسام:
  1) نظام التنبيهات (تنبيه)
  2) نظام الاقتصاد / النقاط (رصيد / نقاطي / يومي / تحويل)
  3) نظام الجولات العام (لألعاب "أول من يجاوب يفوز")
  4) مركز الألعاب:
       - ألعاب جماعية (تبدأ بلوبي 30 ثانية، فيها زر انضمام وزر خروج، حتى 20 لاعب)
       - ألعاب فردية / تحدي مباشر
  5) نظام الإدارة الكامل (أعضاء / رومات / صوت) — بدون بريفكس، حسب الرتب
  6) .العاب و .شرح <اسم اللعبة> و .اوامر

ملاحظات مهمة قبل التشغيل:
  - كل أوامر النقاط والألعاب تبدأ بعلامة "." (مثال: .روليت ، .نقاطي ، .العاب ، .اوامر).
  - أوامر الإدارة تبقى بدون بريفكس زي ما كانت (تنبيه ، برا ، سجن ... إلخ).
  - غيّر أسماء الرتب بالأسفل (ROLE NAMES) إذا كانت أسماء رتبك بالسيرفر
    مختلفة شوي عن الأسماء المكتوبة هنا (لازم تطابق بالضبط حرف بحرف).
  - لازم تسوي رتبتين يدويًا بالسيرفر عشان "سجن" و"اخرس" يشتغلوا صح:
        * رتبة اسمها بالضبط: Jailed  (احجب عنها كل الرومات إلا روم السجن)
        * رتبة اسمها بالضبط: Muted   (احجب عنها إرسال الرسائل بكل الرومات)
    لو ما كانت موجودة، البوت بينشئها تلقائيًا لكن بدون صلاحيات محجوبة —
    لازم تظبط صلاحياتها يدويًا من إعدادات السيرفر أول مرة.

  - بعض الألعاب (مثل "ادمج" و"ريبلكا") فيها تفسير مبسّط مني لأسمائها —
    لو تقصد شكل مختلف قولي وأعدلها.
"""

import discord
from discord.ext import commands
import aiohttp
import asyncio
import itertools
import json
import os
import re
import random
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
WARN_LOG_WEBHOOK_URL = os.environ.get("WARN_WEBHOOK_URL", "")

WARNS_FILE = "warns.json"
ECONOMY_FILE = "economy.json"
JAIL_FILE = "jail_data.json"
ROLES_REMOVED_FILE = "removed_roles.json"

JAIL_ROLE_NAME = "Jailed"
MUTE_ROLE_NAME = "Muted"
WARN_LOG_CHANNEL_NAMES = ["warn-log", "توثيق-التنبيهات", "سجل-التنبيهات", "تنبيهات-اللوق", "log-تنبيهات"]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=".", intents=intents)


# ============================================================
# أدوات تخزين JSON عامة
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


# ============================================================
# 1) نظام التنبيهات
# ============================================================
REQUIRED_WARN_PERMISSION = "manage_messages"


def add_warn(guild_id: int, member_id: int, reason: str, moderator_id: int) -> int:
    data = load_json(WARNS_FILE)
    gid, mid = str(guild_id), str(member_id)
    data.setdefault(gid, {})
    data[gid].setdefault(mid, [])
    warn_number = len(data[gid][mid]) + 1
    data[gid][mid].append({
        "number": warn_number, "reason": reason,
        "moderator_id": moderator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_json(WARNS_FILE, data)
    return warn_number


def get_warn_count(guild_id: int, member_id: int) -> int:
    data = load_json(WARNS_FILE)
    return len(data.get(str(guild_id), {}).get(str(member_id), []))


def find_warn_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """يدور على روم مخصص للوق التنبيهات بالاسم (يتحمل حروف كبيرة/صغيرة ومسافات/شرطات)."""
    for ch in guild.text_channels:
        normalized_name = ch.name.lower().replace("_", "-")
        for target_name in WARN_LOG_CHANNEL_NAMES:
            if target_name.lower() in normalized_name:
                return ch
    return None


async def send_warn_log(guild: discord.Guild, target, moderator, reason, warn_number, channel_name):
    """يرسل لوق التنبيه لروم مخصص — عبر الويب هوك أولًا، وإذا ما نجح يرسله مباشرة عبر البوت لروم اللوق."""
    embed = discord.Embed(
        title="⚠️ تم تسجيل تنبيه رسمي",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="العضو", value=target.mention, inline=True)
    embed.add_field(name="بواسطة", value=moderator.mention, inline=True)
    embed.add_field(name="رقم التنبيه", value=f"#{warn_number}", inline=True)
    embed.add_field(name="السبب", value=reason or "لم يُذكر سبب", inline=False)
    embed.add_field(name="القناة", value=f"#{channel_name}", inline=True)
    embed.set_footer(text=f"معرف العضو: {target.id}")
    if target.display_avatar:
        embed.set_thumbnail(url=target.display_avatar.url)

    delivered = False

    if WARN_LOG_WEBHOOK_URL:
        payload = {
            "username": "نظام التنبيهات",
            "embeds": [embed.to_dict()],
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(WARN_LOG_WEBHOOK_URL, json=payload) as resp:
                    if resp.status in (200, 204):
                        delivered = True
                    else:
                        print(f"[WarnSystem] فشل إرسال الويب هوك: {resp.status}")
        except Exception as e:
            print(f"[WarnSystem] خطأ بالويب هوك: {e}")

    if not delivered:
        log_channel = find_warn_log_channel(guild)
        if log_channel:
            try:
                await log_channel.send(embed=embed)
                delivered = True
            except discord.Forbidden:
                print("[WarnSystem] ما عندي صلاحية أرسل بروم اللوق.")

    if not delivered:
        print("[WarnSystem] ⚠️ ما قدرت أوصل لوق التنبيه — لا الويب هوك اشتغل ولا لقيت روم اسمه warn-log.")


async def handle_warn_command(message: discord.Message):
    author = message.author
    if not isinstance(author, discord.Member) or not getattr(
        author.guild_permissions, REQUIRED_WARN_PERMISSION
    ):
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        await message.channel.send(f"{author.mention} ❌ ليس لديك صلاحية.", delete_after=6)
        return

    if not message.mentions:
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        await message.channel.send(f"{author.mention} ⚠️ الصيغة: `تنبيه @العضو السبب`", delete_after=6)
        return

    target = message.mentions[0]
    reason = message.content.replace("تنبيه", "", 1)
    for m in message.mentions:
        reason = reason.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
    reason = reason.strip() or "لم يُذكر سبب"

    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    warn_number = add_warn(message.guild.id, target.id, reason, author.id)
    await send_warn_log(message.guild, target, author, reason, warn_number, message.channel.name)
    await message.channel.send(f"✅ تسجل تنبيه رقم **#{warn_number}** بحق {target.mention}", delete_after=6)


@bot.command(name="تنبيهاته", aliases=["warns"])
async def show_warns(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    count = get_warn_count(ctx.guild.id, member.id)
    await ctx.send(f"📋 لدى {member.mention} **{count}** تنبيه/تنبيهات مسجلة.")


# ============================================================
# 2) نظام الاقتصاد / النقاط
# ============================================================
def get_balance(guild_id: int, user_id: int) -> int:
    data = load_json(ECONOMY_FILE)
    return data.get(str(guild_id), {}).get(str(user_id), 0)


def add_balance(guild_id: int, user_id: int, amount: int) -> int:
    data = load_json(ECONOMY_FILE)
    gid, uid = str(guild_id), str(user_id)
    data.setdefault(gid, {})
    data[gid][uid] = data[gid].get(uid, 0) + amount
    save_json(ECONOMY_FILE, data)
    return data[gid][uid]


@bot.command(name="رصيد")
async def balance_cmd(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(f"💰 رصيد {member.mention}: **{get_balance(ctx.guild.id, member.id)}** نقطة")


@bot.command(name="نقاطي")
async def my_points_cmd(ctx: commands.Context):
    pts = get_balance(ctx.guild.id, ctx.author.id)
    await ctx.send(f"⭐ {ctx.author.mention} رصيدك من النقاط: **{pts}** نقطة")


@bot.command(name="يومي")
async def daily_cmd(ctx: commands.Context):
    data = load_json(ECONOMY_FILE)
    gid, uid = str(ctx.guild.id), str(ctx.author.id)
    data.setdefault(gid, {})
    last = data[gid].get(f"{uid}_last_daily")
    now = datetime.now(timezone.utc)
    if last:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds()
        if elapsed < 86400:
            hrs_left = int((86400 - elapsed) // 3600)
            await ctx.send(f"⏳ أخذت جائزتك اليومية! ارجع بعد ~{hrs_left} ساعة.")
            return
    reward = random.randint(100, 300)
    data[gid][uid] = data[gid].get(uid, 0) + reward
    data[gid][f"{uid}_last_daily"] = now.isoformat()
    save_json(ECONOMY_FILE, data)
    await ctx.send(f"🎁 {ctx.author.mention} أخذت **{reward}** نقطة!")


@bot.command(name="تحويل")
async def transfer_cmd(ctx: commands.Context, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("⚠️ المبلغ لازم يكون أكبر من صفر.")
        return
    if member == ctx.author or member.bot:
        await ctx.send("⚠️ ما تقدر تحول لنفسك أو لبوت.")
        return
    if get_balance(ctx.guild.id, ctx.author.id) < amount:
        await ctx.send("❌ رصيدك ما يكفي.")
        return
    add_balance(ctx.guild.id, ctx.author.id, -amount)
    add_balance(ctx.guild.id, member.id, amount)
    await ctx.send(f"✅ تم تحويل **{amount}** نقطة إلى {member.mention}")


# ============================================================
# 3) نظام الجولات العام — لألعاب "أول من يجاوب صح يفوز"
# ============================================================
def normalize(text: str) -> str:
    """تطبيع النص عشان المقارنة تكون متسامحة مع الهمزات والتاء المربوطة والتشكيل."""
    text = text.strip()
    text = re.sub(r"[إأآا]", "ا", text)
    text = text.replace("ى", "ي")
    text = text.replace("ة", "ه")
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return text.strip().lower()


active_rounds: dict[int, dict] = {}   # channel_id -> بيانات الجولة الحالية
_round_id_counter = itertools.count()

# ---------- قفل عام يمنع تداخل الألعاب: روم واحد = لعبة وحدة بنفس اللحظة ----------
active_channel_games: dict[int, str] = {}  # channel_id -> اسم اللعبة الشغالة


def is_channel_busy(channel_id: int) -> bool:
    return channel_id in active_channel_games


def mark_busy(channel_id: int, game_name: str) -> None:
    active_channel_games[channel_id] = game_name


def unmark_busy(channel_id: int) -> None:
    active_channel_games.pop(channel_id, None)


async def warn_busy(ctx: commands.Context) -> None:
    name = active_channel_games.get(ctx.channel.id, "لعبة")
    await ctx.send(f"⚠️ فيه **{name}** شغالة بهذا الروم حاليًا، خلصوها الأول قبل لعبة ثانية.")


async def start_round(channel, *, title: str, prompt: str, checker, reward=(20, 40),
                       allowed_ids: set | None = None, timeout: int = 45, reveal: str = ""):
    """يبدأ جولة سؤال/جواب بالروم. أول رسالة تطابق checker تفوز."""
    if channel.id in active_rounds or is_channel_busy(channel.id):
        busy_name = active_channel_games.get(channel.id, title)
        await channel.send(f"⚠️ فيه **{busy_name}** شغالة بهذا الروم حاليًا، خلصوها الأول.")
        return
    token = next(_round_id_counter)
    active_rounds[channel.id] = {
        "checker": checker, "reward": reward,
        "allowed_ids": allowed_ids, "token": token, "reveal": reveal,
    }
    mark_busy(channel.id, title)
    await channel.send(f"🎯 **{title}**\n{prompt}")

    async def _timeout_watcher():
        await asyncio.sleep(timeout)
        current = active_rounds.get(channel.id)
        if current and current.get("token") == token:
            del active_rounds[channel.id]
            unmark_busy(channel.id)
            extra = f" الإجابة كانت: **{reveal}**" if reveal else ""
            await channel.send(f"⏳ خلص الوقت!{extra}")

    bot.loop.create_task(_timeout_watcher())


# ============================================================
# 4) بنوك بيانات الألعاب
# ============================================================
WORD_BANK = ["مدرسة", "حاسوب", "سيارة", "طائرة", "مستشفى", "مكتبة", "شمس", "قمر",
             "بحر", "جبل", "صحراء", "نافذة", "مفتاح", "كتاب", "قلم"]

SPELL_BANK = [
    ("مدرصة", "مدرسة"), ("قلن", "قلم"), ("حديكة", "حديقة"),
    ("فراسة", "فراشة"), ("غاية", "غابة"), ("نافزة", "نافذة"),
    ("ظفدع", "ضفدع"), ("تعلب", "ثعلب"), ("زئب", "ذئب"),
    ("شنس", "شمس"), ("سيارت", "سيارة"), ("كتاپ", "كتاب"),
]

FLAG_BANK = [
    ("🇸🇦", "السعودية"), ("🇪🇬", "مصر"), ("🇦🇪", "الإمارات"), ("🇰🇼", "الكويت"),
    ("🇯🇴", "الأردن"), ("🇲🇦", "المغرب"), ("🇶🇦", "قطر"), ("🇧🇭", "البحرين"),
    ("🇴🇲", "عمان"), ("🇮🇶", "العراق"), ("🇱🇧", "لبنان"), ("🇹🇷", "تركيا"),
    ("🇫🇷", "فرنسا"), ("🇯🇵", "اليابان"), ("🇧🇷", "البرازيل"),
]

EMOJI_GUESS_BANK = [
    ("🦁", "أسد"), ("🐘", "فيل"), ("🍕", "بيتزا"), ("🍔", "برجر"),
    ("⚽", "كرة قدم"), ("🏀", "كرة سلة"), ("🚗", "سيارة"), ("✈️", "طائرة"),
    ("🌙", "قمر"), ("☀️", "شمس"), ("🌧️", "مطر"), ("❄️", "ثلج"),
    ("🐬", "دولفين"), ("🐢", "سلحفاة"), ("🎸", "قيتار"),
]

COMPOUND_BANK = [
    ("🌹💧", "ماء ورد"), ("☀️🌻", "عباد الشمس"), ("❄️☃️", "رجل الثلج"),
    ("🔥🚒", "إطفائية"), ("🐄🥛", "حليب"), ("🐔🥚", "بيضة"),
    ("🌽🍿", "فشار"), ("🍇🧃", "عصير عنب"), ("🐝🍯", "عسل"),
]

COLOR_BANK = [
    ("🍋", "أصفر"), ("🍎", "أحمر"), ("🥦", "أخضر"), ("🍇", "بنفسجي"),
    ("🍊", "برتقالي"), ("⚫", "أسود"), ("⚪", "أبيض"), ("🌊", "أزرق"),
    ("🟤", "بني"), ("🩷", "وردي"),
]

PHRASE_BANK = [
    "الوقت كالسيف إن لم تقطعه قطعك",
    "من جد وجد ومن زرع حصد",
    "العلم نور والجهل ظلام",
    "الصبر مفتاح الفرج",
    "خير الكلام ما قل ودل",
    "درهم وقاية خير من قنطار علاج",
]

ARABIC_LETTERS = list("ابتثجحخدذرزسشصضطظعغفقكلمنهوي")
CATEGORIES = ["حيوان", "دولة", "فاكهة", "مهنة", "لون", "اسم ولد"]

STARTER_WORDS = ["كتاب", "سيارة", "مدرسة", "قمر", "بحر", "تفاح", "حديقة", "سمكة"]


def scramble(word: str) -> str:
    letters = list(word)
    shuffled = letters.copy()
    tries = 0
    while "".join(shuffled) == word and tries < 10:
        random.shuffle(shuffled)
        tries += 1
    return "".join(shuffled)


# ============================================================
# 5) ألعاب الجولات الفردية/السريعة (أول من يجاوب صح)
# ============================================================
@bot.command(name="فكك")
async def unscramble_cmd(ctx: commands.Context):
    word = random.choice(WORD_BANK)
    scrambled = scramble(word)
    await start_round(ctx.channel, title="فكك الكلمة", prompt=f"رتب الحروف: **{scrambled}**",
                       checker=lambda c: normalize(c) == normalize(word),
                       reward=(25, 45), reveal=word)


@bot.command(name="اعكس")
async def reverse_cmd(ctx: commands.Context):
    word = random.choice(WORD_BANK)
    reversed_word = word[::-1]
    await start_round(ctx.channel, title="اعكس الكلمة", prompt=f"اكتب هذي الكلمة بالعكس: **{word}**",
                       checker=lambda c: normalize(c) == normalize(reversed_word),
                       reward=(20, 35), reveal=reversed_word)


@bot.command(name="صحح")
async def correct_cmd(ctx: commands.Context):
    wrong, correct = random.choice(SPELL_BANK)
    await start_round(ctx.channel, title="صحح الكلمة",
                       prompt=f"هذي الكلمة مكتوبة غلط: **{wrong}**\nاكتبها صح.",
                       checker=lambda c: normalize(c) == normalize(correct),
                       reward=(20, 35), reveal=correct)


@bot.command(name="اعلام")
async def flags_cmd(ctx: commands.Context):
    flag, country = random.choice(FLAG_BANK)
    await start_round(ctx.channel, title="خمن الدولة", prompt=f"وش هذي الدولة؟ {flag}",
                       checker=lambda c: normalize(country) in normalize(c),
                       reward=(20, 40), reveal=country)


@bot.command(name="ايموجي")
async def emoji_guess_cmd(ctx: commands.Context):
    emoji, answer = random.choice(EMOJI_GUESS_BANK)
    await start_round(ctx.channel, title="خمن من الرمز", prompt=f"وش تتوقع هذا الرمز؟ {emoji}",
                       checker=lambda c: normalize(c) == normalize(answer),
                       reward=(15, 30), reveal=answer)


@bot.command(name="ادمج")
async def combine_cmd(ctx: commands.Context):
    emojis, answer = random.choice(COMPOUND_BANK)
    await start_round(ctx.channel, title="ادمج وخمن", prompt=f"وش الكلمة اللي يرمز لها دمج: {emojis}",
                       checker=lambda c: normalize(c) == normalize(answer),
                       reward=(25, 45), reveal=answer)


@bot.command(name="الوان")
async def colors_cmd(ctx: commands.Context):
    emoji, color = random.choice(COLOR_BANK)
    await start_round(ctx.channel, title="خمن اللون", prompt=f"وش اللون المرتبط بـ {emoji}؟",
                       checker=lambda c: normalize(c) == normalize(color),
                       reward=(15, 25), reveal=color)


@bot.command(name="اسرع")
async def fastest_typer_cmd(ctx: commands.Context):
    phrase = random.choice(PHRASE_BANK)
    await start_round(ctx.channel, title="أسرع كتابة",
                       prompt=f"اكتب هذي الجملة بالضبط بأسرع وقت:\n**{phrase}**",
                       checker=lambda c: normalize(c) == normalize(phrase),
                       reward=(30, 60), reveal=phrase, timeout=45)


@bot.command(name="حرف")
async def letter_game_cmd(ctx: commands.Context):
    category = random.choice(CATEGORIES)
    letter = random.choice(ARABIC_LETTERS)

    def checker(content: str) -> bool:
        c = normalize(content).replace(" ", "")
        return c.startswith(normalize(letter)) and len(c) >= 2

    await start_round(ctx.channel, title="أول من يجاوب",
                       prompt=f"اذكر ({category}) يبدأ بحرف **{letter}**",
                       checker=checker, reward=(15, 30), reveal="", timeout=30)


@bot.command(name="ترتيب")
async def ordering_cmd(ctx: commands.Context):
    nums = random.sample(range(1, 51), 6)
    correct = sorted(nums)
    shuffled = nums.copy()
    random.shuffle(shuffled)

    def checker(content: str) -> bool:
        found = [int(x) for x in re.findall(r"-?\d+", content)]
        return found == correct

    nums_text = "   ".join(str(n) for n in shuffled)
    reveal_text = "  ".join(str(n) for n in correct)
    await start_round(ctx.channel, title="رتب الأرقام",
                       prompt=f"رتب هذي الأرقام تصاعديًا (اكتبهم بمسافة بينهم):\n**{nums_text}**",
                       checker=checker, reward=(20, 35), reveal=reveal_text, timeout=40)


@bot.command(name="كلمة")
async def word_chain_cmd(ctx: commands.Context):
    word = random.choice(STARTER_WORDS)
    last_letter = normalize(word)[-1]

    def checker(content: str) -> bool:
        c = normalize(content).replace(" ", "")
        return len(c) >= 2 and c[0] == last_letter and c != normalize(word)

    await start_round(ctx.channel, title="سلسلة الكلمات",
                       prompt=f"الكلمة: **{word}**\nقولوا كلمة تبدأ بآخر حرف منها (حرف {word[-1]})",
                       checker=checker, reward=(15, 30), reveal="", timeout=30)


# ---------- خمن (تخمين رقم — مفتوحة بالروم، فيها تلميح فوق/تحت) ----------
active_guess_games: dict[int, dict] = {}


@bot.command(name="خمن", aliases=["تخمين"])
async def guess_start(ctx: commands.Context, max_number: int = 100):
    if ctx.channel.id in active_guess_games or is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    if max_number < 10:
        await ctx.send("⚠️ اختر رقم أقصى 10 أو أكثر.")
        return
    number = random.randint(1, max_number)
    active_guess_games[ctx.channel.id] = {"number": number, "max": max_number}
    mark_busy(ctx.channel.id, "خمن (تخمين رقم)")
    await ctx.send(f"🔢 اخترت رقم سري بين **1** و **{max_number}**! اكتبوا تخمينكم.")


# ============================================================
# 6) ألعاب فردية تفاعلية (أزرار)
# ============================================================
class ReflexButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="انتظر...", style=discord.ButtonStyle.secondary, disabled=True)

    async def callback(self, interaction: discord.Interaction):
        view: ReflexView = self.view
        if not view.ready:
            await interaction.response.send_message("⏳ بدري! انتظر لين يصير أخضر.", ephemeral=True)
            return
        if self.disabled:
            return
        elapsed = (datetime.now(timezone.utc) - view.ready_time).total_seconds()
        self.disabled = True
        self.label = f"{interaction.user.display_name} فاز! ({elapsed:.2f}s)"
        self.style = discord.ButtonStyle.success
        pts = max(10, int(50 - elapsed * 10))
        add_balance(interaction.guild.id, interaction.user.id, pts)
        await interaction.response.edit_message(
            content=f"⚡ فاز {interaction.user.mention} بسرعة {elapsed:.2f} ثانية! (+{pts} نقطة)", view=view)
        view.stop()


class ReflexView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=20)
        self.ready = False
        self.ready_time = None
        self.button = ReflexButton()
        self.add_item(self.button)


@bot.command(name="زر")
async def button_game_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "زر السرعة")
    try:
        view = ReflexView()
        msg = await ctx.send("🔴 استعدوا... اضغطوا الزر أول ما يصير أخضر!", view=view)
        await asyncio.sleep(random.uniform(2, 6))
        if not view.is_finished():
            view.ready = True
            view.ready_time = datetime.now(timezone.utc)
            view.button.disabled = False
            view.button.label = "🟢 اضغط الآن!"
            view.button.style = discord.ButtonStyle.success
            try:
                await msg.edit(content="🟢 دورك! اضغط بسرعة!", view=view)
            except discord.NotFound:
                pass
        await view.wait()
    finally:
        unmark_busy(ctx.channel.id)


class MemoryButton(discord.ui.Button):
    def __init__(self, idx: int):
        super().__init__(label="❓", style=discord.ButtonStyle.secondary, row=idx // 4)
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        view: MemoryView = self.view
        if interaction.user != view.player:
            await interaction.response.send_message("⚠️ هذي مو لعبتك.", ephemeral=True)
            return
        await view.flip(interaction, self.idx, self)


class MemoryView(discord.ui.View):
    def __init__(self, player: discord.Member):
        super().__init__(timeout=120)
        self.player = player
        emojis = ["🍎", "🍌", "🍇", "🍉", "🍒", "🍋", "🍑", "🥝"] * 2
        random.shuffle(emojis)
        self.cards = emojis
        self.matched = [False] * 16
        self.buttons = [MemoryButton(i) for i in range(16)]
        for b in self.buttons:
            self.add_item(b)
        self.selection: list[int] = []
        self.moves = 0
        self.locked = False

    async def flip(self, interaction: discord.Interaction, idx: int, button: MemoryButton):
        if self.locked or self.matched[idx] or button.label != "❓":
            await interaction.response.defer()
            return
        button.label = self.cards[idx]
        self.selection.append(idx)
        if len(self.selection) < 2:
            await interaction.response.edit_message(view=self)
            return
        self.moves += 1
        self.locked = True
        await interaction.response.edit_message(view=self)
        i1, i2 = self.selection
        if self.cards[i1] == self.cards[i2]:
            self.matched[i1] = self.matched[i2] = True
            self.selection = []
            self.locked = False
            if all(self.matched):
                pts = max(20, 200 - self.moves * 10)
                add_balance(interaction.guild.id, self.player.id, pts)
                for b in self.buttons:
                    b.disabled = True
                await interaction.message.edit(
                    content=f"🎉 خلصت اللعبة بعدد **{self.moves}** محاولة! (+{pts} نقطة)", view=self)
                self.stop()
            return
        await asyncio.sleep(1.2)
        self.buttons[i1].label = "❓"
        self.buttons[i2].label = "❓"
        self.selection = []
        self.locked = False
        try:
            await interaction.message.edit(view=self)
        except discord.NotFound:
            pass


@bot.command(name="اكشف")
async def memory_game_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "اكشف (لعبة الذاكرة)")
    try:
        view = MemoryView(ctx.author)
        await ctx.send(f"🧠 {ctx.author.mention} لعبة الذاكرة! دور بطاقتين متطابقتين لين تلقى كل الأزواج.", view=view)
        await view.wait()
    finally:
        unmark_busy(ctx.channel.id)


# ============================================================
# 7) ألعاب التحدي المباشر (شخص ضد شخص) — تبدأ بدعوة قبول/رفض
# ============================================================
class ChallengeView(discord.ui.View):
    """رسالة تحدي فيها زرين: موافقة / رفض، موجهة للخصم المذكور بس."""

    def __init__(self, host: discord.Member, opponent: discord.Member, game_name: str):
        super().__init__(timeout=60)
        self.host = host
        self.opponent = opponent
        self.game_name = game_name
        self.result: bool | None = None  # None = ما رد بعد، True = وافق، False = رفض
        self.message: discord.Message | None = None

    @discord.ui.button(label="✅ موافقة", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("⚠️ هذا التحدي مو لك.", ephemeral=True)
            return
        self.result = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {self.opponent.mention} وافق على تحدي **{self.game_name}**! يبدأ الحين...", view=self)
        self.stop()

    @discord.ui.button(label="❌ رفض", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("⚠️ هذا التحدي مو لك.", ephemeral=True)
            return
        self.result = False
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.opponent.mention} رفض تحدي **{self.game_name}**.", view=self)
        self.stop()

    async def on_timeout(self):
        if self.result is None and self.message:
            for c in self.children:
                c.disabled = True
            try:
                await self.message.edit(
                    content=f"⏳ خلص الوقت! {self.opponent.mention} ما رد على تحدي **{self.game_name}**.", view=self)
            except discord.NotFound:
                pass


async def send_challenge(ctx: commands.Context, opponent: discord.Member, game_name: str) -> bool:
    """يرسل دعوة تحدي للخصم وينتظر رده. يرجع True لو وافق، False لو رفض أو ما رد."""
    view = ChallengeView(ctx.author, opponent, game_name)
    msg = await ctx.send(
        f"⚔️ {ctx.author.mention} يتحداك يا {opponent.mention} بلعبة **{game_name}**! تبي تلعب؟", view=view)
    view.message = msg
    await view.wait()
    return view.result is True


class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x, self.y = x, y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user != view.current_player:
            await interaction.response.send_message("⏳ مو دورك!", ephemeral=True)
            return
        self.style = discord.ButtonStyle.danger if view.current_symbol == "X" else discord.ButtonStyle.success
        self.label = view.current_symbol
        self.disabled = True
        view.board[self.y][self.x] = view.current_symbol
        winner_symbol = view.check_winner()
        if winner_symbol:
            winner = view.player_x if winner_symbol == "X" else view.player_o
            for c in view.children:
                c.disabled = True
            add_balance(interaction.guild.id, winner.id, 50)
            await interaction.response.edit_message(content=f"🏆 فاز {winner.mention}! (+50 نقطة)", view=view)
            view.stop()
            return
        if view.is_full():
            for c in view.children:
                c.disabled = True
            await interaction.response.edit_message(content="🤝 تعادل!", view=view)
            view.stop()
            return
        view.switch_turn()
        await interaction.response.edit_message(
            content=f"🎮 دور {view.current_player.mention} ({view.current_symbol})", view=view
        )


class TicTacToeView(discord.ui.View):
    def __init__(self, player_x: discord.Member, player_o: discord.Member):
        super().__init__(timeout=180)
        self.player_x, self.player_o = player_x, player_o
        self.current_player, self.current_symbol = player_x, "X"
        self.board = [[None, None, None] for _ in range(3)]
        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def switch_turn(self):
        if self.current_player == self.player_x:
            self.current_player, self.current_symbol = self.player_o, "O"
        else:
            self.current_player, self.current_symbol = self.player_x, "X"

    def check_winner(self):
        b = self.board
        lines = list(b) + [[b[r][c] for r in range(3)] for c in range(3)]
        lines.append([b[i][i] for i in range(3)])
        lines.append([b[i][2 - i] for i in range(3)])
        for line in lines:
            if line[0] and line[0] == line[1] == line[2]:
                return line[0]
        return None

    def is_full(self):
        return all(all(cell for cell in row) for row in self.board)


@bot.command(name="xo")
async def xo_cmd(ctx: commands.Context, opponent: discord.Member):
    if opponent.bot or opponent == ctx.author:
        await ctx.send("⚠️ اختر عضو ثاني حقيقي غيرك.")
        return
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "XO")
    try:
        accepted = await send_challenge(ctx, opponent, "XO")
        if not accepted:
            return
        view = TicTacToeView(ctx.author, opponent)
        await ctx.send(
            f"🎮 **XO**: {ctx.author.mention} (X) ضد {opponent.mention} (O)\n🎯 دور {ctx.author.mention}", view=view
        )
        await view.wait()
    finally:
        unmark_busy(ctx.channel.id)


class RPSView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=60)
        self.p1, self.p2 = p1, p2
        self.choices: dict[int, str] = {}

    async def handle_choice(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await interaction.response.send_message("⚠️ هذا التحدي مو لك.", ephemeral=True)
            return
        if interaction.user.id in self.choices:
            await interaction.response.send_message("✅ اخترت مسبقًا.", ephemeral=True)
            return
        self.choices[interaction.user.id] = choice
        await interaction.response.send_message(f"اخترت: {choice} ✅", ephemeral=True)
        if len(self.choices) == 2:
            c1, c2 = self.choices[self.p1.id], self.choices[self.p2.id]
            result = self._decide(c1, c2)
            for c in self.children:
                c.disabled = True
            emoji = {"حجر": "🪨", "ورقة": "📄", "مقص": "✂️"}
            text = f"{self.p1.mention}: {emoji[c1]} {c1}\n{self.p2.mention}: {emoji[c2]} {c2}\n\n"
            if result == 0:
                text += "🤝 تعادل!"
            elif result == 1:
                text += f"🏆 فاز {self.p1.mention}! (+30 نقطة)"
                add_balance(interaction.guild.id, self.p1.id, 30)
            else:
                text += f"🏆 فاز {self.p2.mention}! (+30 نقطة)"
                add_balance(interaction.guild.id, self.p2.id, 30)
            await interaction.message.edit(content=text, view=self)
            self.stop()

    @staticmethod
    def _decide(c1, c2):
        if c1 == c2:
            return 0
        beats = {"حجر": "مقص", "مقص": "ورقة", "ورقة": "حجر"}
        return 1 if beats[c1] == c2 else 2

    @discord.ui.button(label="🪨 حجر", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction, button):
        await self.handle_choice(interaction, "حجر")

    @discord.ui.button(label="📄 ورقة", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction, button):
        await self.handle_choice(interaction, "ورقة")

    @discord.ui.button(label="✂️ مقص", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction, button):
        await self.handle_choice(interaction, "مقص")


@bot.command(name="حجرة", aliases=["rps"])
async def rps_cmd(ctx: commands.Context, opponent: discord.Member):
    if opponent.bot or opponent == ctx.author:
        await ctx.send("⚠️ اختر عضو ثاني حقيقي غيرك.")
        return
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "حجرة ورقة مقص")
    try:
        accepted = await send_challenge(ctx, opponent, "حجرة ورقة مقص")
        if not accepted:
            return
        view = RPSView(ctx.author, opponent)
        await ctx.send(
            f"✂️ **حجرة ورقة مقص**: {ctx.author.mention} ضد {opponent.mention}\nكل واحد يضغط بالخفاء 👇", view=view
        )
        await view.wait()
    finally:
        unmark_busy(ctx.channel.id)


# ============================================================
# 8) نظام اللوبي العام (للألعاب الجماعية — انضمام/خروج/بدء، 30 ثانية، حتى 20 لاعب)
# ============================================================
class GameLobby(discord.ui.View):
    def __init__(self, host: discord.Member, game_title: str, min_players: int = 3,
                 max_players: int = 20, countdown: int = 30):
        super().__init__(timeout=countdown + 30)
        self.host = host
        self.game_title = game_title
        self.min_players = min_players
        self.max_players = max_players
        self.players: list[discord.Member] = [host]
        self.started = False
        self.start_event = asyncio.Event()

    def status_text(self) -> str:
        names = "، ".join(m.mention for m in self.players)
        return (
            f"🎮 **{self.game_title} — بانتظار اللاعبين** ({len(self.players)}/{self.max_players})\n"
            f"{names}\n\n"
            f"اضغط 🎮 **انضمام** للدخول، 🚪 **خروج** للانسحاب، "
            f"أو المضيف {self.host.mention} يضغط ▶️ **بدء الآن** (أدنى عدد: {self.min_players})\n"
            f"⏳ تبدأ تلقائيًا خلال {self.host_countdown_text if hasattr(self, 'host_countdown_text') else '30'} ثانية."
        )

    @discord.ui.button(label="🎮 انضمام", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.bot:
            await interaction.response.send_message("⚠️ البوتات ما تنلعب.", ephemeral=True)
            return
        if interaction.user in self.players:
            await interaction.response.send_message("✅ أنت منضم مسبقًا.", ephemeral=True)
            return
        if len(self.players) >= self.max_players:
            await interaction.response.send_message("⚠️ اللوبي مكتمل (20 لاعب).", ephemeral=True)
            return
        self.players.append(interaction.user)
        await interaction.response.edit_message(content=self.status_text(), view=self)

    @discord.ui.button(label="🚪 خروج", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.players:
            await interaction.response.send_message("⚠️ أنت مو منضم أصلًا.", ephemeral=True)
            return
        self.players.remove(interaction.user)
        if interaction.user == self.host and self.players:
            self.host = self.players[0]
        await interaction.response.edit_message(content=self.status_text(), view=self)

    @discord.ui.button(label="▶️ بدء الآن", style=discord.ButtonStyle.primary)
    async def start_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.host:
            await interaction.response.send_message("⚠️ بس المضيف يقدر يبدأ مبكرًا.", ephemeral=True)
            return
        if len(self.players) < self.min_players:
            await interaction.response.send_message(f"⚠️ لازم {self.min_players} لاعبين على الأقل.", ephemeral=True)
            return
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.started = True
        self.start_event.set()


async def run_lobby(ctx: commands.Context, game_title: str, min_players: int = 3,
                     max_players: int = 20, countdown: int = 30):
    """يفتح لوبي جماعي، ويرجع قائمة اللاعبين إذا اكتمل العدد الأدنى، وإلا يرجع None."""
    if ctx.author.bot:
        return None
    lobby = GameLobby(ctx.author, game_title, min_players, max_players, countdown)
    lobby.host_countdown_text = str(countdown)
    msg = await ctx.send(lobby.status_text(), view=lobby)
    try:
        await asyncio.wait_for(lobby.start_event.wait(), timeout=countdown)
    except asyncio.TimeoutError:
        pass
    for c in lobby.children:
        c.disabled = True
    try:
        await msg.edit(content=lobby.status_text(), view=lobby)
    except discord.NotFound:
        pass
    if len(lobby.players) < min_players:
        await ctx.send(f"❌ ما اكتمل العدد الأدنى ({min_players} لاعبين) — تم إلغاء لعبة **{game_title}**.")
        return None
    return lobby.players


# ============================================================
# 9) الألعاب الجماعية (تعتمد على اللوبي)
# ============================================================
# ---------- روليت روسي ----------
class RouletteView(discord.ui.View):
    def __init__(self, players: list[discord.Member]):
        super().__init__(timeout=180)
        self.remaining = players.copy()
        self.chosen: discord.Member | None = None
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for member in self.remaining:
            if member == self.chosen:
                continue
            btn = discord.ui.Button(label=member.display_name, style=discord.ButtonStyle.danger)
            btn.callback = self._make_callback(member)
            self.add_item(btn)

    def _make_callback(self, target: discord.Member):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.chosen:
                await interaction.response.send_message("⚠️ مو دورك!", ephemeral=True)
                return
            self.remaining.remove(target)
            if len(self.remaining) == 1:
                winner = self.remaining[0]
                for c in self.children:
                    c.disabled = True
                add_balance(interaction.guild.id, winner.id, 100)
                await interaction.response.edit_message(
                    content=f"💀 تم إقصاء {target.mention}!\n\n🏆 الناجي: {winner.mention}! (+100 نقطة) 🎉", view=self
                )
                self.stop()
                return
            self.chosen = random.choice(self.remaining)
            self._build_buttons()
            names = "، ".join(m.mention for m in self.remaining)
            await interaction.response.edit_message(
                content=f"💀 تم إقصاء {target.mention}!\n\n🎡 الباقين: {names}\n🎯 دور {self.chosen.mention} يختار!",
                view=self,
            )
        return callback


@bot.command(name="روليت")
async def roulette_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "روليت")
    try:
        players = await run_lobby(ctx, "🎡 الروليت الروسي", min_players=3, max_players=20, countdown=30)
        if not players:
            return
        view = RouletteView(players)
        view.chosen = random.choice(players)
        view._build_buttons()
        names = "، ".join(p.mention for p in players)
        await ctx.send(f"🎡 **بدأت اللعبة!**\n{names}\n\n🎯 دور {view.chosen.mention} يختار وحد يطلعه!", view=view)
        await view.wait()
    finally:
        unmark_busy(ctx.channel.id)


# ---------- نرد ----------
@bot.command(name="نرد")
async def dice_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "نرد")
    try:
        players = await run_lobby(ctx, "🎲 لعبة النرد", min_players=2, max_players=20, countdown=30)
        if not players:
            return
        rolls = {p: random.randint(1, 6) for p in players}
        top = max(rolls.values())
        winners = [p for p in players if rolls[p] == top]
        lines = "\n".join(f"{p.mention}: 🎲 {rolls[p]}" for p in players)
        for w in winners:
            add_balance(ctx.guild.id, w.id, 60)
        winners_text = " و ".join(w.mention for w in winners)
        extra = " لكل واحد" if len(winners) > 1 else ""
        await ctx.send(f"🎲 **نتائج الرمي:**\n{lines}\n\n🏆 الفائز: {winners_text} (+60 نقطة{extra})")
    finally:
        unmark_busy(ctx.channel.id)


# ---------- عجلة الحظ ----------
@bot.command(name="عجلة")
async def wheel_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "عجلة الحظ")
    try:
        players = await run_lobby(ctx, "🎡 عجلة الحظ", min_players=2, max_players=20, countdown=30)
        if not players:
            return
        msg = await ctx.send("🎡 العجلة تدور...")
        await asyncio.sleep(2)
        winner = random.choice(players)
        pts = random.randint(50, 150)
        add_balance(ctx.guild.id, winner.id, pts)
        await msg.edit(content=f"🎡 توقفت العجلة عند... 🎉 {winner.mention}! (+{pts} نقطة)")
    finally:
        unmark_busy(ctx.channel.id)


# ---------- غميضة ----------
@bot.command(name="غميضة")
async def hideseek_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "غميضة")
    try:
        await _run_hideseek(ctx)
    finally:
        unmark_busy(ctx.channel.id)


async def _run_hideseek(ctx: commands.Context):
    players = await run_lobby(ctx, "🙈 غميضة", min_players=3, max_players=20, countdown=30)
    if not players:
        return
    seeker = random.choice(players)
    hiders = [p for p in players if p != seeker][:10]
    spots = list(range(1, 11))
    random.shuffle(spots)
    hidden_spots = {p: spots[i] for i, p in enumerate(hiders)}
    found = set()
    attempts = len(hidden_spots) + 4
    await ctx.send(
        f"🙈 {seeker.mention} هو الباحث! الباقين مختبئين بأرقام من 1 إلى 10.\n"
        f"اكتب رقم للبحث فيه (عندك {attempts} محاولة)."
    )
    for _ in range(attempts):
        def check(m: discord.Message):
            return m.channel == ctx.channel and m.author == seeker and m.content.strip().isdigit()

        try:
            m = await bot.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            await ctx.send("⏳ خلص وقت الباحث!")
            break
        guess = int(m.content.strip())
        hit = None
        for p, spot in hidden_spots.items():
            if spot == guess and p not in found:
                hit = p
                break
        if hit:
            found.add(hit)
            add_balance(ctx.guild.id, seeker.id, 20)
            await ctx.send(f"🎯 لقيت {hit.mention}!")
            if len(found) == len(hidden_spots):
                break
        else:
            await ctx.send("❌ ما فيه أحد بهذا الرقم.")
    for p in hidden_spots:
        if p not in found:
            add_balance(ctx.guild.id, p.id, 40)
    remaining = len(hidden_spots) - len(found)
    await ctx.send(f"🏁 انتهت اللعبة! {seeker.mention} لقى **{len(found)}** وبقي **{remaining}** مختبئين ماله دري عنهم.")


# ---------- ريبلكا (احفظ الترتيب) ----------
@bot.command(name="ريبلكا")
async def replica_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "ريبلكا (احفظ الترتيب)")
    players = await run_lobby(ctx, "🔁 ريبلكا (احفظ الترتيب)", min_players=2, max_players=20, countdown=30)
    if not players:
        unmark_busy(ctx.channel.id)
        return
    pool = ["🔥", "💧", "🌪️", "🌙", "⭐", "🍀", "⚡", "🎵", "🎯", "🧩"]
    sequence = random.sample(pool, k=5)
    seq_text = " ".join(sequence)
    msg = await ctx.send(f"🔁 احفظوا هذا الترتيب:\n\n# {seq_text}")
    await asyncio.sleep(5)
    try:
        await msg.edit(content="🔁 **ريبلكا**: اكتبوا نفس الترتيب بالضبط (افصلوا بمسافة)!")
    except discord.NotFound:
        pass
    allowed = {p.id for p in players}
    unmark_busy(ctx.channel.id)  # نسلّم القفل لنظام الجولة اللي بيدير حالته بنفسه لين الحل أو انتهاء الوقت
    await start_round(ctx.channel, title="ريبلكا", prompt="اكتبوا الترتيب اللي حفظتوه 👆",
                       checker=lambda c: normalize(c) == normalize(seq_text),
                       reward=(60, 100), allowed_ids=allowed, timeout=30, reveal=seq_text)


# ---------- مافيا (نسخة مبسطة: جولة تصويت وحدة) ----------
@bot.command(name="مافيا")
async def mafia_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "مافيا")
    try:
        await _run_mafia(ctx)
    finally:
        unmark_busy(ctx.channel.id)


async def _run_mafia(ctx: commands.Context):
    players = await run_lobby(ctx, "🕵️ مافيا", min_players=4, max_players=20, countdown=30)
    if not players:
        return
    mafia_count = max(1, len(players) // 4)
    mafia = set(random.sample(players, mafia_count))
    for p in players:
        role = "🔪 أنت مافيا! هدفك تضلل الكل وتفلت." if p in mafia else "😇 أنت مواطن! هدفك تكتشف المافيا."
        try:
            await p.send(f"🕵️ لعبة مافيا بسيرفر **{ctx.guild.name}**:\n{role}")
        except discord.Forbidden:
            pass
    await ctx.send(
        f"🕵️ بدأت اللعبة! فيه **{mafia_count}** من المافيا بينكم.\n"
        f"ناقشوا 60 ثانية، وصوّتوا بكتابة: `تصويت @الشخص`"
    )

    def check(m: discord.Message):
        return (m.channel == ctx.channel and m.author in players
                and m.content.strip().startswith("تصويت") and m.mentions)

    votes: dict[int, discord.Member] = {}
    end_time = datetime.now(timezone.utc) + timedelta(seconds=60)
    while True:
        remaining = (end_time - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            break
        try:
            m = await bot.wait_for("message", check=check, timeout=remaining)
        except asyncio.TimeoutError:
            break
        target = m.mentions[0]
        if target in players:
            votes[m.author.id] = target

    if not votes:
        await ctx.send("⏳ ما صوّت أحد! انتهت اللعبة بدون نتيجة.")
        return

    tally: dict[discord.Member, int] = {}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1
    eliminated = max(tally, key=tally.get)
    was_mafia = eliminated in mafia

    if was_mafia:
        winners = [p for p in players if p not in mafia]
        result = f"✅ {eliminated.mention} كان من المافيا! فاز المواطنون 🎉"
    else:
        winners = list(mafia)
        result = f"❌ {eliminated.mention} كان بريء! فازت المافيا 🕵️"

    for w in winners:
        add_balance(ctx.guild.id, w.id, 50)
    mafia_names = "، ".join(m.mention for m in mafia)
    await ctx.send(f"{result}\n\nالمافيا كانوا: {mafia_names}")


# ---------- كراسي موسيقية ----------
class ChairsView(discord.ui.View):
    def __init__(self, players: list[discord.Member]):
        super().__init__(timeout=15)
        self.remaining = players.copy()
        self.taken: set[int] = set()
        chairs = max(1, len(players) - 1)
        for i in range(chairs):
            btn = discord.ui.Button(label=f"🪑 كرسي {i + 1}", style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(btn)
            self.add_item(btn)

    def _make_cb(self, btn: discord.ui.Button):
        async def cb(interaction: discord.Interaction):
            if interaction.user not in self.remaining:
                await interaction.response.send_message("⚠️ أنت مو باللعبة.", ephemeral=True)
                return
            if interaction.user.id in self.taken:
                await interaction.response.send_message("✅ عندك كرسي مسبقًا.", ephemeral=True)
                return
            if btn.disabled:
                await interaction.response.send_message("❌ هذا الكرسي مأخوذ.", ephemeral=True)
                return
            btn.disabled = True
            btn.label = f"🪑 {interaction.user.display_name}"
            btn.style = discord.ButtonStyle.success
            self.taken.add(interaction.user.id)
            await interaction.response.edit_message(view=self)
        return cb


@bot.command(name="كراسي")
async def chairs_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "كراسي")
    try:
        await _run_chairs(ctx)
    finally:
        unmark_busy(ctx.channel.id)


async def _run_chairs(ctx: commands.Context):
    players = await run_lobby(ctx, "🪑 الكراسي الموسيقية", min_players=3, max_players=20, countdown=30)
    if not players:
        return
    round_num = 1
    while len(players) > 1:
        view = ChairsView(players)
        msg = await ctx.send(
            f"🪑 **الجولة {round_num}**: {len(players)} لاعبين و {max(1, len(players) - 1)} كرسي! بسرعة اقعدوا 👇",
            view=view)
        await asyncio.sleep(12)
        for c in view.children:
            c.disabled = True
        try:
            await msg.edit(view=view)
        except discord.NotFound:
            pass
        out = [p for p in players if p.id not in view.taken]
        eliminated = random.choice(out) if out else random.choice(players)
        players = [p for p in players if p != eliminated]
        if players:
            await ctx.send(f"💥 طاح {eliminated.mention}! الباقين: {'، '.join(p.mention for p in players)}")
        round_num += 1
    if players:
        winner = players[0]
        add_balance(ctx.guild.id, winner.id, 100)
        await ctx.send(f"🏆 فاز {winner.mention} بلعبة الكراسي! (+100 نقطة)")


# ============================================================
# 10) مركز الألعاب: .العاب و .شرح  +  .اوامر
# ============================================================
GAME_LIST = {
    "جماعية": [
        (".روليت", "روليت روسي: يقصّون بعض لين يبقى ناجي وحد."),
        (".xo @خصمك", "اكس أو بينك وبين خصم تحدده."),
        (".مافيا", "مافيا مبسّطة: تصويت جولة وحدة تحدد الفايز."),
        (".كراسي", "الكراسي الموسيقية بالأزرار."),
        (".حجرة @خصمك", "حجرة ورقة مقص بينك وبين خصم."),
        (".نرد", "كل واحد يرمي نرد، الأعلى يفوز."),
        (".عجلة", "عجلة حظ تختار فايز عشوائي."),
        (".غميضة", "وحد يبحث عن الباقين المختبئين بأرقام."),
        (".ريبلكا", "احفظوا ترتيب الرموز واكتبوه صح."),
        (".خمن [أقصى رقم]", "تخمين رقم سري بالشات."),
        (".كلمة", "قول كلمة تبدأ بآخر حرف من الكلمة المعطاة."),
    ],
    "فردية": [
        (".زر", "اضغط الزر أول ما يصير أخضر."),
        (".اسرع", "أعد كتابة الجملة بأسرع وقت."),
        (".فكك", "رتب حروف الكلمة المبعثرة."),
        (".ادمج", "خمن الكلمة من دمج رمزين."),
        (".اعلام", "خمن الدولة من علمها."),
        (".اعكس", "اكتب الكلمة بالعكس."),
        (".حرف", "اذكر كلمة بالفئة المطلوبة تبدأ بحرف معين."),
        (".صحح", "صحح الكلمة المكتوبة غلط."),
        (".ترتيب", "رتب الأرقام تصاعديًا."),
        (".الوان", "خمن اللون من الرمز."),
        (".ايموجي", "خمن الكلمة من الرمز التعبيري."),
        (".اكشف", "لعبة الذاكرة، طابق البطاقات."),
    ],
}

GAME_HELP = {
    "روليت": "الكل ينضم باللوبي، وبعدها اللاعب المختار يطلع وحد من اللعبة كل دور، لين يبقى ناجي وحد وياخذ النقاط.",
    "xo": "اكس أو كلاسيكية بينك وبين عضو تحدده بالمنشن، أول وحد يكمل خط يفوز.",
    "مافيا": "ينضم اللاعبين، يتوزعون أدوار مافيا/مواطنين بالخاص، تناقشون دقيقة وتصوتون بـ `تصويت @الشخص`، ومين يطلع أكثر أصوات يتم كشفه.",
    "كراسي": "كل جولة عدد الكراسي أقل من عدد اللاعبين بواحد، اضغطوا الأزرار بسرعة، اللي ما يحصل كرسي يطيح.",
    "حجرة": "حجرة ورقة مقص بينك وبين خصم، كل واحد يختار بالخفاء والنتيجة تبان بعد اختيار الاثنين.",
    "نرد": "كل لاعب يرمي نرد تلقائيًا، وصاحب أعلى رقم يفوز بالنقاط.",
    "عجلة": "بعد ما يكتمل اللوبي، العجلة تدور وتختار فايز عشوائي من المنضمين.",
    "غميضة": "لاعب وحد يصير الباحث، والباقين يتوزعون على أرقام من 1-10 بالخفاء، والباحث يخمن الأرقام يلقاهم.",
    "ريبلكا": "تشوفون ترتيب رموز لمدة 5 ثواني، وبعدها لازم تكتبونه بنفس الترتيب بالضبط، أول وحد يجاوب صح يفوز.",
    "خمن": "البوت يختار رقم سري بين 1 والرقم اللي تحدده، واكتبوا تخمينكم بالشات وبيعطيكم تلميح فوق/تحت.",
    "كلمة": "يعطيكم البوت كلمة، وأول وحد يكتب كلمة تبدأ بآخر حرف منها يفوز بالنقاط.",
    "زر": "البوت يقول استعدوا، وبعد وقت عشوائي يصير الزر أخضر، أول ضغطة تفوز.",
    "اسرع": "البوت يعطي جملة، وأول وحد يعيد كتابتها بالضبط يفوز.",
    "فكك": "البوت يبعثر حروف كلمة، وأول وحد يرتبها صح يفوز.",
    "ادمج": "رمزين مع بعض يمثلون كلمة، خمنوا الكلمة اللي يدل عليها الدمج.",
    "اعلام": "البوت يعرض علم دولة، وأول وحد يكتب اسم الدولة صح يفوز.",
    "اعكس": "البوت يعطي كلمة، واكتبوها بالعكس (آخر حرف أول حرف).",
    "حرف": "البوت يحدد فئة وحرف، وأول وحد يذكر كلمة من الفئة تبدأ بنفس الحرف يفوز.",
    "صحح": "البوت يكتب كلمة غلط إملائيًا، وأول وحد يصححها صح يفوز.",
    "ترتيب": "البوت يعطي 6 أرقام مبعثرة، رتبوها تصاعديًا وافصلوا بينها بمسافة.",
    "الوان": "البوت يعرض رمز، وقولوا وش اللون المرتبط فيه.",
    "ايموجي": "البوت يعرض رمز تعبيري وحد، وخمنوا وش يمثل.",
    "اكشف": "لعبة ذاكرة فردية، دور بطاقتين متطابقتين من شبكة 16 بطاقة بأقل عدد محاولات ممكن.",
}


@bot.command(name="العاب")
async def games_list_cmd(ctx: commands.Context):
    lines = ["🎮 **مركز الألعاب**\n", "__ألعاب جماعية (تبدأ بلوبي 30 ثانية)__"]
    for cmd, desc in GAME_LIST["جماعية"]:
        lines.append(f"`{cmd}` — {desc}")
    lines.append("\n__ألعاب فردية__")
    for cmd, desc in GAME_LIST["فردية"]:
        lines.append(f"`{cmd}` — {desc}")
    lines.append("\n⭐ اكتب `.نقاطي` عشان تشوف رصيدك.")
    lines.append("📖 اكتب `.شرح اسم_اللعبة` (بدون النقطة داخل الاسم) عشان أشرحلك أي لعبة بالتفصيل.")
    lines.append("📋 اكتب `.اوامر` عشان تشوف باقي الأوامر.")
    await ctx.send("\n".join(lines))


@bot.command(name="شرح")
async def explain_cmd(ctx: commands.Context, *, game_name: str = None):
    if not game_name:
        await ctx.send("⚠️ اكتب: `.شرح اسم اللعبة` — مثال: `.شرح روليت`")
        return
    key = game_name.strip()
    if key not in GAME_HELP:
        await ctx.send("⚠️ ما لقيت هذي اللعبة بالاسم ذا، اكتب `.العاب` عشان تشوف القائمة والأسماء الصحيحة.")
        return
    await ctx.send(f"📖 **{key}**:\n{GAME_HELP[key]}")


# ---------- .اوامر: قائمة كل الأوامر اللي تبدأ بنقطة (ما عدا الألعاب) ----------
@bot.command(name="اوامر", aliases=["الاوامر"])
async def commands_list_cmd(ctx: commands.Context):
    lines = [
        "📋 **قائمة الأوامر** (كلها تبدأ بـ `.`)\n",
        "__⭐ النقاط والاقتصاد__",
        "`.رصيد [@عضو]` — تشوف رصيدك أو رصيد عضو ثاني.",
        "`.نقاطي` — تشوف رصيد نقاطك.",
        "`.يومي` — تاخذ جائزتك اليومية (مرة كل 24 ساعة).",
        "`.تحويل @عضو المبلغ` — تحول نقاط لعضو ثاني.",
        "\n__⚠️ التنبيهات__",
        "`.تنبيهاته [@عضو]` — تشوف عدد التنبيهات المسجلة على عضو (أو عليك).",
        "\n__🎮 الألعاب__",
        "`.العاب` — قائمة كل الألعاب (الجماعية والفردية).",
        "`.شرح اسم_اللعبة` — شرح أي لعبة بالتفصيل.",
        "\n__ℹ️ عام__",
        "`.اوامر` — تعرض هذي القائمة.",
    ]
    await ctx.send("\n".join(lines))


# ============================================================
# 11) نظام الإدارة الكامل — بدون بريفكس، حسب الرتب
# ============================================================
OWNER = "Owner"
CO_OWNER = "Co-Owner"
EXECUTIVE = "Executive"
ADMINISTRATOR = "Administrator"
SR_MODERATOR = "Senior Moderator"
MODERATOR = "Moderator"
JR_MODERATOR = "Junior Moderator"
SUPPORT = "Support"
HELPER = "Helper"

ADMIN_ROLES = [ADMINISTRATOR, EXECUTIVE, CO_OWNER, OWNER]
JR_MOD_ROLES = [JR_MODERATOR, MODERATOR, SR_MODERATOR] + ADMIN_ROLES
HELPER_ROLES = [HELPER, SUPPORT] + JR_MOD_ROLES
MOD_ROLES = [MODERATOR, SR_MODERATOR] + ADMIN_ROLES


def has_role(member: discord.Member, allowed: list[str]) -> bool:
    names = {r.name for r in member.roles}
    return any(n in names for n in allowed)


def strip_mentions(content: str, mentions) -> str:
    for m in mentions:
        content = content.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
    return content.strip()


def parse_duration(text: str) -> timedelta:
    """يفهم صيغ زي: 10 / 10m / 10h / 10d / 10س / 10د / 10ي — افتراضي 10 دقائق."""
    text = text.strip().split()[0] if text.strip() else ""
    match = re.match(r"^(\d+)\s*([smhdدسي]?)$", text)
    if not match:
        return timedelta(minutes=10)
    value, unit = int(match.group(1)), match.group(2)
    if unit in ("h", "س"):
        return timedelta(hours=value)
    if unit in ("d", "ي"):
        return timedelta(days=value)
    if unit == "s":
        return timedelta(seconds=value)
    return timedelta(minutes=value)  # افتراضي دقائق (m أو د أو بدون وحدة)


async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, reason="نظام الإدارة - إنشاء تلقائي")
    return role


async def reply(message: discord.Message, text: str):
    await message.channel.send(text, delete_after=8)


async def cleanup(message: discord.Message):
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass


# ---------- إدارة الأعضاء ----------
async def cmd_ban(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `برا @العضو السبب`")
        return
    target = message.mentions[0]
    reason = strip_mentions(args, message.mentions) or "لم يُذكر سبب"
    await cleanup(message)
    try:
        await target.ban(reason=reason)
        await reply(message, f"🔨 تم حظر {target.mention} — السبب: {reason}")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أحظر هذا العضو (صلاحياتي أقل من رتبته).")


async def cmd_unban(message: discord.Message, args: str):
    arg = args.strip()
    if not arg.isdigit():
        await reply(message, "⚠️ الصيغة: `سماح <آيدي العضو>` (لازم الآيدي رقمي لأن العضو مو بالسيرفر)")
        return
    await cleanup(message)
    try:
        user = discord.Object(id=int(arg))
        await message.guild.unban(user, reason=f"بواسطة {message.author}")
        await reply(message, f"✅ تم فك الحظر عن المستخدم `{arg}`")
    except discord.NotFound:
        await reply(message, "❌ ما فيه حظر بهذا الآيدي.")


async def cmd_kick(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `ترحيل @العضو السبب`")
        return
    target = message.mentions[0]
    reason = strip_mentions(args, message.mentions) or "لم يُذكر سبب"
    await cleanup(message)
    try:
        await target.kick(reason=reason)
        await reply(message, f"👢 تم طرد {target.mention} — السبب: {reason}")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أطرد هذا العضو.")


async def cmd_timeout(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تايم @العضو 10m السبب` (افتراضي 10 دقائق)")
        return
    target = message.mentions[0]
    remainder = strip_mentions(args, message.mentions)
    duration = parse_duration(remainder)
    reason = " ".join(remainder.split()[1:]) if remainder.split() else "لم يُذكر سبب"
    await cleanup(message)
    try:
        await target.timeout(discord.utils.utcnow() + duration, reason=reason)
        await reply(message, f"⏱️ تم إعطاء {target.mention} تايم لمدة {duration}")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أعطي هذا العضو تايم.")


async def cmd_untimeout(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تحرير @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    await target.timeout(None, reason=f"بواسطة {message.author}")
    await reply(message, f"✅ تم فك التايم عن {target.mention}")


async def cmd_textmute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `اخرس @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    role = await ensure_role(message.guild, MUTE_ROLE_NAME)
    await target.add_roles(role, reason=f"بواسطة {message.author}")
    await reply(message, f"🔇 تم إسكات {target.mention} بالشات")


async def cmd_textunmute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تكلم @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    role = discord.utils.get(message.guild.roles, name=MUTE_ROLE_NAME)
    if role and role in target.roles:
        await target.remove_roles(role, reason=f"بواسطة {message.author}")
    await reply(message, f"🔊 تم فك الإسكات عن {target.mention}")


async def cmd_jail(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `سجن @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    jail_role = await ensure_role(message.guild, JAIL_ROLE_NAME)

    keep_roles = [r for r in target.roles if r.name != "@everyone"]
    data = load_json(JAIL_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    data.setdefault(gid, {})
    data[gid][mid] = [r.id for r in keep_roles]
    save_json(JAIL_FILE, data)

    try:
        await target.remove_roles(*keep_roles, reason="سجن")
        await target.add_roles(jail_role, reason=f"سجن بواسطة {message.author}")
        await reply(message, f"🔒 تم سجن {target.mention}")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أسجن هذا العضو.")


async def cmd_unjail(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `فك @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    data = load_json(JAIL_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    saved_ids = data.get(gid, {}).get(mid, [])
    roles = [message.guild.get_role(rid) for rid in saved_ids if message.guild.get_role(rid)]

    jail_role = discord.utils.get(message.guild.roles, name=JAIL_ROLE_NAME)
    if jail_role and jail_role in target.roles:
        await target.remove_roles(jail_role, reason="فك السجن")
    if roles:
        await target.add_roles(*roles, reason="فك السجن — استرجاع الرتب")
        data[gid].pop(mid, None)
        save_json(JAIL_FILE, data)
    await reply(message, f"🔓 تم فك السجن عن {target.mention}")


async def cmd_nick(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `لقب @العضو الاسم_الجديد`")
        return
    target = message.mentions[0]
    new_nick = strip_mentions(args, message.mentions)
    await cleanup(message)
    if not new_nick:
        await reply(message, "⚠️ لازم تكتب اللقب الجديد.")
        return
    try:
        await target.edit(nick=new_nick, reason=f"بواسطة {message.author}")
        await reply(message, f"✏️ تم تغيير لقب {target.mention} إلى **{new_nick}**")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أغيّر لقب هذا العضو.")


async def cmd_remove_role(message: discord.Message, args: str):
    if not message.mentions or not message.role_mentions:
        await reply(message, "⚠️ الصيغة: `تنزيل @العضو @الرتبة`")
        return
    target = message.mentions[0]
    role = message.role_mentions[0]
    await cleanup(message)
    if role not in target.roles:
        await reply(message, f"⚠️ {target.mention} أصلًا ما عنده رتبة {role.name}")
        return
    await target.remove_roles(role, reason=f"بواسطة {message.author}")
    data = load_json(ROLES_REMOVED_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    data.setdefault(gid, {})
    data[gid][mid] = role.id
    save_json(ROLES_REMOVED_FILE, data)
    await reply(message, f"📤 تم سحب رتبة {role.name} من {target.mention}")


async def cmd_restore_role(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `رجع @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    data = load_json(ROLES_REMOVED_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    role_id = data.get(gid, {}).get(mid)
    if not role_id:
        await reply(message, f"⚠️ ما فيه رتبة محفوظة نرجعها لـ {target.mention}")
        return
    role = message.guild.get_role(role_id)
    if role:
        await target.add_roles(role, reason=f"بواسطة {message.author}")
        data[gid].pop(mid, None)
        save_json(ROLES_REMOVED_FILE, data)
        await reply(message, f"📥 تم إرجاع رتبة {role.name} لـ {target.mention}")


# ---------- إدارة الرومات ----------
async def cmd_purge(message: discord.Message, args: str):
    amount_text = args.strip().split()[0] if args.strip() else "50"
    amount = int(amount_text) if amount_text.isdigit() else 50
    amount = min(amount, 200)
    await message.delete()
    deleted = await message.channel.purge(limit=amount)
    await reply(message, f"🧹 تم حذف {len(deleted)} رسالة.")


async def cmd_lock(message: discord.Message, args: str):
    await cleanup(message)
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.send_messages = False
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("🔒 تم قفل الروم.")


async def cmd_unlock(message: discord.Message, args: str):
    await cleanup(message)
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.send_messages = None
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("🔓 تم فتح الروم.")


async def cmd_hide(message: discord.Message, args: str):
    await cleanup(message)
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.view_channel = False
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("🙈 تم إخفاء الروم.")


async def cmd_show(message: discord.Message, args: str):
    await cleanup(message)
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.view_channel = None
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("👁️ تم إظهار الروم.")


# ---------- إدارة الصوت ----------
async def cmd_vc_kick(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `بره @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    if target.voice and target.voice.channel:
        await target.move_to(None, reason=f"بواسطة {message.author}")
        await reply(message, f"👋 تم إخراج {target.mention} من الروم الصوتي.")
    else:
        await reply(message, "⚠️ العضو مو بروم صوتي.")


async def cmd_vc_mute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `اصمت @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    await target.edit(mute=True, reason=f"بواسطة {message.author}")
    await reply(message, f"🔇 تم إسكات {target.mention} صوتيًا.")


async def cmd_vc_unmute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `انطق @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    await target.edit(mute=False, reason=f"بواسطة {message.author}")
    await reply(message, f"🔊 تم فك الإسكات الصوتي عن {target.mention}.")


async def cmd_vc_pull(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `اسحب @العضو` (وأنت داخل روم صوتي)")
        return
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل روم صوتي عشان تسحب له أحد.")
        return
    target = message.mentions[0]
    await cleanup(message)
    if target.voice:
        await target.move_to(message.author.voice.channel, reason=f"بواسطة {message.author}")
        await reply(message, f"📥 تم سحب {target.mention} لروم {message.author.voice.channel.name}")
    else:
        await reply(message, "⚠️ العضو مو داخل أي روم صوتي حاليًا.")


async def cmd_vc_gather(message: discord.Message, args: str):
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل روم صوتي عشان تجمع الكل عندك.")
        return
    destination = message.author.voice.channel
    await cleanup(message)
    count = 0
    for vc in message.guild.voice_channels:
        if vc.id == destination.id:
            continue
        for member in list(vc.members):
            await member.move_to(destination, reason=f"تجميع بواسطة {message.author}")
            count += 1
    await reply(message, f"📦 تم جمع {count} عضو داخل {destination.name}")


async def cmd_vc_comehere(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تعال @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    if not (message.author.voice):
        await reply(message, "⚠️ لازم تكون بروم صوتي عشان يسحبك البوت... انتقل يدويًا.")
        return
    if target.voice and target.voice.channel:
        await message.author.move_to(target.voice.channel, reason="تعال")
        await reply(message, f"➡️ تم نقلك لروم {target.voice.channel.name}")
    else:
        await reply(message, "⚠️ هذا العضو مو داخل روم صوتي.")


async def cmd_vc_kicklock(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `اطلع @العضو`")
        return
    target = message.mentions[0]
    await cleanup(message)
    if not (target.voice and target.voice.channel):
        await reply(message, "⚠️ العضو مو داخل روم صوتي.")
        return
    channel = target.voice.channel
    await target.move_to(None, reason=f"بواسطة {message.author}")
    overwrite = channel.overwrites_for(message.guild.default_role)
    overwrite.connect = False
    await channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await reply(message, f"🚫 تم طرد {target.mention} وقفل روم {channel.name}")


async def cmd_vc_allow(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `مسموح @العضو` (وأنت داخل الروم الصوتي)")
        return
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل الروم الصوتي المقفول عشان تسمح لأحد.")
        return
    target = message.mentions[0]
    channel = message.author.voice.channel
    await cleanup(message)
    overwrite = channel.overwrites_for(target)
    overwrite.connect = True
    await channel.set_permissions(target, overwrite=overwrite)
    await reply(message, f"✅ تم السماح لـ {target.mention} بدخول {channel.name}")


# ---------- جدول الأوامر الإدارية ----------
ADMIN_COMMANDS = {
    # إدارة الأعضاء
    "برا": (ADMIN_ROLES, cmd_ban),
    "سماح": (ADMIN_ROLES, cmd_unban),
    "ترحيل": (JR_MOD_ROLES, cmd_kick),
    "كيك": (JR_MOD_ROLES, cmd_kick),
    "تايم": (HELPER_ROLES, cmd_timeout),
    "اص": (HELPER_ROLES, cmd_timeout),
    "تحرير": (HELPER_ROLES, cmd_untimeout),
    "اخرس": (ADMIN_ROLES, cmd_textmute),
    "تكلم": (ADMIN_ROLES, cmd_textunmute),
    "سجن": (ADMIN_ROLES, cmd_jail),
    "فك": (ADMIN_ROLES, cmd_unjail),
    "لقب": (MOD_ROLES, cmd_nick),
    "اسم": (MOD_ROLES, cmd_nick),
    "تنزيل": (ADMIN_ROLES, cmd_remove_role),
    "رجع": (ADMIN_ROLES, cmd_restore_role),
    # إدارة الرومات
    "اباده": (ADMIN_ROLES, cmd_purge),
    "مسح": (ADMIN_ROLES, cmd_purge),
    "قفل": (ADMIN_ROLES, cmd_lock),
    "فتح": (ADMIN_ROLES, cmd_unlock),
    "اخفاء": (ADMIN_ROLES, cmd_hide),
    "خفي": (ADMIN_ROLES, cmd_hide),
    "اظهار": (ADMIN_ROLES, cmd_show),
    # إدارة الصوت
    "بره": (MOD_ROLES, cmd_vc_kick),
    "اصمت": (MOD_ROLES, cmd_vc_mute),
    "انطق": (MOD_ROLES, cmd_vc_unmute),
    "اسحب": (MOD_ROLES, cmd_vc_pull),
    "اجمعهم": (MOD_ROLES, cmd_vc_gather),
    "تعال": (MOD_ROLES, cmd_vc_comehere),
    "كم هير بيبي": (MOD_ROLES, cmd_vc_comehere),
    "اطلع": (ADMIN_ROLES, cmd_vc_kicklock),
    "مسموح": (ADMIN_ROLES, cmd_vc_allow),
}

# رتّب المفاتيح الأطول أولًا (عشان "كم هير بيبي" ما تتعارض مع كلمة مفردة)
SORTED_TRIGGERS = sorted(ADMIN_COMMANDS.keys(), key=len, reverse=True)


async def try_dispatch_admin_command(message: discord.Message) -> bool:
    content = message.content.strip()
    for trigger in SORTED_TRIGGERS:
        if content == trigger or content.startswith(trigger + " "):
            allowed_roles, handler = ADMIN_COMMANDS[trigger]
            if not isinstance(message.author, discord.Member) or not has_role(message.author, allowed_roles):
                await cleanup(message)
                await reply(message, f"{message.author.mention} ❌ ما عندك صلاحية لهذا الأمر.")
                return True
            args = content[len(trigger):].strip()
            await handler(message, args)
            return True
    return False


# ============================================================
# معالج الرسائل الموحّد
# ============================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.content.strip().startswith("تنبيه"):
        await handle_warn_command(message)
        return

    if await try_dispatch_admin_command(message):
        return

    # لعبة خمن/تخمين (مفتوحة بالروم، بدون بريفكس بالرد — فيها تلميح فوق/تحت)
    game = active_guess_games.get(message.channel.id)
    if game and message.content.strip().lstrip("-").isdigit():
        guess = int(message.content.strip())
        if guess == game["number"]:
            reward = random.randint(50, 150)
            add_balance(message.guild.id, message.author.id, reward)
            await message.channel.send(f"🎉 {message.author.mention} عرف الرقم **{game['number']}**! (+{reward} نقطة)")
            del active_guess_games[message.channel.id]
            unmark_busy(message.channel.id)
        elif 0 < guess < game["number"]:
            await message.add_reaction("⬆️")
        elif guess > game["number"]:
            await message.add_reaction("⬇️")

    # الجولات العامة (فكك / اعلام / صحح / ادمج / اعكس / حرف / ترتيب / الوان / ايموجي / اسرع / كلمة / ريبلكا)
    round_info = active_rounds.get(message.channel.id)
    if round_info:
        allowed = round_info["allowed_ids"]
        if allowed is None or message.author.id in allowed:
            try:
                is_correct = round_info["checker"](message.content)
            except Exception:
                is_correct = False
            if is_correct and active_rounds.get(message.channel.id, {}).get("token") == round_info["token"]:
                del active_rounds[message.channel.id]
                unmark_busy(message.channel.id)
                lo, hi = round_info["reward"]
                pts = random.randint(lo, hi)
                add_balance(message.guild.id, message.author.id, pts)
                reveal = round_info.get("reveal", "")
                extra = f" الإجابة: **{reveal}**" if reveal else ""
                await message.channel.send(f"🎉 {message.author.mention} جاوب صح!{extra} (+{pts} نقطة)")

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول باسم {bot.user}")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("⚠️ ما لقيت هذا العضو — تأكد إنك تعمل منشن حقيقي (@) من قائمة الاقتراحات.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ ناقص معطى بالأمر. مثال صحيح: `.{ctx.command.name} @عضو`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ صيغة الأمر غلط، تأكد من كتابته صح.")
    elif isinstance(error, commands.CommandNotFound):
        return  # تجاهل الأوامر غير الموجودة بصمت
    else:
        print(f"[خطأ غير متوقع] {error}")
        await ctx.send("❌ صار خطأ غير متوقع أثناء تنفيذ الأمر.")


if __name__ == "__main__":
    # تشغيل خادم الويب في خلفية منفصلة
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()
    
    # تشغيل البوت
    bot.run(DISCORD_TOKEN)
