"""
games.py — مركز الألعاب (وحدة داخل بوت الكنترول bot.py)
=======================================================
منقول من games_bot.py كما هو: نظام الجولات + الألعاب الجماعية والفردية + .العاب + .شرح

الربط داخل bot.py (نفس طريقة tickets / protection / bank):
    import games
    games.setup_games(bot)

ملاحظات:
  - الوحدة ما تسجل on_message / on_ready / on_command_error كـ events رئيسية (عشان ما تلغي اللي بـ bot.py).
    تسجل بدلها listeners: games_on_message (تخمين الرقم + الجولات) و on_raw_message_delete (إيقاف اللعبة لو انحذفت رسالتها).
  - اللي يحتاجه bot.py منها: games.GamesRoleRequired و games.handle_games_role_error(ctx) بمعالج الأخطاء.
  - رول التشغيل: "Event Team" (GAMES_ROLE_NAME). مجلد الصور game_images بجنب bot.py.
  - النقاط تنحفظ بنفس economy.json و game_stats.json اللي يستخدمها bot.py (صار البوت واحد، فالرصيد موحّد).
  - مستقلة بالكامل: ما تستورد شي من bot.py.
"""

import discord
from discord.ext import commands
import asyncio
import itertools
import json
import math
import os
import re
import random
from io import BytesIO
from datetime import datetime, timezone, timedelta

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

ECONOMY_FILE = "economy.json"
GAME_STATS_FILE = "game_stats.json"

# الحد الأقصى للنقاط اللي يقدر اللاعب ياخذها من الألعاب خلال 24 ساعة (يحمي من تكديس النقاط بسرعة غير طبيعية).
# النقاط اللي تجي من .يومي أو .تحويل أو .اصدار ما تدخل بهذا الحد.
DAILY_GAME_POINTS_CAP = 500

# مهلة التفاعل بالثواني: اللاعب اللي دوره/اختياره مطلوب منه ولا تفاعل خلال هذي المدة يطلع من اللعبة
# (روليت: اللاعب المختار يطيح — XO: اللي دوره يخسر — حجرة ورقة مقص: اللي ما اختار يخسر).
TURN_TIMEOUT = 15

# ---------- صور الألعاب ----------
# مجلد الصور لازم يكون بجنب ملف البوت (نفس المجلد) باسم game_images.
GAME_IMAGES_DIR = "game_images"
GAME_IMAGES = {
    "روليت": "roulette.png", "xo": "xo.png", "مافيا": "mafia.png", "كراسي": "chairs.png",
    "حجرة": "rps.png", "نرد": "dice.png", "عجلة": "wheel.png", "غميضة": "hideseek.png",
    "ريبلكا": "replica.png", "خمن": "guess.png", "كلمة": "wordchain.png", "زر": "button.png",
    "اسرع": "fastest.png", "فكك": "split.png", "رتب": "unscramble.png", "ادمج": "combine.png",
    "اعلام": "flags.png", "اعكس": "reverse.png", "حرف": "letter.png", "ترتيب": "ordering.png",
    "الوان": "colors.png", "ايموجي": "emoji.png", "اكشف": "memory.png",
}


def game_image_file(game_key: str) -> discord.File | None:
    """يرجع صورة اللعبة (discord.File جديدة كل مرة) لو موجودة على القرص، وإلا None."""
    filename = GAME_IMAGES.get(game_key)
    if not filename:
        return None
    path = os.path.join(GAME_IMAGES_DIR, filename)
    if not os.path.exists(path):
        return None
    return discord.File(path, filename=filename)


def game_image_name(game_key: str) -> str | None:
    """يرجع اسم ملف صورة اللعبة لو موجودة على القرص، وإلا None."""
    filename = GAME_IMAGES.get(game_key)
    if not filename:
        return None
    if not os.path.exists(os.path.join(GAME_IMAGES_DIR, filename)):
        return None
    return filename


def attach_game_image(embed: discord.Embed, game_key: str) -> discord.File | None:
    """يشبك صورة اللعبة داخل الإطار (الإمبد) نفسه: يضبط صورة الإمبد على المرفق،
    ويرجع الملف اللي لازم يتبعت مع الرسالة (أو None لو الصورة مو موجودة)."""
    image = game_image_file(game_key)
    if image:
        embed.set_image(url=f"attachment://{image.filename}")
    return image


# اسم رول الألعاب — لازم يطابق اسم الرول اللي سويته بالسيرفر حرف بحرف
GAMES_ROLE_NAME = "Event Team"

# ---------- فايب البوت (ستايل خاص بالألعاب) ----------
# لون موحّد لكل لوحات الألعاب (لوبي الانضمام وغيره).
VIBE_COLOR = discord.Color.from_rgb(124, 92, 255)

# أشكال الأزرار: رموز/أشكال نصية (مو ايموجي) تنكتب قبل نص الزر. بدّلها بأي شكل تبيه، أو خلها "" لو تبي زر بدون شكل.
UI_ICONS = {
    "join": "⊕",
    "leave": "⊖",
    "start": "➤",
    "accept": "✓",
    "decline": "✕",
    "dice": "⚄",
    "stop": "■",
}


# يتعبّى من setup_games (الكود الأصلي يستخدم bot.get_channel / bot.loop داخل الدوال)
bot = None


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
# نقاط الألعاب + سجل الفوز/الخسارة (نفس الدوال اللي كانت بقسم الاقتصاد)
# ============================================================
def add_game_reward(guild_id: int, user_id: int, amount: int) -> int:
    """يضيف نقاط من مكاسب الألعاب بس (مو من .يومي أو .تحويل أو .اصدار)، بحد أقصى DAILY_GAME_POINTS_CAP
    نقطة كل 24 ساعة لكل لاعب. يرجع المبلغ اللي انضاف فعليًا (ممكن يكون أقل من amount لو قارب السقف)."""
    if amount <= 0:
        return 0
    data = load_json(ECONOMY_FILE)
    gid, uid = str(guild_id), str(user_id)
    data.setdefault(gid, {})
    now = datetime.now(timezone.utc)
    start_key, earned_key = f"{uid}_daily_game_start", f"{uid}_daily_game_earned"
    start_str = data[gid].get(start_key)
    earned_so_far = data[gid].get(earned_key, 0)
    if not start_str or (now - datetime.fromisoformat(start_str)).total_seconds() >= 86400:
        start_str = now.isoformat()
        earned_so_far = 0
    actual = max(0, min(amount, DAILY_GAME_POINTS_CAP - earned_so_far))
    data[gid][start_key] = start_str
    data[gid][earned_key] = earned_so_far + actual
    if actual > 0:
        data[gid][uid] = data[gid].get(uid, 0) + actual
    save_json(ECONOMY_FILE, data)
    return actual


def record_game_result(guild_id: int, user_id: int, won: bool) -> None:
    """يسجل فوز أو خسارة للاعب بملف إحصائيات الألعاب (يستخدمه أمر .سجلي)."""
    data = load_json(GAME_STATS_FILE)
    gid, uid = str(guild_id), str(user_id)
    data.setdefault(gid, {})
    data[gid].setdefault(uid, {"wins": 0, "losses": 0})
    data[gid][uid]["wins" if won else "losses"] += 1
    save_json(GAME_STATS_FILE, data)


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

# ---------- سحب بدون تكرار (كل الكلمات تنعرض مرة وحدة قبل ما تتكرر أي كلمة) ----------
_bags: dict[str, list] = {}


def draw_no_repeat(key: str, items: list):
    """يرجع عنصر عشوائي من القائمة بدون ما يتكرر لين تنعرض كل العناصر، وبعدها يخلط من جديد."""
    bag = _bags.get(key)
    if not bag:
        bag = list(range(len(items)))
        random.shuffle(bag)
        _bags[key] = bag
    return items[bag.pop()]


# ---------- قفل عام يمنع تداخل الألعاب: روم واحد = لعبة وحدة بنفس اللحظة ----------
active_channel_games: dict[int, str] = {}  # channel_id -> اسم اللعبة الشغالة


def is_channel_busy(channel_id: int) -> bool:
    return channel_id in active_channel_games


def mark_busy(channel_id: int, game_name: str) -> None:
    active_channel_games[channel_id] = game_name


def unmark_busy(channel_id: int) -> None:
    active_channel_games.pop(channel_id, None)
    untrack_game_message(channel_id)


async def warn_busy(ctx: commands.Context) -> None:
    name = active_channel_games.get(ctx.channel.id, "لعبة")
    await ctx.send(f"فيه **{name}** شغالة بهذا الروم حاليًا، خلصوها الأول قبل لعبة ثانية.")


# ---------- تتبع رسالة اللعبة الحالية (عشان لو انحذفت، اللعبة توقف) ----------
active_game_messages: dict[int, int] = {}       # channel_id -> آيدي رسالة اللعبة الحالية
game_cancel_events: dict[int, asyncio.Event] = {}  # channel_id -> Event تنضبط لو انحذفت رسالة اللعبة


def track_game_message(channel_id: int, message: discord.Message) -> asyncio.Event:
    """يسجل هذي الرسالة كرسالة اللعبة الحالية بهذا الروم (يستبدل أي تتبع سابق لنفس الروم)،
    ويرجع Event تنضبط تلقائيًا لو حد حذف الرسالة."""
    event = asyncio.Event()
    game_cancel_events[channel_id] = event
    active_game_messages[channel_id] = message.id
    return event


def untrack_game_message(channel_id: int) -> None:
    game_cancel_events.pop(channel_id, None)
    active_game_messages.pop(channel_id, None)


async def wait_or_game_cancelled(event: asyncio.Event, timeout: float | None = None) -> bool:
    """ينتظر لين اللعبة تنلغى (حذف رسالتها) أو ينتهي الوقت. يرجع True لو انلغت اللعبة."""
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    """لو انحذفت رسالة لعبة شغالة حاليًا، نوقف اللعبة فورًا ونبلّغ بالروم."""
    channel_id = payload.channel_id

    if active_game_messages.get(channel_id) != payload.message_id:
        return
    event = game_cancel_events.get(channel_id)
    if event is not None:
        event.set()
    # نوقف أي جولة سؤال/جواب أو لعبة تخمين شغالة بنفس الروم
    active_rounds.pop(channel_id, None)
    active_guess_games.pop(channel_id, None)
    unmark_busy(channel_id)  # يشيل قفل "روم مشغول" ويمسح التتبع
    channel = bot.get_channel(channel_id)
    if channel is not None:
        try:
            await channel.send("تم إيقاف اللعبة (تم حذف رسالتها).")
        except discord.Forbidden:
            pass


class StopRoundView(discord.ui.View):
    """زر "إيقاف" يطلع تحت رسالة الألعاب الفردية: يوقف اللعبة ويكشف الجواب.
    يقدر يوقفها بس اللي بدأ اللعبة أو أونر السيرفر."""

    def __init__(self, channel_id: int, token: int, starter, timeout: float):
        super().__init__(timeout=timeout + 10)
        self.channel_id = channel_id
        self.token = token
        self.starter = starter
        btn = discord.ui.Button(label=f"{UI_ICONS['stop']} إيقاف", style=discord.ButtonStyle.secondary)
        btn.callback = self.on_stop
        self.add_item(btn)

    async def on_stop(self, interaction: discord.Interaction):
        info = active_rounds.get(self.channel_id)
        if not info or info.get("token") != self.token:
            await interaction.response.send_message("اللعبة خلصت أصلًا.", ephemeral=True)
            return
        is_starter = self.starter is not None and interaction.user.id == self.starter.id
        is_owner = interaction.guild is not None and interaction.user.id == interaction.guild.owner_id
        if not (is_starter or is_owner):
            await interaction.response.send_message(
                "ما تقدر توقف اللعبة، بس اللي بدأها.", ephemeral=True)
            return
        del active_rounds[self.channel_id]
        event = game_cancel_events.get(self.channel_id)
        if event is not None:
            event.set()
        unmark_busy(self.channel_id)
        reveal = info.get("reveal", "")
        text = "تم إيقاف اللعبة." + (f" الجواب كان: **{reveal}**" if reveal else "")
        await interaction.response.edit_message(view=None)
        await interaction.channel.send(text)
        self.stop()


async def _remove_round_button(msg) -> None:
    """يشيل زر الإيقاف من رسالة الجولة (بعد ما تنتهي)."""
    if msg is None:
        return
    try:
        await msg.edit(view=None)
    except (discord.NotFound, discord.HTTPException):
        pass


async def start_round(channel, *, title: str, prompt: str, checker, reward=(20, 40),
                       allowed_ids: set | None = None, timeout: int = 45, reveal: str = "",
                       game_key: str = "", starter=None):
    """يبدأ جولة سؤال/جواب بالروم. أول رسالة تطابق checker تفوز."""
    if channel.id in active_rounds or is_channel_busy(channel.id):
        busy_name = active_channel_games.get(channel.id, title)
        await channel.send(f"فيه **{busy_name}** شغالة بهذا الروم حاليًا، خلصوها الأول.")
        return
    token = next(_round_id_counter)
    active_rounds[channel.id] = {
        "checker": checker, "reward": reward,
        "allowed_ids": allowed_ids, "token": token, "reveal": reveal,
    }
    mark_busy(channel.id, title)
    embed = discord.Embed(title=title, description=prompt, color=VIBE_COLOR)
    image = attach_game_image(embed, game_key)
    stop_view = StopRoundView(channel.id, token, starter, timeout)
    if image:
        msg = await channel.send(embed=embed, file=image, view=stop_view)
    else:
        msg = await channel.send(embed=embed, view=stop_view)
    active_rounds[channel.id]["msg"] = msg
    cancel_event = track_game_message(channel.id, msg)

    async def _timeout_watcher():
        cancelled = await wait_or_game_cancelled(cancel_event, timeout=timeout)
        current = active_rounds.get(channel.id)
        if current and current.get("token") == token:
            del active_rounds[channel.id]
            unmark_busy(channel.id)
            await _remove_round_button(current.get("msg"))
            if not cancelled:
                extra = f" الإجابة كانت: **{reveal}**" if reveal else ""
                await channel.send(f"خلص الوقت!{extra}")
            # لو انحذفت الرسالة، معالج on_raw_message_delete هو اللي أرسل خبر الإيقاف

    bot.loop.create_task(_timeout_watcher())


# ============================================================
# 4) بنوك بيانات الألعاب
# ============================================================
WORD_BANK = ["مدرسة", "حاسوب", "سيارة", "طائرة", "مستشفى", "مكتبة", "شمس", "قمر",
             "بحر", "جبل", "صحراء", "نافذة", "مفتاح", "كتاب", "قلم"]

# ---------- صحح الكلمة: (الكلمة الغلط, الكلمة الصح) ----------
SPELL_BANK = [
    ("مدرصة", "مدرسة"), ("قلن", "قلم"), ("حديكة", "حديقة"),
    ("فراسة", "فراشة"), ("غاية", "غابة"), ("نافزة", "نافذة"),
    ("ظفدع", "ضفدع"), ("تعلب", "ثعلب"), ("زئب", "ذئب"),
    ("شنس", "شمس"), ("سيارت", "سيارة"), ("كتاپ", "كتاب"),
    ("مستشفا", "مستشفى"), ("مطعن", "مطعم"), ("حاسوف", "حاسوب"), ("طيارت", "طيارة"),
    ("دفتل", "دفتر"), ("مفتاخ", "مفتاح"), ("صحرا", "صحراء"), ("بحل", "بحر"),
    ("نهل", "نهر"), ("شجرت", "شجرة"), ("وردت", "وردة"), ("ثلاجت", "ثلاجة"),
    ("طاولت", "طاولة"), ("مدينت", "مدينة"), ("ملعف", "ملعب"), ("سماعت", "سماعة"),
    ("ساعت", "ساعة"), ("هاتق", "هاتف"), ("شاشت", "شاشة"), ("حقيبت", "حقيبة"),
    ("مطبق", "مطبخ"), ("غرفت", "غرفة"), ("نظارت", "نظارة"), ("مظلت", "مظلة"),
    ("مقعت", "مقعد"), ("طبيت", "طبيب"), ("معلن", "معلم"), ("مهندز", "مهندس"),
    ("شرتي", "شرطي"), ("فلاخ", "فلاح"), ("نجال", "نجار"), ("تيور", "طيور"),
    ("عصفوز", "عصفور"), ("هصان", "حصان"), ("غزان", "غزال"), ("زرافت", "زرافة"),
    ("دجاجت", "دجاجة"), ("بقرت", "بقرة"), ("حمامت", "حمامة"), ("سلحفات", "سلحفاة"),
    ("عنكبود", "عنكبوت"), ("تمساخ", "تمساح"), ("سعبان", "ثعبان"), ("أصد", "أسد"),
    ("بتيخ", "بطيخ"), ("تفاخ", "تفاح"), ("برطقال", "برتقال"), ("رمام", "رمان"),
    ("فراولت", "فراولة"), ("حيار", "خيار"), ("تماطم", "طماطم"), ("توم", "ثوم"),
    ("عصيل", "عصير"), ("هليب", "حليب"), ("مكيق", "مكيف"), ("وصادة", "وسادة"),
    ("صجادة", "سجادة"), ("جذار", "جدار"), ("صقف", "سقف"), ("حديت", "حديد"),
    ("حشب", "خشب"), ("زجاز", "زجاج"), ("زهب", "ذهب"), ("فظة", "فضة"),
    ("نحاص", "نحاس"), ("رياخ", "رياح"), ("غيمت", "غيمة"), ("سلج", "ثلج"),
    ("صاعقت", "صاعقة"), ("عاصفت", "عاصفة"), ("زلزان", "زلزال"), ("بركال", "بركان"),
    ("كوكت", "كوكب"), ("نجمت", "نجمة"), ("مجرت", "مجرة"), ("ساروخ", "صاروخ"),
    ("جامعت", "جامعة"), ("مكتبت", "مكتبة"), ("سديق", "صديق"), ("عايلة", "عائلة"),
    ("ظيف", "ضيف"), ("ظوء", "ضوء"), ("ضلام", "ظلام"), ("ضهر", "ظهر"), ("ظحك", "ضحك"),
]

# ---------- الحرف الناقص: كلمات (4 حروف فأكثر، بدون همزات وسط الكلمة) ----------
LETTER_BANK = list(dict.fromkeys([
    # أماكن ومباني
    "دكان", "مدرسة", "مكتبة", "حديقة", "مطعم", "مستشفى", "ملعب", "جامعة", "مطار", "محطة",
    "مدينة", "قرية", "شارع", "قلعة", "مسجد", "كنيسة", "متحف", "مصنع", "مزرعة", "بستان",
    "غابة", "بحيرة", "شلال", "جزيرة", "بركان", "واحة", "وادي", "ينبوع", "شرفة", "مكتب",
    # مواصلات
    "سيارة", "طيارة", "قطار", "دراجة", "سفينة", "شاحنة", "صاروخ", "مصعد", "حافلة", "قارب",
    # أجهزة وأدوات
    "حاسوب", "مفتاح", "ثلاجة", "غسالة", "مكيف", "تلفاز", "هاتف", "شاشة", "ساعة", "نظارة",
    "حقيبة", "مظلة", "سجادة", "وسادة", "طاولة", "كرسي", "سرير", "خزانة", "مطبخ", "غرفة",
    "حمام", "جدار", "مكنسة", "ملعقة", "سكين", "صحن", "إبريق", "طابعة", "كاميرا", "سماعة",
    "مسطرة", "ممحاة", "سبورة", "دفتر", "كتاب", "نافذة", "لوحة", "بوصلة", "خريطة", "تذكرة",
    # نباتات وفواكه وخضار
    "شجرة", "زهرة", "بطيخ", "برتقال", "تفاح", "رمان", "فراولة", "طماطم", "خيار", "ليمون",
    "موزة", "مشمش", "كمثرى", "جوافة", "اناناس", "فستق", "بندق", "باذنجان", "فلفل", "بطاطس",
    "زيتون", "جزرة", "بصلة", "شمام", "عنقود", "ورقة",
    # أكل وشرب
    "قهوة", "حليب", "عصير", "جبنة", "زبدة", "دجاج", "سمكة", "حلوى", "شوربة", "معكرونة",
    # حيوانات وطيور وحشرات
    "عصفور", "غزال", "حصان", "ثعلب", "ضفدع", "سلحفاة", "تمساح", "زرافة", "دجاجة", "غراب",
    "حمامة", "بجعة", "نعامة", "طاووس", "دلفين", "أخطبوط", "عقرب", "عنكبوت", "نملة", "نحلة",
    "ذبابة", "سحلية", "ثعبان", "أفعى", "حمار", "ناقة", "خروف", "بقرة", "ماعز", "أرنب",
    "قنفذ", "سنجاب", "كنغر", "هدهد", "بلبل", "غزالة",
    # مهن وناس
    "طبيب", "معلم", "مهندس", "شرطي", "جندي", "فلاح", "نجار", "حداد", "خباز", "طباخ",
    "ممرض", "صياد", "تاجر", "رسام", "كاتب", "شاعر", "لاعب", "حارس", "قاضي", "محامي",
    "صحفي", "طيار", "عالم", "مزارع", "صديق", "والدة",
    # طبيعة وفضاء ومواد
    "كوكب", "نجمة", "مجرة", "سحابة", "رياح", "عاصفة", "صاعقة", "ضباب", "صقيع", "صخرة",
    "رمال", "معدن", "فضة", "نحاس", "حديد", "زجاج", "قماش", "حرير", "زلزال", "غيمة",
    # أفكار ومعاني
    "نجاح", "صداقة", "سعادة", "حرية", "عدالة", "شجاعة", "ذاكرة", "حكمة", "ثقافة", "رياضة",
    "موسيقى", "رحلة", "مغامرة", "حكاية", "مسرحية", "قصيدة", "رسالة", "جريدة", "مجلة",
    # وقت
    "ظهيرة", "أسبوع", "ربيع", "خريف", "ثانية", "دقيقة",
]))

_LETTER_BANK_NORM = {normalize(w) for w in LETTER_BANK}


def answer_matches(content: str, names: list[str]) -> bool:
    """يطابق إجابة اللاعب مع قائمة إجابات مقبولة (كلمة كاملة، يتجاهل 'ال' والهمزات والتشكيل)."""
    text = re.sub(r"[^\w\s]", " ", normalize(content))
    words = text.split()
    if not words or len(words) > 6:
        return False
    padded = " " + " ".join(words) + " "
    for name in names:
        n = re.sub(r"[^\w\s]", " ", normalize(name))
        n = " ".join(n.split())
        if not n:
            continue
        variants = {n}
        if n.startswith("ال") and len(n) > 3:
            variants.add(n[2:])
        else:
            variants.add("ال" + n)
        for v in variants:
            if f" {v} " in padded:
                return True
    return False


# ---------- أعلام: 4 مستويات (سهل / متوسط / صعب / صعب جدًا) — كل علم معه أسماء مقبولة ----------
FLAG_TIERS = {
    "سهل": {
        "reward": (15, 30),
        "flags": [
            ("🇸🇦", ["السعودية", "المملكة العربية السعودية", "المملكة السعودية"]),
            ("🇪🇬", ["مصر"]),
            ("🇦🇪", ["الإمارات", "الإمارات العربية المتحدة"]),
            ("🇰🇼", ["الكويت"]), ("🇶🇦", ["قطر"]), ("🇧🇭", ["البحرين"]),
            ("🇴🇲", ["عمان", "سلطنة عمان"]), ("🇮🇶", ["العراق"]), ("🇯🇴", ["الأردن"]),
            ("🇱🇧", ["لبنان"]), ("🇲🇦", ["المغرب"]), ("🇹🇷", ["تركيا"]),
            ("🇺🇸", ["أمريكا", "الولايات المتحدة", "الولايات المتحدة الأمريكية"]),
            ("🇬🇧", ["بريطانيا", "المملكة المتحدة", "إنجلترا"]),
            ("🇫🇷", ["فرنسا"]), ("🇯🇵", ["اليابان"]), ("🇧🇷", ["البرازيل"]),
            ("🇩🇪", ["ألمانيا"]), ("🇮🇹", ["إيطاليا"]), ("🇪🇸", ["إسبانيا"]), ("🇷🇺", ["روسيا"]),
            ("🇨🇳", ["الصين"]), ("🇮🇳", ["الهند"]), ("🇨🇦", ["كندا"]), ("🇦🇺", ["أستراليا"]),
            ("🇲🇽", ["المكسيك"]), ("🇦🇷", ["الأرجنتين"]),
        ],
    },
    "متوسط": {
        "reward": (25, 45),
        "flags": [
            ("🇨🇭", ["سويسرا"]), ("🇸🇪", ["السويد"]), ("🇳🇴", ["النرويج"]), ("🇩🇰", ["الدنمارك"]),
            ("🇫🇮", ["فنلندا"]), ("🇵🇹", ["البرتغال"]), ("🇬🇷", ["اليونان"]), ("🇦🇷", ["الأرجنتين"]),
            ("🇲🇽", ["المكسيك"]), ("🇨🇦", ["كندا"]), ("🇦🇺", ["أستراليا"]),
            ("🇰🇷", ["كوريا الجنوبية", "جنوب كوريا"]), ("🇰🇵", ["كوريا الشمالية", "شمال كوريا"]),
            ("🇮🇳", ["الهند"]), ("🇵🇰", ["باكستان"]), ("🇮🇷", ["إيران"]), ("🇱🇾", ["ليبيا"]),
            ("🇹🇳", ["تونس"]), ("🇩🇿", ["الجزائر"]), ("🇸🇩", ["السودان"]), ("🇾🇪", ["اليمن"]),
            ("🇸🇾", ["سوريا"]), ("🇵🇸", ["فلسطين"]), ("🇮🇩", ["إندونيسيا"]), ("🇲🇾", ["ماليزيا"]),
            ("🇪🇸", ["إسبانيا"]), ("🇮🇹", ["إيطاليا"]), ("🇩🇪", ["ألمانيا"]), ("🇷🇺", ["روسيا"]),
            ("🇳🇱", ["هولندا"]), ("🇧🇪", ["بلجيكا"]), ("🇦🇹", ["النمسا"]), ("🇵🇱", ["بولندا"]),
            ("🇺🇦", ["أوكرانيا"]), ("🇨🇺", ["كوبا"]), ("🇨🇴", ["كولومبيا"]), ("🇨🇱", ["تشيلي"]),
            ("🇵🇪", ["بيرو"]), ("🇻🇳", ["فيتنام"]), ("🇹🇭", ["تايلاند"]), ("🇵🇭", ["الفلبين"]),
            ("🇸🇴", ["الصومال"]), ("🇲🇷", ["موريتانيا"]), ("🇨🇳", ["الصين"]),
            ("🇸🇬", ["سنغافورة"]), ("🇩🇯", ["جيبوتي"]), ("🇰🇲", ["جزر القمر"]),
            ("🇩🇴", ["جمهورية الدومينيكان", "الدومينيكان", "الدومنيكان"]),
            ("🇬🇦", ["الغابون"]), ("🇸🇸", ["جنوب السودان"]),
        ],
    },
    "صعب": {
        "reward": (40, 70),
        "flags": [
            ("🇨🇿", ["التشيك", "تشيكيا", "جمهورية التشيك"]), ("🇭🇺", ["المجر"]), ("🇷🇴", ["رومانيا"]),
            ("🇧🇬", ["بلغاريا"]), ("🇷🇸", ["صربيا"]), ("🇭🇷", ["كرواتيا"]), ("🇸🇰", ["سلوفاكيا"]),
            ("🇸🇮", ["سلوفينيا"]), ("🇮🇪", ["أيرلندا", "جمهورية أيرلندا"]), ("🇮🇸", ["آيسلندا"]),
            ("🇪🇪", ["إستونيا"]), ("🇱🇻", ["لاتفيا"]), ("🇱🇹", ["ليتوانيا"]),
            ("🇧🇾", ["بيلاروسيا", "روسيا البيضاء"]), ("🇬🇪", ["جورجيا"]), ("🇦🇲", ["أرمينيا"]),
            ("🇦🇿", ["أذربيجان"]), ("🇰🇿", ["كازاخستان"]), ("🇺🇿", ["أوزبكستان"]), ("🇦🇫", ["أفغانستان"]),
            ("🇧🇩", ["بنغلاديش"]), ("🇱🇰", ["سريلانكا"]), ("🇳🇵", ["نيبال"]), ("🇲🇳", ["منغوليا"]),
            ("🇰🇭", ["كمبوديا"]), ("🇲🇲", ["ميانمار", "بورما"]), ("🇱🇦", ["لاوس"]), ("🇳🇬", ["نيجيريا"]),
            ("🇰🇪", ["كينيا"]), ("🇪🇹", ["إثيوبيا"]), ("🇬🇭", ["غانا"]), ("🇹🇿", ["تنزانيا"]),
            ("🇸🇳", ["السنغال"]), ("🇨🇮", ["ساحل العاج", "كوت ديفوار"]), ("🇿🇦", ["جنوب أفريقيا", "جنوب افريقيا"]),
            ("🇻🇪", ["فنزويلا"]), ("🇪🇨", ["الإكوادور"]), ("🇺🇾", ["أوروغواي", "اوروجواي", "اورغواي"]),
            ("🇵🇾", ["باراغواي", "باراجواي"]), ("🇧🇴", ["بوليفيا"]), ("🇨🇷", ["كوستاريكا"]),
            ("🇵🇦", ["بنما"]), ("🇯🇲", ["جامايكا"]), ("🇳🇿", ["نيوزيلندا", "نيوزلندا"]),
            ("🇲🇹", ["مالطا"]), ("🇨🇾", ["قبرص"]), ("🇱🇺", ["لوكسمبورغ", "لكسمبورغ"]),
            ("🇻🇦", ["الفاتيكان", "دولة الفاتيكان"]), ("🇸🇱", ["سيراليون"]), ("🇱🇷", ["ليبيريا"]),
            ("🇨🇫", ["أفريقيا الوسطى", "جمهورية أفريقيا الوسطى", "افريقيا الوسطى"]),
            ("🇧🇮", ["بوروندي"]), ("🇬🇲", ["غامبيا"]),
            ("🇨🇻", ["الرأس الأخضر", "كابو فيردي", "جزر الرأس الأخضر"]),
            ("🇬🇶", ["غينيا الاستوائية"]), ("🇬🇼", ["غينيا بيساو"]),
            ("🇸🇹", ["ساو تومي وبرينسيب", "ساو تومي"]), ("🇸🇿", ["إسواتيني", "سوازيلاند"]),
        ],
    },
    "صعب جدًا": {
        "reward": (60, 100),
        "flags": [
            ("🇲🇰", ["مقدونيا الشمالية", "مقدونيا", "شمال مقدونيا"]), ("🇦🇱", ["ألبانيا"]),
            ("🇲🇪", ["الجبل الأسود", "مونتينيغرو"]), ("🇧🇦", ["البوسنة والهرسك", "البوسنة"]),
            ("🇲🇩", ["مولدوفا"]), ("🇱🇮", ["ليختنشتاين", "ليخنشتاين", "ليختشتاين"]),
            ("🇲🇨", ["موناكو"]), ("🇸🇲", ["سان مارينو"]), ("🇦🇩", ["أندورا"]),
            ("🇹🇯", ["طاجيكستان"]), ("🇰🇬", ["قرغيزستان", "قيرغيزستان"]), ("🇹🇲", ["تركمانستان"]),
            ("🇧🇹", ["بوتان"]), ("🇲🇻", ["جزر المالديف", "المالديف"]), ("🇧🇳", ["بروناي"]),
            ("🇹🇱", ["تيمور الشرقية"]), ("🇵🇬", ["بابوا غينيا الجديدة", "بابوا غينيا", "بابوا"]),
            ("🇫🇯", ["فيجي", "فيدجي"]), ("🇼🇸", ["ساموا"]), ("🇹🇴", ["تونغا", "تونجا"]),
            ("🇲🇬", ["مدغشقر"]), ("🇲🇿", ["موزمبيق"]), ("🇿🇼", ["زيمبابوي"]), ("🇧🇼", ["بوتسوانا"]),
            ("🇳🇦", ["ناميبيا"]), ("🇲🇱", ["مالي"]), ("🇳🇪", ["النيجر"]), ("🇹🇩", ["تشاد"]),
            ("🇧🇫", ["بوركينا فاسو"]), ("🇨🇲", ["الكاميرون"]),
            ("🇨🇩", ["الكونغو الديمقراطية", "الكونغو", "الكونجو"]), ("🇦🇴", ["أنغولا", "انجولا"]),
            ("🇷🇼", ["رواندا"]), ("🇺🇬", ["أوغندا", "اوجندا"]), ("🇪🇷", ["إريتريا"]),
            ("🇸🇨", ["سيشل"]), ("🇲🇺", ["موريشيوس"]), ("🇭🇹", ["هايتي"]),
            ("🇬🇹", ["غواتيمالا", "جواتيمالا"]), ("🇭🇳", ["هندوراس"]), ("🇳🇮", ["نيكاراغوا", "نيكاراجوا"]),
            ("🇸🇻", ["السلفادور"]), ("🇧🇿", ["بليز"]), ("🇬🇾", ["غيانا", "جيانا"]), ("🇸🇷", ["سورينام"]),
            ("🇧🇧", ["بربادوس"]), ("🇧🇸", ["جزر البهاما", "البهاما"]),
            ("🇹🇹", ["ترينيداد وتوباغو", "ترينيداد"]), ("🇹🇬", ["توغو"]), ("🇧🇯", ["بنين"]),
            ("🇿🇲", ["زامبيا"]), ("🇲🇼", ["مالاوي"]), ("🇱🇸", ["ليسوتو"]),
            ("🇩🇲", ["دومينيكا"]), ("🇱🇨", ["سانت لوسيا"]), ("🇬🇩", ["غرينادا", "غرنادا"]),
            ("🇰🇳", ["سانت كيتس ونيفيس", "سانت كيتس"]),
            ("🇻🇨", ["سانت فنسنت والغرينادين", "سانت فنسنت"]),
            ("🇦🇬", ["أنتيغوا وبربودا", "أنتيغوا", "انتيجوا وبربودا"]),
            ("🇰🇮", ["كيريباتي"]), ("🇳🇷", ["ناورو"]), ("🇹🇻", ["توفالو"]), ("🇻🇺", ["فانواتو"]),
            ("🇸🇧", ["جزر سليمان"]), ("🇫🇲", ["ميكرونيزيا"]), ("🇲🇭", ["جزر مارشال"]),
            ("🇵🇼", ["بالاو"]),
        ],
    },
}

# ---------- ايموجي: رموز مركبة (أفلام / شخصيات / قصص / أماكن) — أصعب من رمز واحد ----------
# كل عنصر: (الرموز, [الأجوبة المقبولة], التصنيف)
EMOJI_GUESS_BANK = [
    ("🕷️👨", ["سبايدرمان", "سبايدر مان", "سبيدرمان", "الرجل العنكبوت"], "شخصية"),
    ("🦇👨", ["باتمان", "بات مان", "الرجل الوطواط"], "شخصية"),
    ("🧊🚢💔", ["تايتانيك", "titanic"], "فيلم"),
    ("🦁👑🌅", ["الأسد الملك", "اسد الملك", "the lion king"], "فيلم"),
    ("🐠🔍🌊", ["نيمو", "البحث عن نيمو", "finding nemo"], "فيلم"),
    ("❄️👸⛄", ["فروزن", "ملكة الثلج", "frozen"], "فيلم"),
    ("💍🧙‍♂️🌋", ["سيد الخواتم", "the lord of the rings", "لورد اوف ذا رينقز"], "فيلم"),
    ("🍎👸😴", ["بياض الثلج", "سنو وايت", "snow white"], "قصة"),
    ("🧞‍♂️🪔", ["علاء الدين", "علاء الدين والمصباح السحري", "المصباح السحري"], "قصة"),
    ("🐢🐇🏁", ["السلحفاة والأرنب", "الأرنب والسلحفاة"], "قصة"),
    ("🏴‍☠️🦜", ["قراصنة الكاريبي", "قراصنة", "قرصان"], "فيلم"),
    ("🦖🏞️", ["جوراسيك بارك", "جوراسيك", "حديقة الديناصورات"], "فيلم"),
    ("🛸👽", ["فضائيين", "كائنات فضائية", "كائن فضائي", "فضائي"], "شيء"),
    ("🧛🩸", ["دراكولا", "مصاص دماء", "مصاص الدماء"], "شخصية"),
    ("🧟🧠", ["زومبي", "الزومبي"], "شيء"),
    ("🦸‍♂️🇺🇸🛡️", ["كابتن أمريكا", "captain america"], "شخصية"),
    ("⚡🏃", ["فلاش", "الفلاش", "the flash"], "شخصية"),
    ("🌑☀️", ["كسوف", "كسوف الشمس"], "ظاهرة"),
    ("🕰️🔙🚗", ["العودة للمستقبل", "back to the future"], "فيلم"),
    ("🍫🏭", ["مصنع الشوكولاتة", "تشارلي ومصنع الشوكولاتة", "ويلي ونكا"], "فيلم"),
    ("🗼🥖🇫🇷", ["باريس"], "مدينة"),
    ("🗽🇺🇸🍎", ["نيويورك"], "مدينة"),
    ("🎡🏰🐭", ["ديزني لاند", "ديزني"], "مكان"),
]

COMPOUND_BANK = [
    ("🌹💧", "ماء ورد"), ("☀️🌻", "عباد الشمس"), ("❄️☃️", "رجل الثلج"),
    ("🔥🚒", "إطفائية"), ("🐄🥛", "حليب"), ("🐔🥚", "بيضة"),
    ("🌽🍿", "فشار"), ("🍇🧃", "عصير عنب"), ("🐝🍯", "عسل"),
]

# ---------- ألوان: أسئلة خلط ألوان ومعلومات عن الألوان (بدل "وش لون البرتقالة") ----------
# كل عنصر: (السؤال, [الأجوبة المقبولة])
COLOR_BANK = [
    ("وش اللون الناتج من خلط **الأصفر** مع **الأزرق**؟", ["أخضر"]),
    ("وش اللون الناتج من خلط **الأحمر** مع **الأصفر**؟", ["برتقالي"]),
    ("وش اللون الناتج من خلط **الأحمر** مع **الأزرق**؟", ["بنفسجي", "موف", "أرجواني"]),
    ("وش اللون الناتج من خلط **الأبيض** مع **الأسود**؟", ["رمادي", "رصاصي"]),
    ("وش اللون الناتج من خلط **الأحمر** مع **الأبيض**؟", ["وردي", "زهري"]),
    ("وش اللون الناتج من خلط **الأزرق** مع **الأبيض**؟", ["سماوي", "أزرق فاتح", "أزرق سماوي"]),
    ("وش اللون الناتج من خلط **الأخضر** مع **الأحمر** (بالأصباغ)؟", ["بني", "قهوائي"]),
    ("وش لون **الصندوق الأسود** بالطائرات فعليًا؟", ["برتقالي"]),
    ("وش لون **دم الأخطبوط**؟", ["أزرق"]),
    ("وش لون **جلد الدب القطبي** تحت الفرو؟", ["أسود"]),
    ("وش لون حجر **الياقوت** الأصلي؟", ["أحمر"]),
    ("وش لون حجر **الزمرد**؟", ["أخضر"]),
    ("وش اللون اللي يتكون من **اجتماع كل ألوان الضوء**؟", ["أبيض"]),
    ("وش اللون اللي **يمتص كل ألوان الضوء**؟", ["أسود"]),
    ("وش اللون **المكمّل للأزرق** بعجلة الألوان؟", ["برتقالي"]),
    ("وش اللون **المكمّل للأحمر** بعجلة الألوان؟", ["أخضر"]),
    ("وش اللون **المكمّل للأصفر** بعجلة الألوان؟", ["بنفسجي", "موف"]),
    ("وش اللون المسؤول عن لون النباتات (مادة **الكلوروفيل**)؟", ["أخضر"]),
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

# كل الحروف مطبّعة (للبحث عن حروف بديلة تكوّن كلمة صحيحة بلعبة الحرف الناقص)
_LETTER_CANDIDATES = sorted({normalize(c) for c in ARABIC_LETTERS})

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
SPLIT_BANK = ["بكره", "مدرسة", "حاسوب", "سيارة", "طائرة", "مكتبة", "حديقة", "سلام",
              "صباح", "مساء", "قهوة", "مطعم", "ملعب", "صديق", "كتاب", "نافذة", "مفتاح", "شمس", "قمر", "بحر"]


@commands.command(name="فكك")
async def split_letters_cmd(ctx: commands.Context):
    """فكك الكلمة حرف حرف: بكره ← ب ك ر ه"""
    word = random.choice(SPLIT_BANK)
    letters = list(normalize(word))
    spaced = " ".join(word)

    def checker(content: str) -> bool:
        cleaned = re.sub(r"[-_.,،|/]", " ", content)
        tokens = [normalize(t) for t in cleaned.split()]
        return tokens == letters

    await start_round(ctx.channel, starter=ctx.author, title="فكك الكلمة",
                       prompt=f"فكك هذي الكلمة حرف حرف (بين كل حرف مسافة): **{word}**\nمثال: بكره ← ب ك ر ه",
                       checker=checker, reward=(25, 45), reveal=spaced, game_key="فكك")


@commands.command(name="رتب")
async def unscramble_cmd(ctx: commands.Context):
    """رتب الحروف المبعثرة (اللعبة القديمة حقت فكك)"""
    word = random.choice(WORD_BANK)
    scrambled = scramble(word)
    await start_round(ctx.channel, starter=ctx.author, title="رتب الحروف", prompt=f"رتب الحروف: **{scrambled}**",
                       checker=lambda c: normalize(c) == normalize(word),
                       reward=(25, 45), reveal=word, game_key="رتب")


@commands.command(name="اعكس")
async def reverse_cmd(ctx: commands.Context):
    word = random.choice(WORD_BANK)
    reversed_word = word[::-1]
    await start_round(ctx.channel, starter=ctx.author, title="اعكس الكلمة", prompt=f"اكتب هذي الكلمة بالعكس: **{word}**",
                       checker=lambda c: normalize(c) == normalize(reversed_word),
                       reward=(20, 35), reveal=reversed_word, game_key="اعكس")


@commands.command(name="صحح")
async def correct_cmd(ctx: commands.Context):
    wrong, correct = draw_no_repeat("spell", SPELL_BANK)
    await start_round(ctx.channel, starter=ctx.author, title="صحح الكلمة",
                       prompt=f"هذي الكلمة مكتوبة غلط: **{wrong}**\nاكتبها صح.",
                       checker=lambda c: normalize(c) == normalize(correct),
                       reward=(20, 35), reveal=correct)


# ---------- اعلام: اختيار المستوى بالأزرار قبل بدء الجولة ----------
class FlagLevelButton(discord.ui.Button):
    def __init__(self, tier: str):
        super().__init__(label=tier, style=discord.ButtonStyle.secondary)
        self.tier = tier

    async def callback(self, interaction: discord.Interaction):
        view: FlagLevelView = self.view
        if interaction.user.id != view.author.id:
            await interaction.response.send_message("هذي القائمة لصاحب الأمر بس.", ephemeral=True)
            return
        view.chosen = self.tier
        for c in view.children:
            c.disabled = True
        await interaction.response.edit_message(content=f"المستوى المختار: **{self.tier}**", view=view)
        view.stop()


class FlagLevelView(discord.ui.View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=30)
        self.author = author
        self.chosen: str | None = None
        self.message: discord.Message | None = None
        for tier in FLAG_TIERS:
            self.add_item(FlagLevelButton(tier))

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="انتهى الوقت، ما تم اختيار مستوى.", view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


@commands.command(name="اعلام")
async def flags_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "خمن الدولة")
    view = None
    try:
        view = FlagLevelView(ctx.author)
        msg = await ctx.send(f"{ctx.author.mention} اختر مستوى الأعلام اللي يناسب خبرتك:", view=view)
        view.message = msg
        cancel_event = track_game_message(ctx.channel.id, msg)
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.wait()), asyncio.create_task(cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            view.stop()
    finally:
        unmark_busy(ctx.channel.id)   # نفك القفل عشان نظام الجولة يمسكه بنفسه

    if view is None or view.chosen is None:
        return
    tier = view.chosen
    info = FLAG_TIERS[tier]
    flag, names = random.choice(info["flags"])
    await start_round(ctx.channel, starter=ctx.author, title=f"خمن الدولة — مستوى {tier}",
                       prompt=f"وش هذي الدولة؟ {flag}",
                       checker=lambda c: answer_matches(c, names),
                       reward=info["reward"], reveal=names[0], timeout=60, game_key="اعلام")


@commands.command(name="ايموجي")
async def emoji_guess_cmd(ctx: commands.Context):
    emojis, names, category = random.choice(EMOJI_GUESS_BANK)
    await start_round(ctx.channel, starter=ctx.author, title="خمن من الرموز",
                       prompt=f"وش تتوقع هالرموز؟ {emojis}\nالتصنيف: **{category}**",
                       checker=lambda c: answer_matches(c, names),
                       reward=(25, 45), reveal=names[0], timeout=60, game_key="ايموجي")


@commands.command(name="ادمج")
async def combine_cmd(ctx: commands.Context):
    emojis, answer = random.choice(COMPOUND_BANK)
    await start_round(ctx.channel, starter=ctx.author, title="ادمج وخمن", prompt=f"وش الكلمة اللي يرمز لها دمج: {emojis}",
                       checker=lambda c: normalize(c) == normalize(answer),
                       reward=(25, 45), reveal=answer, game_key="ادمج")


@commands.command(name="الوان")
async def colors_cmd(ctx: commands.Context):
    question, names = random.choice(COLOR_BANK)
    await start_round(ctx.channel, starter=ctx.author, title="خمن اللون", prompt=question,
                       checker=lambda c: answer_matches(c, names),
                       reward=(20, 35), reveal=names[0], timeout=45, game_key="الوان")


@commands.command(name="اسرع")
async def fastest_typer_cmd(ctx: commands.Context):
    phrase = random.choice(PHRASE_BANK)
    await start_round(ctx.channel, starter=ctx.author, title="أسرع كتابة",
                       prompt=f"اكتب هذي الجملة بالضبط بأسرع وقت:\n**{phrase}**",
                       checker=lambda c: normalize(c) == normalize(phrase),
                       reward=(30, 60), reveal=phrase, timeout=45, game_key="اسرع")


@commands.command(name="حرف")
async def letter_game_cmd(ctx: commands.Context):
    """الحرف الناقص: كلمة ناقصها حرف، واللي يخمن الحرف أول يفوز (مثال: د ك ＿ ن ← ا)."""
    word = draw_no_repeat("letter", LETTER_BANK)
    idx = random.randrange(len(word))
    missing = word[idx]
    prefix, suffix = word[:idx], word[idx + 1:]
    shown = " ".join(list(prefix) + ["＿"] + list(suffix))

    # الحروف المقبولة: الحرف الناقص الأصلي + أي حرف ثاني يكوّن كلمة ثانية صحيحة من نفس البنك
    accepted_letters = {normalize(missing)}
    accepted_words = {normalize(word)}
    for letter in _LETTER_CANDIDATES:
        candidate = normalize(prefix + letter + suffix)
        if candidate in _LETTER_BANK_NORM:
            accepted_letters.add(letter)
            accepted_words.add(candidate)

    def checker(content: str) -> bool:
        text = normalize(content).replace(" ", "")
        if len(text) == 1:
            return text in accepted_letters
        return text in accepted_words

    await start_round(ctx.channel, starter=ctx.author, title="الحرف الناقص",
                       prompt=(f"الكلمة: **{shown}**\n"
                               f"فيه حرف ناقص من الكلمة، خمنوه واكتبوا الحرف بس! (عدد حروف الكلمة: {len(word)})"),
                       checker=checker, reward=(20, 35), reveal=f"{missing} ({word})",
                       timeout=30, game_key="حرف")


@commands.command(name="ترتيب")
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
    await start_round(ctx.channel, starter=ctx.author, title="رتب الأرقام",
                       prompt=f"رتب هذي الأرقام تصاعديًا (اكتبهم بمسافة بينهم):\n**{nums_text}**",
                       checker=checker, reward=(20, 35), reveal=reveal_text, timeout=40, game_key="ترتيب")


@commands.command(name="كلمة")
async def word_chain_cmd(ctx: commands.Context):
    word = random.choice(STARTER_WORDS)
    last_letter = normalize(word)[-1]

    def checker(content: str) -> bool:
        c = normalize(content).replace(" ", "")
        return len(c) >= 2 and c[0] == last_letter and c != normalize(word)

    await start_round(ctx.channel, starter=ctx.author, title="سلسلة الكلمات",
                       prompt=f"الكلمة: **{word}**\nقولوا كلمة تبدأ بآخر حرف منها (حرف {word[-1]})",
                       checker=checker, reward=(15, 30), reveal="", timeout=30, game_key="كلمة")


# ---------- خمن (تخمين رقم — مفتوحة بالروم، فيها تلميح فوق/تحت) ----------
active_guess_games: dict[int, dict] = {}


@commands.command(name="خمن", aliases=["تخمين"])
async def guess_start(ctx: commands.Context, max_number: int = 100):
    if ctx.channel.id in active_guess_games or is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    if max_number < 10:
        await ctx.send("اختر رقم أقصى 10 أو أكثر.")
        return
    number = random.randint(1, max_number)
    active_guess_games[ctx.channel.id] = {"number": number, "max": max_number}
    mark_busy(ctx.channel.id, "خمن (تخمين رقم)")
    embed = discord.Embed(
        description=f"اخترت رقم سري بين **1** و **{max_number}**! اكتبوا تخمينكم.", color=VIBE_COLOR)
    image = attach_game_image(embed, "خمن")
    if image:
        msg = await ctx.send(embed=embed, file=image)
    else:
        msg = await ctx.send(embed=embed)
    track_game_message(ctx.channel.id, msg)


# ============================================================
# 6) ألعاب فردية تفاعلية (أزرار)
# ============================================================
class ElimButton(discord.ui.Button):
    def __init__(self, idx: int):
        super().__init__(label="...", style=discord.ButtonStyle.secondary, disabled=True, row=idx // 5)
        self.taken_by = None

    async def callback(self, interaction: discord.Interaction):
        view: ElimButtonView = self.view
        user = interaction.user
        if user.id not in view.alive_ids:
            await interaction.response.send_message("أنت مو باللعبة أو طحت من جولة سابقة.", ephemeral=True)
            return
        if user.id in view.claimed:
            await interaction.response.send_message("عندك زر مسبقًا.", ephemeral=True)
            return
        if self.taken_by is not None:
            await interaction.response.send_message("هذا الزر انأخذ.", ephemeral=True)
            return
        self.taken_by = user
        view.claimed[user.id] = user
        self.disabled = True
        self.label = user.display_name[:20]
        self.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=view)
        if len(view.claimed) >= len(view.children):
            view.done.set()


class ElimButtonView(discord.ui.View):
    """جولة وحدة: عدد الأزرار أقل من عدد اللاعبين، اللي ما يلحق زر يطيح."""

    def __init__(self, alive: list, button_count: int):
        super().__init__(timeout=120)
        self.alive_ids = {p.id for p in alive}
        self.claimed: dict = {}
        self.done = asyncio.Event()
        for i in range(button_count):
            self.add_item(ElimButton(i))

    def open_buttons(self):
        for b in self.children:
            b.disabled = False
            b.label = "اضغط"
            b.style = discord.ButtonStyle.secondary

    def lock_all(self):
        for b in self.children:
            b.disabled = True
            if b.taken_by is None:
                b.label = "فاضي"
                b.style = discord.ButtonStyle.secondary


async def _run_button_game(ctx: commands.Context, players: list):
    alive = players.copy()
    target = 5          # الجولة الأولى 5 أزرار، وبعدها تقل واحد كل جولة
    round_num = 1
    idle_rounds = 0
    while len(alive) > 1:
        n = max(1, min(target, len(alive) - 1))
        view = ElimButtonView(alive, n)
        names = "، ".join(p.mention for p in alive)
        msg = await ctx.send(
            f"**الجولة {round_num}** — {len(alive)} لاعبين و **{n}** أزرار بس!\n{names}\n"
            f"استعدوا... لما تصير خضراء اضغطوا زر (كل واحد ياخذ زر واحد). اللي ما يلحق زر يطيح!",
            view=view)
        cancel_event = track_game_message(ctx.channel.id, msg)
        await asyncio.sleep(random.uniform(2, 5))
        if cancel_event.is_set():
            return
        view.open_buttons()
        try:
            await msg.edit(content=f"**الجولة {round_num}** — اضغطوا الحين! ({n} أزرار)", view=view)
        except discord.NotFound:
            return
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.done.wait()), asyncio.create_task(cancel_event.wait())],
            timeout=10, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            return
        view.lock_all()
        view.stop()
        try:
            await msg.edit(view=view)
        except discord.NotFound:
            pass

        survivors = [p for p in alive if p.id in view.claimed]
        if not survivors:
            idle_rounds += 1
            if idle_rounds >= 2:
                await ctx.send("ما تفاعل أحد، انتهت اللعبة بدون فائز.")
                return
            await ctx.send("ما ضغط أحد! نعيد الجولة.")
            continue
        idle_rounds = 0
        out = [p for p in alive if p.id not in view.claimed]
        alive = survivors
        target = max(1, n - 1)
        await ctx.send(f"طاح: {'، '.join(p.mention for p in out)}")
        if len(alive) > 1:
            await ctx.send(f"الباقين ({len(alive)}): {'، '.join(p.mention for p in alive)}")
        round_num += 1

    winner = alive[0]
    actual = add_game_reward(ctx.guild.id, winner.id, 100)
    record_game_result(ctx.guild.id, winner.id, won=True)
    for p in players:
        if p != winner:
            record_game_result(ctx.guild.id, p.id, won=False)
    await ctx.send(f"فاز {winner.mention} بلعبة الأزرار! (+{actual} نقطة)")


@commands.command(name="زر")
async def button_game_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "زر (آخر ناجي)")
    try:
        players = await run_lobby(ctx, "لعبة الأزرار (آخر ناجي)", min_players=2, max_players=20, countdown=30, game_key="زر")
        if not players:
            return
        await _run_button_game(ctx, players)
    finally:
        unmark_busy(ctx.channel.id)


class MemoryButton(discord.ui.Button):
    def __init__(self, idx: int):
        super().__init__(label="؟", style=discord.ButtonStyle.secondary, row=idx // 4)
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        view: MemoryView = self.view
        if interaction.user != view.player:
            await interaction.response.send_message("هذي مو لعبتك.", ephemeral=True)
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
        if self.locked or self.matched[idx] or button.label != "؟":
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
                actual = add_game_reward(interaction.guild.id, self.player.id, pts)
                for b in self.buttons:
                    b.disabled = True
                emb = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(color=VIBE_COLOR)
                emb.description = f"خلصت اللعبة بعدد **{self.moves}** محاولة! (+{actual} نقطة)"
                await interaction.message.edit(embed=emb, view=self)
                self.stop()
            return
        await asyncio.sleep(1.2)
        self.buttons[i1].label = "؟"
        self.buttons[i2].label = "؟"
        self.selection = []
        self.locked = False
        try:
            await interaction.message.edit(view=self)
        except discord.NotFound:
            pass


@commands.command(name="اكشف")
async def memory_game_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "اكشف (لعبة الذاكرة)")
    try:
        view = MemoryView(ctx.author)
        embed = discord.Embed(
            description=f"{ctx.author.mention} لعبة الذاكرة! دور بطاقتين متطابقتين لين تلقى كل الأزواج.",
            color=VIBE_COLOR)
        image = attach_game_image(embed, "اكشف")
        if image:
            msg = await ctx.send(embed=embed, view=view, file=image)
        else:
            msg = await ctx.send(embed=embed, view=view)
        cancel_event = track_game_message(ctx.channel.id, msg)
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.wait()), asyncio.create_task(cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            view.stop()
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
        self.embed: discord.Embed | None = None   # إطار التحدي (فيه صورة اللعبة)

    @discord.ui.button(label=f"{UI_ICONS['accept']} موافقة", style=discord.ButtonStyle.secondary)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("هذا التحدي مو لك.", ephemeral=True)
            return
        self.result = True
        for c in self.children:
            c.disabled = True
        self.embed.description = f"{self.opponent.mention} وافق على تحدي **{self.game_name}**! يبدأ الحين..."
        await interaction.response.edit_message(embed=self.embed, view=self)
        self.stop()

    @discord.ui.button(label=f"{UI_ICONS['decline']} رفض", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("هذا التحدي مو لك.", ephemeral=True)
            return
        self.result = False
        for c in self.children:
            c.disabled = True
        self.embed.description = f"{self.opponent.mention} رفض تحدي **{self.game_name}**."
        await interaction.response.edit_message(embed=self.embed, view=self)
        self.stop()

    async def on_timeout(self):
        if self.result is None and self.message:
            for c in self.children:
                c.disabled = True
            self.embed.description = f"خلص الوقت! {self.opponent.mention} ما رد على تحدي **{self.game_name}**."
            try:
                await self.message.edit(embed=self.embed, view=self)
            except discord.NotFound:
                pass


async def send_challenge(ctx: commands.Context, opponent: discord.Member, game_name: str, game_key: str = "") -> bool:
    """يرسل دعوة تحدي للخصم وينتظر رده. يرجع True لو وافق، False لو رفض أو ما رد."""
    view = ChallengeView(ctx.author, opponent, game_name)
    text = f"{ctx.author.mention} يتحداك يا {opponent.mention} بلعبة **{game_name}**! تبي تلعب؟"
    embed = discord.Embed(title=f"تحدي {game_name}", description=text, color=VIBE_COLOR)
    view.embed = embed
    image = attach_game_image(embed, game_key)
    if image:
        msg = await ctx.send(content=opponent.mention, embed=embed, view=view, file=image)
    else:
        msg = await ctx.send(content=opponent.mention, embed=embed, view=view)
    view.message = msg
    await view.wait()
    return view.result is True


class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x, self.y = x, y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        user = interaction.user
        if view.done:
            await interaction.response.send_message("انتهت اللعبة.", ephemeral=True)
            return
        if user != view.current_player:
            await interaction.response.send_message("مو دورك!", ephemeral=True)
            return
        view.cancel_turn_timer()   # اللاعب لعب بوقته، نوقف عداد الـ 15 ثانية
        self.style = discord.ButtonStyle.secondary
        self.label = view.current_symbol
        self.disabled = True
        view.board[self.y][self.x] = view.current_symbol
        winner_symbol = view.check_winner()
        if winner_symbol:
            view.done = True
            winner = view.player_x if winner_symbol == "X" else view.player_o
            loser = view.player_o if winner_symbol == "X" else view.player_x
            for c in view.children:
                c.disabled = True
            actual = add_game_reward(interaction.guild.id, winner.id, 50)
            record_game_result(interaction.guild.id, winner.id, won=True)
            record_game_result(interaction.guild.id, loser.id, won=False)
            await interaction.response.edit_message(content=f"فاز {winner.mention}! (+{actual} نقطة)", view=view)
            view.stop()
            return
        if view.is_full():
            view.done = True
            for c in view.children:
                c.disabled = True
            await interaction.response.edit_message(content="تعادل!", view=view)
            view.stop()
            return
        view.switch_turn()
        await interaction.response.edit_message(
            content=(f"دور {view.current_player.mention} ({view.current_symbol})\n"
                     f"عندك {TURN_TIMEOUT} ثانية وإلا تخسر!"), view=view
        )
        view.start_turn_timer()


class TicTacToeView(discord.ui.View):
    def __init__(self, player_x: discord.Member, player_o: discord.Member):
        super().__init__(timeout=180)
        self.player_x, self.player_o = player_x, player_o
        self.current_player, self.current_symbol = player_x, "X"
        self.board = [[None, None, None] for _ in range(3)]
        self.guild_id = player_x.guild.id
        self.message: discord.Message | None = None
        self.done = False
        self.turn_token = 0
        self._turn_task: asyncio.Task | None = None
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

    # ---------- عداد دور اللاعب (15 ثانية) ----------
    def cancel_turn_timer(self):
        self.turn_token += 1
        task = self._turn_task
        self._turn_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def start_turn_timer(self):
        self.cancel_turn_timer()
        token = self.turn_token
        self._turn_task = asyncio.create_task(self._turn_watcher(token))

    async def _turn_watcher(self, token: int):
        try:
            await asyncio.sleep(TURN_TIMEOUT)
        except asyncio.CancelledError:
            return
        if token != self.turn_token or self.done or self.is_finished():
            return
        # اللي دوره ما لعب خلال المهلة → يخسر وخصمه يفوز
        self.done = True
        idle = self.current_player
        winner = self.player_o if idle == self.player_x else self.player_x
        for c in self.children:
            c.disabled = True
        actual = add_game_reward(self.guild_id, winner.id, 50)
        record_game_result(self.guild_id, winner.id, won=True)
        record_game_result(self.guild_id, idle.id, won=False)
        text = (f"{idle.mention} ما لعب خلال {TURN_TIMEOUT} ثانية وتم إخراجه من اللعبة!\n"
                f"فاز {winner.mention}! (+{actual} نقطة)")
        if self.message is not None:
            try:
                await self.message.edit(content=text, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
        self.stop()


@commands.command(name="xo")
async def xo_cmd(ctx: commands.Context, opponent: discord.Member):
    if opponent.bot or opponent == ctx.author:
        await ctx.send("اختر عضو ثاني حقيقي غيرك.")
        return
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "XO")
    try:
        accepted = await send_challenge(ctx, opponent, "XO", game_key="xo")
        if not accepted:
            return
        view = TicTacToeView(ctx.author, opponent)
        msg = await ctx.send(
            f"**XO**: {ctx.author.mention} (X) ضد {opponent.mention} (O)\n"
            f"دور {ctx.author.mention}\nعندك {TURN_TIMEOUT} ثانية وإلا تخسر!", view=view
        )
        view.message = msg
        view.start_turn_timer()
        cancel_event = track_game_message(ctx.channel.id, msg)
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.wait()), asyncio.create_task(cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            view.cancel_turn_timer()
            view.stop()
    finally:
        unmark_busy(ctx.channel.id)


class RPSView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=60)
        self.p1, self.p2 = p1, p2
        self.guild_id = p1.guild.id
        self.choices: dict[int, str] = {}
        self.message: discord.Message | None = None
        self.done = False
        self._timer: asyncio.Task | None = None

    # ---------- عداد الاختيار (15 ثانية) ----------
    def start_timer(self):
        self._timer = asyncio.create_task(self._watcher())

    def cancel_timer(self):
        task = self._timer
        self._timer = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _watcher(self):
        try:
            await asyncio.sleep(TURN_TIMEOUT)
        except asyncio.CancelledError:
            return
        if self.done or self.is_finished():
            return
        self.done = True
        for c in self.children:
            c.disabled = True
        missing = [p for p in (self.p1, self.p2) if p.id not in self.choices]
        if len(missing) == 2:
            text = f"ما اختار أحد خلال {TURN_TIMEOUT} ثانية — تم إلغاء اللعبة."
        else:
            idle = missing[0]
            winner = self.p2 if idle == self.p1 else self.p1
            actual = add_game_reward(self.guild_id, winner.id, 30)
            record_game_result(self.guild_id, winner.id, won=True)
            record_game_result(self.guild_id, idle.id, won=False)
            text = (f"{idle.mention} ما اختار خلال {TURN_TIMEOUT} ثانية وتم إخراجه من اللعبة!\n"
                    f"فاز {winner.mention}! (+{actual} نقطة)")
        if self.message is not None:
            try:
                await self.message.edit(content=text, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
        self.stop()

    async def handle_choice(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await interaction.response.send_message("هذا التحدي مو لك.", ephemeral=True)
            return
        if self.done:
            await interaction.response.send_message("انتهت اللعبة.", ephemeral=True)
            return
        if interaction.user.id in self.choices:
            await interaction.response.send_message("اخترت مسبقًا.", ephemeral=True)
            return
        self.choices[interaction.user.id] = choice
        await interaction.response.send_message(f"اخترت: {choice}", ephemeral=True)
        if len(self.choices) == 2:
            self.done = True
            self.cancel_timer()
            c1, c2 = self.choices[self.p1.id], self.choices[self.p2.id]
            result = self._decide(c1, c2)
            for c in self.children:
                c.disabled = True
            text = f"{self.p1.mention}: {c1}\n{self.p2.mention}: {c2}\n\n"
            if result == 0:
                text += "تعادل!"
            elif result == 1:
                actual = add_game_reward(interaction.guild.id, self.p1.id, 30)
                record_game_result(interaction.guild.id, self.p1.id, won=True)
                record_game_result(interaction.guild.id, self.p2.id, won=False)
                text += f"فاز {self.p1.mention}! (+{actual} نقطة)"
            else:
                actual = add_game_reward(interaction.guild.id, self.p2.id, 30)
                record_game_result(interaction.guild.id, self.p2.id, won=True)
                record_game_result(interaction.guild.id, self.p1.id, won=False)
                text += f"فاز {self.p2.mention}! (+{actual} نقطة)"
            await interaction.message.edit(content=text, view=self)
            self.stop()

    @staticmethod
    def _decide(c1, c2):
        if c1 == c2:
            return 0
        beats = {"حجر": "مقص", "مقص": "ورقة", "ورقة": "حجر"}
        return 1 if beats[c1] == c2 else 2

    @discord.ui.button(label="حجر", style=discord.ButtonStyle.secondary, emoji="🪨")
    async def rock(self, interaction, button):
        await self.handle_choice(interaction, "حجر")

    @discord.ui.button(label="ورقة", style=discord.ButtonStyle.secondary, emoji="📄")
    async def paper(self, interaction, button):
        await self.handle_choice(interaction, "ورقة")

    @discord.ui.button(label="مقص", style=discord.ButtonStyle.secondary, emoji="✂️")
    async def scissors(self, interaction, button):
        await self.handle_choice(interaction, "مقص")


@commands.command(name="حجرة", aliases=["rps"])
async def rps_cmd(ctx: commands.Context, opponent: discord.Member):
    if opponent.bot or opponent == ctx.author:
        await ctx.send("اختر عضو ثاني حقيقي غيرك.")
        return
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "حجرة ورقة مقص")
    try:
        accepted = await send_challenge(ctx, opponent, "حجرة ورقة مقص", game_key="حجرة")
        if not accepted:
            return
        view = RPSView(ctx.author, opponent)
        msg = await ctx.send(
            f"**حجرة ورقة مقص**: {ctx.author.mention} ضد {opponent.mention}\n"
            f"كل واحد يضغط بالخفاء (عندكم {TURN_TIMEOUT} ثانية)", view=view
        )
        view.message = msg
        view.start_timer()
        cancel_event = track_game_message(ctx.channel.id, msg)
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.wait()), asyncio.create_task(cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            view.cancel_timer()
            view.stop()
    finally:
        unmark_busy(ctx.channel.id)


# ============================================================
# 8) نظام اللوبي العام (للألعاب الجماعية — دخول/خروج/بدء، 30 ثانية، حتى 20 لاعب)
# ============================================================
class GameLobby(discord.ui.LayoutView):
    """لوبي الانضمام لكل الألعاب الجماعية (بما فيها الروليت): كل شي داخل إطار واحد —
    صورة اللعبة + عداد تنازلي حي + عدد المشاركين + اللاعبين + أزرار دخول / خروج / بدء.
    (يحتاج discord.py 2.6 أو أحدث)"""

    def __init__(self, host: discord.Member, game_title: str, min_players: int = 3,
                 max_players: int = 20, countdown: int = 30, game_key: str = ""):
        super().__init__(timeout=countdown + 30)
        self.host = host
        self.game_title = game_title
        self.min_players = min_players
        self.max_players = max_players
        self.players: list[discord.Member] = [host]
        self.started = False
        self.start_event = asyncio.Event()
        self.ends_at = discord.utils.utcnow() + timedelta(seconds=countdown)
        self.image_name = game_image_name(game_key)

        # ---------- الإطار ----------
        self.container = discord.ui.Container(accent_colour=VIBE_COLOR)
        if self.image_name:
            self.container.add_item(discord.ui.MediaGallery(
                discord.MediaGalleryItem(f"attachment://{self.image_name}")))
            self.container.add_item(discord.ui.Separator())
        self.title_text = discord.ui.TextDisplay("-")
        self.info_text = discord.ui.TextDisplay("-")
        self.players_text = discord.ui.TextDisplay("-")
        self.footer_text = discord.ui.TextDisplay("-")
        self.container.add_item(self.title_text)
        self.container.add_item(self.info_text)
        self.container.add_item(self.players_text)
        self.container.add_item(self.footer_text)
        self.container.add_item(discord.ui.Separator())

        # ---------- الأزرار (داخل نفس الإطار) ----------
        self.join_btn = discord.ui.Button(label=f"{UI_ICONS['join']} دخول", style=discord.ButtonStyle.secondary)
        self.leave_btn = discord.ui.Button(label=f"{UI_ICONS['leave']} خروج", style=discord.ButtonStyle.secondary)
        self.start_btn = discord.ui.Button(label=f"{UI_ICONS['start']} ابدأ الآن", style=discord.ButtonStyle.secondary)
        self.join_btn.callback = self.on_join
        self.leave_btn.callback = self.on_leave
        self.start_btn.callback = self.on_start
        self.container.add_item(discord.ui.ActionRow(self.join_btn, self.leave_btn, self.start_btn))
        self.add_item(self.container)
        self.refresh()

    def refresh(self, closed: bool = False) -> None:
        """يحدّث نصوص اللوحة (العداد، عدد المشاركين، اللاعبين)."""
        count_line = f"**عدد المشاركين:** ({len(self.players)} / {self.max_players})"
        self.title_text.content = f"### ◈  {self.game_title}"
        if closed:
            self.info_text.content = f"**انتهى وقت التسجيل**\n{count_line}"
        else:
            self.info_text.content = (f"**ستبدأ اللعبة خلال:** {discord.utils.format_dt(self.ends_at, 'R')}\n"
                                      f"{count_line}")
        players = "، ".join(m.mention for m in self.players) if self.players else "لا أحد"
        self.players_text.content = f"**اللاعبون**\n{players}"
        self.footer_text.content = f"-# الحد الأدنى {self.min_players} لاعبين  |  المضيف: {self.host.display_name}"

    def disable_buttons(self) -> None:
        for b in (self.join_btn, self.leave_btn, self.start_btn):
            b.disabled = True

    async def on_join(self, interaction: discord.Interaction):
        if interaction.user.bot:
            await interaction.response.send_message("البوتات ما تنلعب.", ephemeral=True)
            return
        if interaction.user in self.players:
            await interaction.response.send_message("أنت منضم مسبقًا.", ephemeral=True)
            return
        if len(self.players) >= self.max_players:
            await interaction.response.send_message(f"اللوبي مكتمل ({self.max_players} لاعب).", ephemeral=True)
            return
        self.players.append(interaction.user)
        self.refresh()
        await interaction.response.edit_message(view=self, allowed_mentions=discord.AllowedMentions.none())

    async def on_leave(self, interaction: discord.Interaction):
        if interaction.user not in self.players:
            await interaction.response.send_message("أنت مو منضم أصلًا.", ephemeral=True)
            return
        self.players.remove(interaction.user)
        if interaction.user == self.host and self.players:
            self.host = self.players[0]
        self.refresh()
        await interaction.response.edit_message(view=self, allowed_mentions=discord.AllowedMentions.none())

    async def on_start(self, interaction: discord.Interaction):
        if interaction.user != self.host:
            await interaction.response.send_message("بس المضيف يقدر يبدأ مبكرًا.", ephemeral=True)
            return
        if len(self.players) < self.min_players:
            await interaction.response.send_message(f"لازم {self.min_players} لاعبين على الأقل.", ephemeral=True)
            return
        self.disable_buttons()
        await interaction.response.edit_message(view=self, allowed_mentions=discord.AllowedMentions.none())
        self.started = True
        self.start_event.set()


async def run_lobby(ctx: commands.Context, game_title: str, min_players: int = 3,
                     max_players: int = 20, countdown: int = 30, game_key: str = ""):
    """يفتح لوبي جماعي، ويرجع قائمة اللاعبين إذا اكتمل العدد الأدنى، وإلا يرجع None."""
    if ctx.author.bot:
        return None
    lobby = GameLobby(ctx.author, game_title, min_players, max_players, countdown, game_key=game_key)
    image = game_image_file(game_key)
    if image:
        msg = await ctx.send(view=lobby, file=image, allowed_mentions=discord.AllowedMentions.none())
    else:
        msg = await ctx.send(view=lobby, allowed_mentions=discord.AllowedMentions.none())
    cancel_event = track_game_message(ctx.channel.id, msg)
    done, pending = await asyncio.wait(
        [asyncio.create_task(lobby.start_event.wait()), asyncio.create_task(cancel_event.wait())],
        timeout=countdown, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    if cancel_event.is_set():
        return None  # انحذفت رسالة اللوبي — معالج on_raw_message_delete هو اللي بلّغ بالإيقاف
    lobby.disable_buttons()
    lobby.refresh(closed=True)
    try:
        await msg.edit(view=lobby, allowed_mentions=discord.AllowedMentions.none())
    except discord.NotFound:
        pass
    if len(lobby.players) < min_players:
        await ctx.send(f"ما اكتمل العدد الأدنى ({min_players} لاعبين) — تم إلغاء لعبة **{game_title}**.")
        return None
    return lobby.players


# ============================================================
# 9) الألعاب الجماعية (تعتمد على اللوبي)
# ============================================================
# ---------- عجلة حقيقية (شريط أسماء يدور ويبطّئ لين يوقف على واحد) ----------
async def spin_wheel_on(msg: discord.Message, players: list, prefix: str = ""):
    """يدوّر عجلة بالتعديل على رسالة: الأسماء تلف بسرعة وتبطّئ تدريجيًا لين توقف على لاعب.
    يرجع اللاعب اللي وقفت عليه العجلة."""
    n = len(players)
    names = [p.display_name[:16] for p in players]
    winner_idx = random.randrange(n)
    frames = random.randint(12, 16)
    idx = (winner_idx - frames) % n   # بعد عدد الخطوات هذا توقف بالضبط على الفايز

    def render(i: int, header: str) -> str:
        rows = []
        for off in (-2, -1, 0, 1, 2):
            name = names[(i + off) % n]
            rows.append(f"» **{name}** «" if off == 0 else f"◦ {name}")
        return f"{prefix}{header}\n" + "\n".join(rows)

    try:
        await msg.edit(content=render(idx, "العجلة تدور..."))
        for step in range(frames):
            idx = (idx + 1) % n
            await asyncio.sleep(0.7 + 0.7 * step / (frames - 1))   # تبطّئ من 0.7 لين 1.4 ثانية
            await msg.edit(content=render(idx, "العجلة تدور..."))
    except discord.NotFound:
        pass
    await asyncio.sleep(0.8)
    return players[winner_idx]


# ---------- عجلة دائرية حقيقية (سهم ثابت + عجلة صور بروفايل اللاعبين تدور) — خاصة بالروليت بس ----------
# ألوان هادية مرتبة حسب درجة اللون — كل لاعب ياخذ لون عشوائي، ولا يتكرر لون بين لاعبين
WHEEL_COLORS = [
    '#A04B4B', '#B07E6D', '#8A6138', '#A08A4B', '#B0B06D', '#758A38', '#75A04B', '#7EB06D',
    '#388A38', '#4BA060', '#6DB08F', '#388A75', '#4BA0A0', '#6DA0B0', '#38618A', '#4B60A0',
    '#6D6DB0', '#4D388A', '#754BA0', '#A06DB0', '#8A388A', '#A04B8A', '#B06D8F', '#8A384D',
]
WHEEL_BG = (49, 51, 56)   # خلفية الـGIF (نفس لون خلفية ديسكورد الداكن)
_AVATAR_CACHE: dict = {}  # يحفظ صور اللاعبين عشان ما نحمّلها من جديد كل لفّة (يسرّع العجلة)


def _pick_sector_colors(n: int, rng) -> list:
    """يوزّع الألوان الهادية على الأقسام عشوائيًا، بدون تكرار، وبحيث الأقسام المتجاورة ألوانها مختلفة بوضوح."""
    total = len(WHEEL_COLORS)
    if n > total:
        return [rng.choice(WHEEL_COLORS) for _ in range(n)]
    offset = rng.randrange(total)
    steps = [5, 7, 11, 13]
    rng.shuffle(steps)

    def hue_gap(a, b):
        d = abs(a - b) % total
        return min(d, total - d)

    for k in steps:
        idxs = [(offset + i * k) % total for i in range(n)]
        if n < 2 or hue_gap(idxs[0], idxs[-1]) >= 3:
            return [WHEEL_COLORS[i] for i in idxs]
    return [WHEEL_COLORS[(offset + i * steps[0]) % total] for i in range(n)]


async def _get_avatar_circle(member: discord.Member, size: int = 160):
    """يحمّل أفتار العضو ويرجعه كصورة دائرية جاهزة للّصق. يرجع None لو فشل التحميل."""
    key = (member.id, getattr(member.display_avatar, "key", None), size)
    cached = _AVATAR_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = await member.display_avatar.replace(size=128, format="png").read()
        img = Image.open(BytesIO(data)).convert("RGBA").resize((size, size))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        circular = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        circular.paste(img, (0, 0), mask)
        if len(_AVATAR_CACHE) > 300:
            _AVATAR_CACHE.clear()
        _AVATAR_CACHE[key] = circular
        return circular
    except Exception as e:
        print(f"[روليت] تعذّر تحميل أفتار {member}: {e}")
        return None


def _wheel_layout(n: int, radius: float):
    """حجم الأفتار ومكانها حسب عدد اللاعبين: قليلين = أفتار كبيرة، كثيرين = يتوزعون على حلقتين عشان ما يتداخلون.
    يرجع (قطر_الأفتار, [نسب_بعدها_عن_المركز])."""
    if n <= 5:
        return int(radius * 0.56), [0.66]
    if n <= 8:
        return int(radius * 0.46), [0.68]
    if n <= 12:
        return int(radius * 0.36), [0.77, 0.52]
    return int(radius * 0.28), [0.80, 0.50]


def _prepare_wheel_assets(avatars: list, names: list, size: int = 360) -> list:
    """يجهّز صورة كل لاعب (الأفتار بإطار أبيض، أو حروف الاسم لو ما قدرنا نحمّل الصورة) مرة وحدة،
    عشان رسم الفريمات يكون سريع وسلس."""
    radius = size // 2 - 8
    avatar_size, _ = _wheel_layout(len(avatars), radius)
    ring_size = avatar_size + 6
    try:
        font = ImageFont.load_default(size=max(16, int(avatar_size * 0.4)))
    except TypeError:
        font = ImageFont.load_default()
    rings = []
    for i in range(len(avatars)):
        avatar_img = avatars[i]
        if avatar_img is not None:
            av = avatar_img.resize((avatar_size, avatar_size))
            ring = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((0, 0, ring_size, ring_size), fill=(255, 255, 255, 255))
            ring.paste(av, (3, 3), av)
        else:
            ring = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
            d = ImageDraw.Draw(ring)
            d.ellipse((0, 0, avatar_size, avatar_size), fill="#7289DA")
            text = names[i][:2] if names[i] else "?"
            tb = d.textbbox((0, 0), text, font=font)
            w, h = tb[2] - tb[0], tb[3] - tb[1]
            d.text(((avatar_size - w) / 2 - tb[0], (avatar_size - h) / 2 - tb[1]), text, fill="#FFFFFF", font=font)
        rings.append(ring)
    return rings


def _draw_wheel_frame(rings: list, colors: list, rotation_deg: float, size: int = 360, bg=None):
    """يرسم عجلة دائرية مقسّمة بعدد اللاعبين، كل قسم بلون هادي مختلف وبه صورة بروفايل العضو،
    وسهم ثابت فوق العجلة يشاور تحت."""
    top_margin = 40
    center = size // 2
    cy = top_margin + center
    radius = size // 2 - 8
    n = len(rings)
    sector = 360 / n
    _, factors = _wheel_layout(n, radius)
    rotation_deg = rotation_deg % 360
    img = Image.new("RGBA", (size, size + 40), bg if bg is not None else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bbox_box = [center - radius, cy - radius, center + radius, cy + radius]

    for i in range(n):
        start_angle = rotation_deg + i * sector
        draw.pieslice(bbox_box, start_angle, start_angle + sector,
                      fill=colors[i % len(colors)], outline="#2C2F33", width=2)

    for i in range(n):
        mid_angle = math.radians(rotation_deg + i * sector + sector / 2)
        text_radius = radius * factors[i % len(factors)]
        tx = center + text_radius * math.cos(mid_angle)
        ty = cy + text_radius * math.sin(mid_angle)
        ring = rings[i]
        img.paste(ring, (int(tx - ring.width / 2), int(ty - ring.height / 2)), ring)

    # إطار خارجي للعجلة
    draw.ellipse(bbox_box, outline="#23272A", width=4)
    # مركز العجلة
    draw.ellipse([center - 10, cy - 10, center + 10, cy + 10], fill="#23272A")
    # السهم الثابت فوق العجلة يشاور تحت
    arrow = [(center - 14, 6), (center + 14, 6), (center, 34)]
    draw.polygon(arrow, fill="#B9BBBE")
    return img


def _spin_schedule(total_spin: float, duration: float = 3.0, power: float = 2.2) -> list:
    """جدول فريمات اللفّة: [(زاوية_الدوران, مدة_الفريم_بالمللي)]. فريمات كثيرة وقت السرعة (سلاسة)
    وقليلة وقت التباطؤ (سرعة في التجهيز)."""
    frames = []
    t = 0.0
    while t < duration - 1e-9:
        speed = power * total_spin / duration * (1 - t / duration) ** (power - 1)   # درجة بالثانية
        dt = min(max(22 / max(speed, 1e-6), 0.05), 0.16)
        dt = min(dt, duration - t)
        t += dt
        angle = total_spin * (1 - (1 - t / duration) ** power)
        frames.append((angle, max(50, int(round(dt * 100)) * 10)))
    frames[-1] = (total_spin, frames[-1][1])
    return frames


def _build_wheel_gif(avatars: list, names: list, winner_index: int, colors: list):
    """يبني GIF واحد سلس للعبة العجلة وهي تدور وتبطّئ لين توقف بالضبط عند الفايز، مع صورة ثابتة للنتيجة.
    يرجع (gif_bytes, png_bytes, مدة_اللفّة_بالثواني)."""
    n = len(avatars)
    sector = 360 / n
    rings = _prepare_wheel_assets(avatars, names)

    # السهم فوق العجلة = زاوية 270 بنظام الرسم (pieslice تبدأ من 3 الساعة وتزيد باتجاه عقارب الساعة)
    target_offset = (270 - (winner_index * sector + sector / 2)) % 360
    start_rotation = random.uniform(0, 360)   # كل لفّة تبدأ من زاوية عشوائية
    total_spin = ((target_offset - start_rotation) % 360) + 360 * random.randint(2, 3)

    frames, durations = [], []
    for angle, dur in _spin_schedule(total_spin):
        frames.append(_draw_wheel_frame(rings, colors, start_rotation + angle, bg=WHEEL_BG).convert("RGB"))
        durations.append(dur)
    spin_secs = sum(durations) / 1000
    durations[-1] += 600   # وقفة قصيرة على النتيجة

    frames_p = [f.quantize(colors=128, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
                for f in frames]
    gif_buf = BytesIO()
    frames_p[0].save(gif_buf, format="GIF", save_all=True, append_images=frames_p[1:],
                     duration=durations, loop=0)

    final_img = _draw_wheel_frame(rings, colors, start_rotation + total_spin)
    png_buf = BytesIO()
    final_img.save(png_buf, format="PNG")
    return gif_buf.getvalue(), png_buf.getvalue(), spin_secs


async def _spin_wheel_image(msg: discord.Message, avatars: list, names: list, winner_index: int,
                             colors: list, header: str = "العجلة تدور...") -> None:
    """يدوّر عجلة دائرية فيها سهم ثابت (GIF واحد سلس بدون تقطيع)، لين توقف بالضبط عند اللاعب الفايز."""
    gif_bytes, png_bytes, spin_secs = await asyncio.to_thread(
        _build_wheel_gif, avatars, names, winner_index, colors)
    try:
        await msg.edit(content=header, attachments=[discord.File(BytesIO(gif_bytes), filename="wheel.gif")])
        await asyncio.sleep(spin_secs + 0.8)
        # نثبّت آخر صورة (بدل ما الـGIF يعيد نفسه)
        await msg.edit(attachments=[discord.File(BytesIO(png_bytes), filename="wheel.png")])
    except discord.NotFound:
        return


async def spin_and_choose(msg: discord.Message, players: list[discord.Member],
                           header: str = "العجلة تدور تختار...") -> discord.Member:
    """يدوّر عجلة دائرية فيها صور بروفايل اللاعبين وسهم ثابت، ويرجع اللاعب اللي وقف عليه السهم.
    الاختيار عشوائي 100%: ترتيب الأقسام على العجلة يتخربط كل مرة، والفايز يتحدد بعشوائية النظام،
    ومافيه أي أفضلية للمضيف أو لرقم المقعد. لو Pillow مو متوفرة، يرجع لأسلوب العجلة النصية القديم."""
    if not players:
        return None
    rng = random.SystemRandom()
    order = list(players)
    rng.shuffle(order)                       # ترتيب الأقسام على العجلة عشوائي
    n = len(order)
    winner_idx = rng.randrange(n)            # الفايز عشوائي
    if PIL_AVAILABLE:
        try:
            avatars = await asyncio.gather(*(_get_avatar_circle(p) for p in order))
            names = [p.display_name for p in order]
            colors = _pick_sector_colors(n, rng)
            await _spin_wheel_image(msg, list(avatars), names, winner_idx, colors, header=header)
            return order[winner_idx]
        except Exception as e:
            print(f"[روليت] تعذّر رسم العجلة الدائرية، رجعنا لأسلوب النص: {e}")
    return await spin_wheel_on(msg, order, prefix=header + "\n")


# ---------- روليت روسي ----------
class RouletteView(discord.ui.View):
    def __init__(self, players: list[discord.Member], channel: discord.abc.Messageable):
        # بدون مهلة عامة: كل دور له عداد خاص (TURN_TIMEOUT) واللعبة تتقدم لحالها
        super().__init__(timeout=None)
        self.channel = channel
        self.guild = channel.guild
        self.all_players = players.copy()
        self.remaining = players.copy()
        self.chosen: discord.Member | None = None
        self.spinning = False
        self.current_msg: discord.Message | None = None   # رسالة الأزرار الحالية
        self.turn_token = 0
        self._turn_task: asyncio.Task | None = None
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for member in self.remaining:
            if member == self.chosen:
                continue
            btn = discord.ui.Button(label=member.display_name, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(member)
            self.add_item(btn)
        # زر الطرد العشوائي
        random_btn = discord.ui.Button(label="اختيار عشوائي" if len(self.remaining) == 2 else "طرد عشوائي",
                                      style=discord.ButtonStyle.secondary)
        random_btn.callback = self._random_callback
        self.add_item(random_btn)
        # زر الانسحاب (أي لاعب باقي يقدر ينسحب من اللعبة)
        withdraw_btn = discord.ui.Button(label="انسحاب", style=discord.ButtonStyle.secondary)
        withdraw_btn.callback = self._withdraw_callback
        self.add_item(withdraw_btn)

    def _turn_text(self, header: str = "") -> str:
        """نص رسالة الدور الحالي (اللاعبين الباقين + مين دوره)."""
        names = "، ".join(m.mention for m in self.remaining)
        body = (f"اللاعبون: {names}\n\n"
                f"دور {self.chosen.mention} {'يختار مين يفوز!' if len(self.remaining) == 2 else 'يختار وحد يطلعه!'}\n"
                f"عندك {TURN_TIMEOUT} ثانية وإلا تطلع من اللعبة!")
        return f"{header}\n{body}" if header else body

    # ---------- عداد دور اللاعب المختار (15 ثانية) ----------
    def _cancel_turn_timer(self):
        self.turn_token += 1
        task = self._turn_task
        self._turn_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def start_turn_timer(self):
        self._cancel_turn_timer()
        token = self.turn_token
        self._turn_task = asyncio.create_task(self._turn_watcher(token))

    async def _turn_watcher(self, token: int):
        """لو اللاعب المختار ما طلّع أحد خلال TURN_TIMEOUT ثانية، البوت يطلّعه هو من اللعبة ويكمل."""
        try:
            await asyncio.sleep(TURN_TIMEOUT)
        except asyncio.CancelledError:
            return
        if token != self.turn_token or self.spinning or self.is_finished():
            return
        idle = self.chosen
        if idle is None or idle not in self.remaining:
            return
        self.spinning = True
        self.remaining.remove(idle)
        self.chosen = None
        for c in self.children:
            c.disabled = True
        elim_text = f"{idle.mention} ما اختار خلال {TURN_TIMEOUT} ثانية وتم إخراجه من اللعبة!"
        try:
            if len(self.remaining) == 1:
                # ما بقي إلا واحد → هو الفايز
                if self.current_msg is not None:
                    await self.current_msg.edit(view=None)
                await self.channel.send(elim_text)
                await self._announce_winner(self.remaining[0])
                return
            if self.current_msg is not None:
                await self.current_msg.edit(content="العجلة تدور...", view=None)
            await self.channel.send(elim_text)
            await self._spin_next()
        except discord.NotFound:
            self.stop()
        except Exception as e:
            print(f"[روليت] خطأ بعداد الدور: {e}")
            self.stop()
        finally:
            self.spinning = False

    async def _announce_winner(self, winner: discord.Member):
        actual = add_game_reward(self.guild.id, winner.id, 100)
        record_game_result(self.guild.id, winner.id, won=True)
        for p in self.all_players:
            if p != winner:
                record_game_result(self.guild.id, p.id, won=False)
        await self.channel.send(f"الفايز: {winner.mention}! (+{actual} نقطة)")
        self.stop()

    async def _spin_next(self):
        """يدوّر العجلة بين اللاعبين الباقين ويختار مين دوره (أو يعلن الفايز لو باقي اثنين بس)."""
        new_msg = await self.channel.send("العجلة تدور...")
        chosen = await spin_and_choose(new_msg, self.remaining, header="العجلة تدور...")

        # آخر راوند: باقي اثنين بس → اللي طلعت عليه العجلة يفوز على طول بدون ما يختار
        if len(self.remaining) == 2:
            self.chosen = chosen
            await new_msg.edit(content=f"وقفت العجلة على {chosen.mention}!")
            await self._announce_winner(chosen)
            return

        self.chosen = chosen
        self._build_buttons()
        self.current_msg = new_msg
        await new_msg.edit(content=self._turn_text(), view=self)
        self.start_turn_timer()

    def _make_callback(self, target: discord.Member):
        async def callback(interaction: discord.Interaction):
            if self.spinning:
                await interaction.response.send_message("العجلة تدور، انتظر...", ephemeral=True)
                return
            if interaction.user != self.chosen:
                await interaction.response.send_message("مو دورك!", ephemeral=True)
                return
            await self._eliminate(interaction, target, pick_wins=(len(self.remaining) == 2))
        return callback

    async def _random_callback(self, interaction: discord.Interaction):
        if self.spinning:
            await interaction.response.send_message("العجلة تدور، انتظر...", ephemeral=True)
            return
        if interaction.user != self.chosen:
            await interaction.response.send_message("مو دورك!", ephemeral=True)
            return
        candidates = [m for m in self.remaining if m != self.chosen]
        if not candidates:
            await interaction.response.send_message("ما فيه أحد تطرده.", ephemeral=True)
            return
        target = random.choice(candidates)
        await self._eliminate(interaction, target, pick_wins=(len(self.remaining) == 2))

    async def _withdraw_callback(self, interaction: discord.Interaction):
        """انسحاب: أي لاعب باقي يقدر يطلع نفسه من اللعبة."""
        user = interaction.user
        if self.spinning:
            await interaction.response.send_message("العجلة تدور، انتظر...", ephemeral=True)
            return
        if user not in self.remaining:
            await interaction.response.send_message("أنت مو باللعبة.", ephemeral=True)
            return

        # اللاعب المختار ينسحب: نفس مسار الطرد (يطلع ويدور العجلة للدور الجاي)
        if user == self.chosen:
            await self._eliminate(interaction, user, text=f"{user.mention} انسحب من اللعبة.")
            return

        # لاعب ثاني ينسحب أثناء دور غيره: نشيله من القائمة ونحدّث الأزرار
        self.remaining.remove(user)
        self._build_buttons()
        await interaction.response.edit_message(content=self._turn_text(), view=self)
        await interaction.channel.send(f"{user.mention} انسحب من اللعبة.")

    async def _eliminate(self, interaction: discord.Interaction, target: discord.Member,
                         text: str | None = None, pick_wins: bool = False):
        if target not in self.remaining:
            await interaction.response.send_message("هذا اللاعب طلع من اللعبة أصلًا.", ephemeral=True)
            return
        # آخر اثنين: اللي يختاره اللاعب هو اللي يفوز (مو يطلع)
        if pick_wins and len(self.remaining) == 2:
            self.spinning = True
            self._cancel_turn_timer()
            try:
                for c in self.children:
                    c.disabled = True
                await interaction.response.edit_message(view=self)
                await interaction.channel.send(f"{interaction.user.mention} اختار {target.mention} يفوز!")
                await self._announce_winner(target)
            except discord.NotFound:
                self.stop()
            finally:
                self.spinning = False
            return
        self.spinning = True
        self._cancel_turn_timer()   # اللاعب اختار بوقته، نوقف عداد الـ 15 ثانية
        self.remaining.remove(target)
        elim_text = text or f"{interaction.user.mention} أقصى {target.mention} من اللعبة!"
        try:
            if len(self.remaining) == 1:
                winner = self.remaining[0]
                for c in self.children:
                    c.disabled = True
                await interaction.response.edit_message(view=self)
                await interaction.channel.send(elim_text)
                await self._announce_winner(winner)
                return

            # العجلة الدائرية تدور وتختار مين دوره يطلع وحد — كل جولة برسالة جديدة (بدون المطرود)
            await interaction.response.edit_message(content="العجلة تدور...", view=None)
            await interaction.channel.send(elim_text)   # تطلع تحت رسالة الأزرار
            await self._spin_next()
        except discord.NotFound:
            self.stop()
        finally:
            self.spinning = False


@commands.command(name="روليت")
async def roulette_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "روليت")
    view = None
    try:
        players = await run_lobby(ctx, "الروليت الروسي", min_players=2, max_players=20, countdown=30, game_key="روليت")
        if not players:
            return
        view = RouletteView(players, ctx.channel)
        header = "**بدأت اللعبة!** العجلة تدور تختار مين يبدأ..."
        msg = await ctx.send(header)
        cancel_event = track_game_message(ctx.channel.id, msg)
        chosen = await spin_and_choose(msg, players, header=header)
        if cancel_event.is_set():
            return
        view.chosen = chosen
        view._build_buttons()
        view.current_msg = msg
        await msg.edit(content=view._turn_text(header=header), view=view)
        view.start_turn_timer()
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.wait()), asyncio.create_task(cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            view.stop()
    finally:
        if view is not None:
            view._cancel_turn_timer()
        unmark_busy(ctx.channel.id)


# ---------- نرد ----------
class DiceRollView(discord.ui.View):
    """زر "ارمِ النرد" — كل لاعب يرمي بنفسه مرة وحدة، والرقم عشوائي من 1 إلى 6."""

    def __init__(self, players: list[discord.Member], seconds: int = 10):
        super().__init__(timeout=seconds + 10)
        self.players = players
        self.seconds = seconds
        self.rolls: dict[int, int] = {}
        self.auto_ids: set[int] = set()
        self.closed = False
        self.all_rolled = asyncio.Event()

    def status_text(self, final: bool = False) -> str:
        lines = []
        for p in self.players:
            if p.id in self.rolls:
                tag = " (تلقائي)" if p.id in self.auto_ids else ""
                lines.append(f"{p.mention}: **{self.rolls[p.id]}**{tag}")
            else:
                lines.append(f"{p.mention}: ما رمى بعد")
        if final:
            header = "**انتهى الوقت!**"
        else:
            header = f"**النرد** — اضغط الزر وارمِ النرد بنفسك! عندكم {self.seconds} ثواني"
        return header + "\n\n" + "\n".join(lines)

    @discord.ui.button(label=f"{UI_ICONS['dice']} ارمِ النرد", style=discord.ButtonStyle.secondary)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed:
            await interaction.response.send_message("خلص الوقت.", ephemeral=True)
            return
        if interaction.user.id not in {p.id for p in self.players}:
            await interaction.response.send_message("أنت مو باللعبة.", ephemeral=True)
            return
        if interaction.user.id in self.rolls:
            await interaction.response.send_message(
                f"رميت مسبقًا ورقمك **{self.rolls[interaction.user.id]}**.", ephemeral=True)
            return
        self.rolls[interaction.user.id] = random.randint(1, 6)
        if len(self.rolls) >= len(self.players):
            self.all_rolled.set()
        await interaction.response.edit_message(content=self.status_text(), view=self)


@commands.command(name="نرد")
async def dice_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "نرد")
    try:
        players = await run_lobby(ctx, "لعبة النرد", min_players=2, max_players=20, countdown=30, game_key="نرد")
        if not players:
            return
        view = DiceRollView(players, seconds=10)
        msg = await ctx.send(view.status_text(), view=view)
        cancel_event = track_game_message(ctx.channel.id, msg)
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.all_rolled.wait()), asyncio.create_task(cancel_event.wait())],
            timeout=view.seconds, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            view.stop()
            return
        view.closed = True
        # اللي ما رمى خلال المهلة يرمي له البوت تلقائيًا
        for p in players:
            if p.id not in view.rolls:
                view.rolls[p.id] = random.randint(1, 6)
                view.auto_ids.add(p.id)
        for c in view.children:
            c.disabled = True
        view.stop()
        try:
            await msg.edit(content=view.status_text(final=True), view=view)
        except discord.NotFound:
            pass

        rolls = {p: view.rolls[p.id] for p in players}
        top = max(rolls.values())
        winners = [p for p in players if rolls[p] == top]
        lines = "\n".join(
            f"{p.mention}: {rolls[p]}{' (تلقائي)' if p.id in view.auto_ids else ''}" for p in players)
        actual_amounts = []
        for w in winners:
            actual_amounts.append(add_game_reward(ctx.guild.id, w.id, 60))
            record_game_result(ctx.guild.id, w.id, won=True)
        for p in players:
            if p not in winners:
                record_game_result(ctx.guild.id, p.id, won=False)
        winners_text = " و ".join(w.mention for w in winners)
        if len(set(actual_amounts)) == 1:
            reward_text = f"(+{actual_amounts[0]} نقطة{' لكل واحد' if len(winners) > 1 else ''})"
        else:
            reward_text = "(" + "، ".join(f"{w.mention}: +{a}" for w, a in zip(winners, actual_amounts)) + ")"
        await ctx.send(f"**نتائج الرمي:**\n{lines}\n\nالفائز: {winners_text} {reward_text}")
    finally:
        unmark_busy(ctx.channel.id)


# ---------- عجلة الحظ ----------
@commands.command(name="عجلة")
async def wheel_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "عجلة الحظ")
    try:
        players = await run_lobby(ctx, "عجلة الحظ", min_players=2, max_players=20, countdown=30, game_key="عجلة")
        if not players:
            return
        msg = await ctx.send("**العجلة تدور تختار الفايز...**")
        cancel_event = track_game_message(ctx.channel.id, msg)
        pts = random.randint(50, 150)
        winner = await spin_and_choose(msg, players, header="**العجلة تدور تختار الفايز...**")
        if cancel_event.is_set():
            return
        actual = add_game_reward(ctx.guild.id, winner.id, pts)
        record_game_result(ctx.guild.id, winner.id, won=True)
        for p in players:
            if p != winner:
                record_game_result(ctx.guild.id, p.id, won=False)
        await ctx.send(f"الفايز: {winner.mention}! (+{actual} نقطة)")
    finally:
        unmark_busy(ctx.channel.id)


# ---------- غميضة ----------
class HideSeekButton(discord.ui.Button):
    def __init__(self, number: int):
        super().__init__(label=str(number), style=discord.ButtonStyle.secondary, row=(number - 1) // 5)
        self.number = number

    async def callback(self, interaction: discord.Interaction):
        view: HideSeekView = self.view
        if interaction.user != view.seeker:
            await interaction.response.send_message("أنت مو الباحث بهذي اللعبة.", ephemeral=True)
            return
        if self.disabled:
            await interaction.response.send_message("هذا الرقم انفتح مسبقًا.", ephemeral=True)
            return

        occupant = view.spots.get(self.number)
        self.disabled = True

        if occupant is not None:
            self.label = occupant.display_name[:12]
            self.style = discord.ButtonStyle.secondary
            view.found.add(occupant.id)
            add_game_reward(interaction.guild.id, view.seeker.id, 20)
            await interaction.response.edit_message(view=view)
            await interaction.channel.send(f"لقيت {occupant.mention}!")
        else:
            self.label = "فاضي"
            self.style = discord.ButtonStyle.secondary
            view.attempts_used += 1
            remaining_attempts = view.max_attempts - view.attempts_used
            await interaction.response.edit_message(content=view.status_text(remaining_attempts), view=view)

        if len(view.found) >= len(view.hiders):
            view.all_found.set()
        elif view.attempts_used >= view.max_attempts:
            view.attempts_exhausted.set()


class HideSeekView(discord.ui.View):
    def __init__(self, seeker: discord.Member, hiders: list[discord.Member]):
        super().__init__(timeout=90)
        self.seeker = seeker
        self.hiders = hiders

        # عدد الأماكن (بعضها فاضي — فخاخ) وعدد المحاولات، الاثنين يكبرون مع عدد اللاعبين.
        # القاعدة: أماكن = ضعف عدد المختبئين تقريبًا (بحد أقصى 20)، محاولات = 1.5 × عددهم (بحد أدنى 4).
        hiders_count = len(hiders)
        self.spot_count = min(20, max(hiders_count + 3, hiders_count * 2))
        self.max_attempts = max(4, math.ceil(hiders_count * 1.5) + 1)
        self.attempts_used = 0

        numbers = list(range(1, self.spot_count + 1))
        random.shuffle(numbers)
        hider_numbers = numbers[:hiders_count]
        self.spots: dict[int, discord.Member | None] = {n: None for n in range(1, self.spot_count + 1)}
        for num, p in zip(hider_numbers, hiders):
            self.spots[num] = p

        self.found: set[int] = set()
        self.all_found = asyncio.Event()
        self.attempts_exhausted = asyncio.Event()
        for n in range(1, self.spot_count + 1):
            self.add_item(HideSeekButton(n))

    def status_text(self, remaining_attempts: int) -> str:
        return (f"{self.seeker.mention} هو الباحث! الباقين مختبئين بين **{self.spot_count}** مكان.\n"
                f"محاولة غلط! باقي لك **{remaining_attempts}** محاولة.")


@commands.command(name="غميضة")
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
    players = await run_lobby(ctx, "غميضة", min_players=2, max_players=20, countdown=30, game_key="غميضة")
    if not players:
        return
    seeker = random.choice(players)
    hiders = [p for p in players if p != seeker]
    view = HideSeekView(seeker, hiders)
    msg = await ctx.send(
        f"{seeker.mention} هو الباحث! الباقين مختبئين بين **{view.spot_count}** مكان.\n"
        f"عندك **{view.max_attempts}** محاولة بس — اضغط على رقم عشان تبحث فيه", view=view
    )
    cancel_event = track_game_message(ctx.channel.id, msg)
    done, pending = await asyncio.wait(
        [asyncio.create_task(view.all_found.wait()),
         asyncio.create_task(view.attempts_exhausted.wait()),
         asyncio.create_task(cancel_event.wait())],
        timeout=90, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    if cancel_event.is_set():
        return
    for c in view.children:
        c.disabled = True
    try:
        if len(view.found) >= len(hiders):
            await ctx.send("لقاهم كلهم!")
        elif view.attempts_exhausted.is_set():
            await ctx.send("خلصت محاولاتك!")
        else:
            await ctx.send("خلص وقت البحث!")
    except discord.NotFound:
        pass
    for p in hiders:
        if p.id not in view.found:
            add_game_reward(ctx.guild.id, p.id, 40)
    remaining = len(hiders) - len(view.found)
    await ctx.send(f"{seeker.mention} لقى **{len(view.found)}** وبقي **{remaining}** ماله دري عنهم.")


# ---------- ريبلكا (احفظ الترتيب) ----------
@commands.command(name="ريبلكا")
async def replica_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "ريبلكا (احفظ الترتيب)")
    players = await run_lobby(ctx, "ريبلكا (احفظ الترتيب)", min_players=2, max_players=20, countdown=30, game_key="ريبلكا")
    if not players:
        unmark_busy(ctx.channel.id)
        return
    pool = ["🔥", "💧", "🌪️", "🌙", "⭐", "🍀", "⚡", "🎵", "🎯", "🧩"]
    sequence = random.sample(pool, k=5)
    seq_text = " ".join(sequence)
    msg = await ctx.send(f"احفظوا هذا الترتيب:\n\n# {seq_text}")
    cancel_event = track_game_message(ctx.channel.id, msg)
    await asyncio.sleep(5)
    if cancel_event.is_set():
        return
    try:
        await msg.edit(content="**ريبلكا**: اكتبوا نفس الترتيب بالضبط (افصلوا بمسافة)!")
    except discord.NotFound:
        pass
    allowed = {p.id for p in players}
    unmark_busy(ctx.channel.id)  # نسلّم القفل لنظام الجولة اللي بيدير حالته بنفسه لين الحل أو انتهاء الوقت
    await start_round(ctx.channel, starter=ctx.author, title="ريبلكا", prompt="اكتبوا الترتيب اللي حفظتوه",
                       checker=lambda c: normalize(c) == normalize(seq_text),
                       reward=(60, 100), allowed_ids=allowed, timeout=30, reveal=seq_text)


# ---------- مافيا (نسخة مبسطة: جولة تصويت وحدة) ----------
@commands.command(name="مافيا")
async def mafia_cmd(ctx: commands.Context):
    if is_channel_busy(ctx.channel.id):
        await warn_busy(ctx)
        return
    mark_busy(ctx.channel.id, "مافيا")
    try:
        await _run_mafia(ctx)
    finally:
        unmark_busy(ctx.channel.id)


class MafiaRoleView(discord.ui.View):
    """زر "اكشف دورك" — كل لاعب يضغطه ويشوف دوره برسالة خفية بنفس الروم (محد يشوفها غيره)."""

    def __init__(self, players: list[discord.Member], mafia: set):
        super().__init__(timeout=90)
        self.players_ids = {p.id for p in players}
        self.mafia_ids = {p.id for p in mafia}
        self.mafia_members = list(mafia)

    @discord.ui.button(label="اكشف دورك", style=discord.ButtonStyle.secondary)
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.players_ids:
            await interaction.response.send_message("أنت مو باللعبة.", ephemeral=True)
            return
        if interaction.user.id in self.mafia_ids:
            text = "أنت **مافيا**! هدفك تضلل الكل وتفلت."
            allies = [m for m in self.mafia_members if m.id != interaction.user.id]
            if allies:
                text += "\nخوياك المافيا: " + "، ".join(m.mention for m in allies)
            else:
                text += "\nأنت المافيا الوحيد بهذي اللعبة."
        else:
            text = "أنت **مواطن**! هدفك تكتشف المافيا."
        await interaction.response.send_message(text, ephemeral=True)


class MafiaVoteView(discord.ui.View):
    """أزرار تصويت — زر لكل لاعب باقي بالجولة، يضغط عليه اللي يشك فيه (يقدر يغيّر صوته)."""

    def __init__(self, players: list[discord.Member], duration: int = 60):
        super().__init__(timeout=duration + 10)
        self.players = players
        self.votes: dict[int, int] = {}  # voter_id -> target_id
        self.done = asyncio.Event()
        for p in players:
            btn = discord.ui.Button(label=p.display_name[:20], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(p)
            self.add_item(btn)

    def _make_cb(self, target: discord.Member):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id not in {p.id for p in self.players}:
                await interaction.response.send_message("أنت مو باللعبة.", ephemeral=True)
                return
            self.votes[interaction.user.id] = target.id
            await interaction.response.send_message(f"صوّتّ ضد {target.mention}", ephemeral=True)
            if len(self.votes) >= len(self.players):
                self.done.set()
        return cb

    def tally(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for target_id in self.votes.values():
            counts[target_id] = counts.get(target_id, 0) + 1
        return counts


async def _run_mafia(ctx: commands.Context):
    players = await run_lobby(ctx, "مافيا", min_players=2, max_players=20, countdown=30, game_key="مافيا")
    if not players:
        return
    mafia_count = max(1, len(players) // 4)
    mafia = set(random.sample(players, mafia_count))

    role_view = MafiaRoleView(players, mafia)
    announce_msg = await ctx.send(
        f"بدأت اللعبة! فيه **{mafia_count}** من المافيا بينكم.\n"
        f"اضغط الزر تحت عشان تشوف دورك (يبان لك بس):",
        view=role_view,
    )
    cancel_event = track_game_message(ctx.channel.id, announce_msg)
    await asyncio.sleep(20)  # وقت مناقشة قصير قبل التصويت
    if cancel_event.is_set():
        return

    vote_view = MafiaVoteView(players, duration=60)
    vote_msg = await ctx.send("صوّتوا بالضغط على اسم اللي تشكون فيه (عندكم 60 ثانية):", view=vote_view)
    cancel_event = track_game_message(ctx.channel.id, vote_msg)
    done, pending = await asyncio.wait(
        [asyncio.create_task(vote_view.done.wait()), asyncio.create_task(cancel_event.wait())],
        timeout=60, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    if cancel_event.is_set():
        return
    for c in vote_view.children:
        c.disabled = True
    try:
        await vote_msg.edit(view=vote_view)
    except discord.NotFound:
        pass

    tally = vote_view.tally()
    if not tally:
        await ctx.send("ما صوّت أحد! انتهت اللعبة بدون نتيجة.")
        return

    max_votes = max(tally.values())
    top_ids = [uid for uid, v in tally.items() if v == max_votes]
    eliminated_id = random.choice(top_ids)
    eliminated = discord.utils.get(players, id=eliminated_id)
    was_mafia = eliminated in mafia

    if was_mafia:
        winners = [p for p in players if p not in mafia]
        result = f"{eliminated.mention} كان من المافيا! فاز المواطنون"
    else:
        winners = list(mafia)
        result = f"{eliminated.mention} كان بريء! فازت المافيا"

    for w in winners:
        add_game_reward(ctx.guild.id, w.id, 50)
        record_game_result(ctx.guild.id, w.id, won=True)
    for p in players:
        if p not in winners:
            record_game_result(ctx.guild.id, p.id, won=False)
    mafia_names = "، ".join(m.mention for m in mafia)
    await ctx.send(f"{result}\n\nالمافيا كانوا: {mafia_names}")


# ---------- كراسي موسيقية ----------
class ChairsView(discord.ui.View):
    def __init__(self, players: list[discord.Member]):
        super().__init__(timeout=15)
        self.remaining = players.copy()
        self.taken: set[int] = set()
        self.done = asyncio.Event()
        self.chairs = max(1, len(players) - 1)
        for i in range(self.chairs):
            btn = discord.ui.Button(label=f"كرسي {i + 1}", style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(btn)
            self.add_item(btn)

    def _make_cb(self, btn: discord.ui.Button):
        async def cb(interaction: discord.Interaction):
            if interaction.user not in self.remaining:
                await interaction.response.send_message("أنت مو باللعبة.", ephemeral=True)
                return
            if interaction.user.id in self.taken:
                await interaction.response.send_message("عندك كرسي مسبقًا.", ephemeral=True)
                return
            if btn.disabled:
                await interaction.response.send_message("هذا الكرسي مأخوذ.", ephemeral=True)
                return
            btn.disabled = True
            btn.label = interaction.user.display_name[:20]
            btn.style = discord.ButtonStyle.secondary
            self.taken.add(interaction.user.id)
            await interaction.response.edit_message(view=self)
            if len(self.taken) >= self.chairs:
                self.done.set()
        return cb


@commands.command(name="كراسي")
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
    players = await run_lobby(ctx, "الكراسي الموسيقية", min_players=2, max_players=20, countdown=30, game_key="كراسي")
    if not players:
        return
    all_players = players.copy()
    round_num = 1
    while len(players) > 1:
        view = ChairsView(players)
        msg = await ctx.send(
            f"**الجولة {round_num}**: {len(players)} لاعبين و {max(1, len(players) - 1)} كرسي! بسرعة اقعدوا",
            view=view)
        cancel_event = track_game_message(ctx.channel.id, msg)
        done, pending = await asyncio.wait(
            [asyncio.create_task(view.done.wait()), asyncio.create_task(cancel_event.wait())],
            timeout=10, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if cancel_event.is_set():
            return
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
            await ctx.send(f"طاح {eliminated.mention}! الباقين: {'، '.join(p.mention for p in players)}")
        round_num += 1
    if players:
        winner = players[0]
        actual = add_game_reward(ctx.guild.id, winner.id, 100)
        record_game_result(ctx.guild.id, winner.id, won=True)
        for p in all_players:
            if p != winner:
                record_game_result(ctx.guild.id, p.id, won=False)
        await ctx.send(f"فاز {winner.mention} بلعبة الكراسي! (+{actual} نقطة)")


# ============================================================
# 10) مركز الألعاب: .العاب و .شرح
# ============================================================
GAME_LIST = {
    "جماعية": [
        (".روليت", "روليت روسي: يقصّون بعض لين يبقى ناجي وحد (فيه زر انسحاب)."),
        (".xo @خصمك", "اكس أو بينك وبين خصم تحدده."),
        (".مافيا", "مافيا مبسّطة: تصويت جولة وحدة تحدد الفايز."),
        (".كراسي", "الكراسي الموسيقية بالأزرار."),
        (".حجرة @خصمك", "حجرة ورقة مقص بينك وبين خصم."),
        (".نرد", "كل واحد يرمي نرد، الأعلى يفوز."),
        (".عجلة", "عجلة حظ تختار فايز عشوائي."),
        (".غميضة", "وحد يبحث عن الباقين المختبئين بأزرار مرقّمة."),
        (".ريبلكا", "احفظوا ترتيب الرموز واكتبوه صح."),
        (".خمن [أقصى رقم]", "تخمين رقم سري بالشات."),
        (".كلمة", "قول كلمة تبدأ بآخر حرف من الكلمة المعطاة."),
        (".زر", "أزرار تقل كل جولة (5 ثم 4 ثم 3...) واللي ما يلحق زر يطيح لين يبقى ناجي وحد."),
    ],
    "فردية": [
        (".اسرع", "أعد كتابة الجملة بأسرع وقت."),
        (".فكك", "فكك الكلمة حرف حرف (بكره ← ب ك ر ه)."),
        (".رتب", "رتب حروف الكلمة المبعثرة."),
        (".ادمج", "خمن الكلمة من دمج رمزين."),
        (".اعلام", "خمن الدولة من علمها (تختار المستوى بالأزرار: سهل / متوسط / صعب / صعب جدًا)."),
        (".اعكس", "اكتب الكلمة بالعكس."),
        (".حرف", "كلمة ناقصها حرف، خمن الحرف الناقص."),
        (".صحح", "صحح الكلمة المكتوبة غلط."),
        (".ترتيب", "رتب الأرقام تصاعديًا."),
        (".الوان", "أسئلة خلط ألوان ومعلومات عن الألوان."),
        (".ايموجي", "خمن الفيلم/الشخصية/القصة من رموز مركبة."),
        (".اكشف", "لعبة الذاكرة، طابق البطاقات."),
    ],
}

GAME_HELP = {
    "روليت": "الكل ينضم باللوبي (زر دخول)، وبعدها اللاعب المختار يطلع وحد من اللعبة كل دور (عنده 15 ثانية، ولو ما اختار أحد يطلع هو من اللعبة)، لين يبقى ناجي وحد وياخذ النقاط. فيه زر طرد عشوائي، وزر انسحاب يقدر أي لاعب باقي يطلع فيه نفسه من اللعبة.",
    "xo": "اكس أو كلاسيكية بينك وبين عضو تحدده بالمنشن، أول وحد يكمل خط يفوز. اللي دوره وما لعب خلال 15 ثانية يخسر.",
    "مافيا": "ينضم اللاعبين، يتوزعون أدوار مافيا/مواطنين بزر خفي يبان لهم بس (والمافيا يعرفون بعض)، تناقشون شوي وتصوتون بالأزرار على اللي تشكون فيه، ومين يطلع أكثر أصوات يتم كشفه.",
    "كراسي": "كل جولة عدد الكراسي أقل من عدد اللاعبين بواحد، اضغطوا الأزرار بسرعة، اللي ما يحصل كرسي يطيح.",
    "حجرة": "حجرة ورقة مقص بينك وبين خصم، كل واحد يختار بالخفاء (عندكم 15 ثانية، واللي ما اختار يخسر) والنتيجة تبان بعد اختيار الاثنين.",
    "نرد": "بعد اللوبي كل لاعب يضغط زر الرمي ويرمي النرد بنفسه (عندكم 10 ثواني)، ومن ما رمى يرمي له البوت تلقائيًا، وصاحب أعلى رقم يفوز بالنقاط.",
    "عجلة": "بعد ما يكتمل اللوبي، العجلة تدور وتختار فايز عشوائي من المنضمين.",
    "غميضة": "لاعب وحد يصير الباحث، والباقين يختبئون بين مجموعة أماكن (بعضها فاضي كفخ)، والباحث عنده عدد محاولات محدود يحاول يلقاهم فيه.",
    "ريبلكا": "تشوفون ترتيب رموز لمدة 5 ثواني، وبعدها لازم تكتبونه بنفس الترتيب بالضبط، أول وحد يجاوب صح يفوز.",
    "خمن": "البوت يختار رقم سري بين 1 والرقم اللي تحدده، واكتبوا تخمينكم بالشات وبيعطيكم تلميح فوق/تحت.",
    "كلمة": "يعطيكم البوت كلمة، وأول وحد يكتب كلمة تبدأ بآخر حرف منها يفوز بالنقاط.",
    "زر": "ينضم اللاعبين باللوبي. كل جولة تطلع أزرار أقل من عدد اللاعبين (5 بالجولة الأولى، ثم 4، ثم 3...)، لما تصير خضراء اضغطوا زر بسرعة (زر واحد لكل لاعب)، واللي ما يلحق زر يطيح، لين يبقى ناجي وحد ويفوز. لو اللاعبين أقل من 6 تكون الأزرار أقل من عددهم بواحد.",
    "اسرع": "البوت يعطي جملة، وأول وحد يعيد كتابتها بالضبط يفوز.",
    "فكك": "البوت يعطي كلمة، وأول وحد يكتبها حرف حرف وبين كل حرف مسافة يفوز. مثال: بكره ← ب ك ر ه",
    "رتب": "البوت يبعثر حروف كلمة، وأول وحد يرتبها صح يفوز.",
    "ادمج": "رمزين مع بعض يمثلون كلمة، خمنوا الكلمة اللي يدل عليها الدمج.",
    "اعلام": "أول ما تكتب الأمر يطلع لك أزرار المستويات (سهل / متوسط / صعب / صعب جدًا) وتختار اللي يناسب خبرتك، بعدها البوت يعرض علم دولة من المستوى اللي اخترته، وأول وحد يكتب اسم الدولة صح يفوز. كل ما صعب المستوى كبرت النقاط.",
    "اعكس": "البوت يعطي كلمة، واكتبوها بالعكس (آخر حرف أول حرف).",
    "حرف": "البوت يكتب كلمة ناقصها حرف (مثال: د ك ＿ ن)، وأول وحد يكتب الحرف الناقص يفوز (بالمثال الحرف: ا لأن الكلمة دكان). تقدر تكتب الحرف بس أو الكلمة كاملة.",
    "صحح": "البوت يكتب كلمة غلط إملائيًا، وأول وحد يصححها صح يفوز.",
    "ترتيب": "البوت يعطي 6 أرقام مبعثرة، رتبوها تصاعديًا وافصلوا بينها بمسافة.",
    "الوان": "البوت يسأل سؤال عن الألوان (خلط ألوان، لون شي معروف، ألوان مكمّلة...)، وأول وحد يجاوب صح يفوز.",
    "ايموجي": "البوت يعرض رموز مركبة (وتحتها التصنيف: فيلم / شخصية / قصة / مكان...)، وأول وحد يخمن المقصود يفوز.",
    "اكشف": "لعبة ذاكرة فردية، دور بطاقتين متطابقتين من شبكة 16 بطاقة بأقل عدد محاولات ممكن.",
}


@commands.command(name="العاب")
async def games_list_cmd(ctx: commands.Context):
    lines = ["**مركز الألعاب**\n", "__ألعاب جماعية (تبدأ بلوبي 30 ثانية)__"]
    for cmd, desc in GAME_LIST["جماعية"]:
        lines.append(f"`{cmd}`")
    lines.append("\n__ألعاب فردية__")
    for cmd, desc in GAME_LIST["فردية"]:
        lines.append(f"`{cmd}`")
    lines.append("\nاكتب `.نقاطي` عشان تشوف رصيدك.")
    lines.append("اكتب `.شرح اسم_اللعبة` (بدون النقطة داخل الاسم) عشان أشرحلك أي لعبة بالتفصيل.")
    lines.append("اكتب `.اوامر` عشان تشوف باقي الأوامر.")
    await ctx.send("\n".join(lines))


@commands.command(name="شرح")
async def explain_cmd(ctx: commands.Context, *, game_name: str = None):
    if not game_name:
        await ctx.send("اكتب: `.شرح اسم اللعبة` — مثال: `.شرح روليت`")
        return
    key = game_name.strip()
    if key not in GAME_HELP:
        await ctx.send("ما لقيت هذي اللعبة بالاسم ذا، اكتب `.العاب` عشان تشوف القائمة والأسماء الصحيحة.")
        return
    await ctx.send(f"**{key}**:\n{GAME_HELP[key]}")


# ---------- قفل تشغيل الألعاب: بس اللي معه رول الألعاب ----------
GAME_COMMAND_NAMES = {
    # جماعية
    "روليت", "xo", "مافيا", "كراسي", "حجرة", "نرد", "عجلة",
    "غميضة", "ريبلكا", "خمن", "كلمة",
    # فردية
    "زر", "اسرع", "فكك", "رتب", "ادمج", "اعلام", "اعكس", "حرف",
    "صحح", "ترتيب", "الوان", "ايموجي", "اكشف",
    # قائمة الألعاب
    "العاب",
}


class GamesRoleRequired(commands.CheckFailure):
    pass


async def games_role_check(ctx: commands.Context) -> bool:
    """يمنع أي أمر لعبة (و .العاب) إلا لو صاحبه معه رول الألعاب. باقي الأوامر (شرح...) مفتوحة للكل."""
    if ctx.command is None or ctx.command.name not in GAME_COMMAND_NAMES:
        return True
    if isinstance(ctx.author, discord.Member) and any(r.name == GAMES_ROLE_NAME for r in ctx.author.roles):
        return True
    raise GamesRoleRequired()


# ============================================================
# معالج الرسائل (تخمين الرقم + الجولات العامة) — يشتغل كـ listener
# ============================================================
async def games_on_message(message: discord.Message):
    if message.author.bot:
        return

    # لعبة خمن/تخمين (مفتوحة بالروم، بدون بريفكس بالرد — فيها تلميح فوق/تحت)
    game = active_guess_games.get(message.channel.id)
    if game and message.content.strip().lstrip("-").isdigit():
        guess = int(message.content.strip())
        if guess == game["number"]:
            reward = random.randint(50, 150)
            actual = add_game_reward(message.guild.id, message.author.id, reward)
            record_game_result(message.guild.id, message.author.id, won=True)
            capped = " (وصلت السقف اليومي)" if actual < reward else ""
            await message.channel.send(
                f"{message.author.mention} عرف الرقم **{game['number']}**! (+{actual} نقطة{capped})")
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
                actual = add_game_reward(message.guild.id, message.author.id, pts)
                record_game_result(message.guild.id, message.author.id, won=True)
                reveal = round_info.get("reveal", "")
                extra = f" الإجابة: **{reveal}**" if reveal else ""
                capped = " (وصلت السقف اليومي)" if actual < pts else ""
                await message.channel.send(f"{message.author.mention} جاوب صح!{extra} (+{actual} نقطة{capped})")
                await _remove_round_button(round_info.get("msg"))


# ============================================================
# الربط مع بوت الكنترول
# ============================================================
async def handle_games_role_error(ctx: commands.Context) -> None:
    """رسالة "ما عندك الصلاحية" لما أحد بدون رول الألعاب يجرب أمر لعبة."""
    if ctx.guild and discord.utils.get(ctx.guild.roles, name=GAMES_ROLE_NAME) is None:
        print(f"[تنبيه] رول الألعاب '{GAMES_ROLE_NAME}' مو موجود بالسيرفر — تأكد إن الاسم يطابق.")
    await ctx.send(f"{ctx.author.mention} ما عندك الصلاحية.")


def setup_games(b: commands.Bot) -> None:
    """يسجل أوامر الألعاب + الـlisteners + قفل الرول. لو اسم أمر مكرر يتخطاه ويطبع تنبيه (ما يطيّح البوت)."""
    global bot
    bot = b
    added = 0
    for obj in list(globals().values()):
        if isinstance(obj, commands.Command):
            try:
                b.add_command(obj)
                added += 1
            except commands.CommandRegistrationError as e:
                print(f"[ألعاب] ⚠️ تخطيت أمر مكرر: {e}")
    b.add_check(games_role_check)  # يقفل أوامر الألعاب برول Event Team (باقي الأوامر يمرّها)
    b.add_listener(games_on_message, "on_message")
    b.add_listener(on_raw_message_delete, "on_raw_message_delete")
    print(f"[ألعاب] ✅ تم تحميل مركز الألعاب ({added} أمر)")
