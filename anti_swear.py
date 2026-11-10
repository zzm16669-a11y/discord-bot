"""
anti_swear.py
فلتر السب والقذف (الصريح والمشفّر) لبوت ديسكورد - discord.py 2.x

طريقة الاستخدام داخل ملف البوت الرئيسي:

    from anti_swear import AntiSwear
    await bot.add_cog(AntiSwear(bot))          # داخل setup_hook أو async main

أو:

    await bot.load_extension("anti_swear")      # داخل setup_hook

أو لو تبي تستخدم الفحص فقط داخل on_message حقك:

    from anti_swear import contains_swear
    if contains_swear(message.content):
        await message.delete()

مهم: لازم تفعّل Message Content Intent (في البوت وفي موقع المطورين)،
ولازم يكون للبوت صلاحية Manage Messages.
"""

import re
import unicodedata

import discord
from discord.ext import commands

# ============================================================
#                        الإعدادات
# ============================================================

# رتب تتفلت من الفلتر (حط ايديات الرتب)، مثال: {123456789012345678}
EXEMPT_ROLE_IDS: set[int] = set()

# رومات مستثناة من الفلتر (حط ايديات الرومات)
EXEMPT_CHANNEL_IDS: set[int] = set()

# روم اللوق: لو تبي البوت يسجّل الرسائل المحذوفة حط ايدي الروم، وإذا لا خله None
LOG_CHANNEL_ID: int | None = 1538326544832012318

# هل الأدمن (صلاحية Administrator) يتفلت من الفلتر؟
EXEMPT_ADMINISTRATORS: bool = True

# بعد كم ثانية تنحذف رسالة التنبيه
WARNING_DELETE_AFTER: int = 5

# نص التنبيه ({user} يتحول لمنشن العضو)
WARNING_TEXT: str = "{user} ⚠️ ممنوع السب والقذف في السيرفر."

# ============================================================
#                     قائمة الكلمات الأساسية
# ============================================================
# - اكتب الكلمات عادي (بدون تشكيل)، الكود ينظّفها بنفس طريقة تنظيف الرسائل.
# - الكلمات القصيرة (أقل من 5 حروف) تنمسك فقط إذا جت ككلمة كاملة أو متفرقة
#   (مثل: ك س م ك) عشان ما نحذف رسائل بريئة.
# - الكلمات الأطول تنمسك حتى لو انكتبت ملصوقة أو بينها رموز أو مسافات.
# - تقدر تزيد أو تحذف من القائمة بكيفك.

BAD_WORDS: list[str] = [
    # ----- عربي -----
    "كس", "كسمك", "كسامك", "كس امك", "كس اختك", "كسختك", "كسك",
    "زب", "زبي", "زبك",
    "طيز", "طيزك",
    "عرص", "عرصه", "عرصة",
    "شرموط", "شرموطه", "شرموطة",
    "قحبه", "قحبة", "عاهره", "عاهرة",
    "منيوك", "منيك", "متناك", "ناك", "نيك",
    "ابن الكلب", "ولد الكلب", "ابن الحرام", "ولد الحرام",
    "ابن الزانيه", "ولد الزنا", "ابن القحبه", "ابن العاهره",
    "يا خنزير", "يا حقير", "يا واطي",
    "يا زباله", "يا ساقط", "يا ديوث", "ديوث", "ياديوث",
    # ----- انجليزي -----
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "pussy", "cunt",
]

# ============================================================
#                      تنظيف وفحص النص
# ============================================================

_TATWEEL = "\u0640"

# توحيد الحروف العربية المتشابهة
_LETTER_MAP = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ی": "ي", "ئ": "ي",
    "ة": "ه",
    "ؤ": "و",
    "ء": "",
    "ک": "ك", "گ": "ك",
    "ڤ": "ف", "پ": "ب", "چ": "ج",
}

# الأرقام والرموز اللي يستخدمونها بدل الحروف
_LEET_MAP = {
    "3": "ع", "7": "ح", "5": "خ", "9": "ق", "6": "ط", "8": "غ",
    "@": "a", "$": "s", "0": "o", "1": "i",
}

_TRANSLATION = str.maketrans({**_LETTER_MAP, **_LEET_MAP})
_REPEAT_RE = re.compile(r"(.)\1+")
_NON_LETTER_RE = re.compile(r"[^a-z\u0621-\u064A]+")


def normalize(text: str) -> str:
    """ينظّف النص: يشيل التشكيل والتطويل والرموز الخفية، يوحّد الحروف،
    يحوّل الأرقام المموّهة لحروف، ويضغط الحروف المكررة. يرجّع النص بمسافات بين الكلمات."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(
        ch for ch in text
        if ch != _TATWEEL and unicodedata.category(ch) not in ("Mn", "Cf")
    )
    text = text.translate(_TRANSLATION)
    text = _NON_LETTER_RE.sub(" ", text)
    text = _REPEAT_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _merge_single_letters(tokens: list[str]) -> list[str]:
    """يلصق الحروف المتفرقة: ['ك','س','م','ك'] -> ['كسمك']"""
    merged: list[str] = []
    run: list[str] = []
    for tok in tokens:
        if len(tok) == 1:
            run.append(tok)
            continue
        if run:
            merged.append("".join(run))
            run = []
        merged.append(tok)
    if run:
        merged.append("".join(run))
    return merged


# تجهيز القوائم مرة وحدة عند تشغيل الملف
_SHORT_WORDS: set[str] = set()      # كلمات كاملة فقط
_SHORT_PHRASES: set[str] = set()    # عبارات من كذا كلمة (تنفحص بالمسافات)
_LONG_WORDS: set[str] = set()       # تنفحص كجزء من النص الملصوق

for _w in BAD_WORDS:
    _n = normalize(_w)
    if not _n:
        continue
    _compact = _n.replace(" ", "")
    if len(_compact) >= 5:
        _LONG_WORDS.add(_compact)
    elif " " in _n:
        _SHORT_PHRASES.add(_n)
    else:
        _SHORT_WORDS.add(_n)


def contains_swear(text: str) -> bool:
    """True إذا النص فيه سب أو قذف (صريح أو مشفّر)."""
    if not text:
        return False

    spaced = normalize(text)
    if not spaced:
        return False

    tokens = _merge_single_letters(spaced.split(" "))

    # 1) كلمات قصيرة: لازم تطابق كلمة كاملة
    if _SHORT_WORDS.intersection(tokens):
        return True

    # 2) عبارات قصيرة بالمسافات
    padded = f" {' '.join(tokens)} "
    for phrase in _SHORT_PHRASES:
        if f" {phrase} " in padded:
            return True

    # 3) كلمات طويلة: تنفحص في النص الملصوق (يمسك التفريق والرموز)
    compact = "".join(tokens)
    for word in _LONG_WORDS:
        if word in compact:
            return True

    return False


# ============================================================
#                          الكوج
# ============================================================

class AntiSwear(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_exempt(self, message: discord.Message) -> bool:
        if message.channel.id in EXEMPT_CHANNEL_IDS:
            return True
        author = message.author
        if isinstance(author, discord.Member):
            if EXEMPT_ADMINISTRATORS and author.guild_permissions.administrator:
                return True
            if EXEMPT_ROLE_IDS and any(r.id in EXEMPT_ROLE_IDS for r in author.roles):
                return True
        return False

    async def _log(self, message: discord.Message):
        if not LOG_CHANNEL_ID:
            return
        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel is None:
            return
        embed = discord.Embed(
            title="🚫 رسالة محذوفة (سب/قذف)",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="العضو", value=f"{message.author.mention} ({message.author.id})", inline=False)
        embed.add_field(name="الروم", value=message.channel.mention, inline=False)
        embed.add_field(name="الرسالة", value=(message.content[:1000] or "-"), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _handle(self, message: discord.Message):
        if message.author.bot or message.guild is None or not message.content:
            return
        if self._is_exempt(message):
            return
        if not contains_swear(message.content):
            return

        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            return

        try:
            await message.channel.send(
                WARNING_TEXT.format(user=message.author.mention),
                delete_after=WARNING_DELETE_AFTER,
            )
        except discord.HTTPException:
            pass

        await self._log(message)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._handle(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # يمسك اللي يعدّل رسالته بعد ما ترسل ويحط فيها سب
        if before.content != after.content:
            await self._handle(after)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiSwear(bot))
