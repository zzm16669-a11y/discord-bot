"""
leaderboard.py — لوحة متصدرين بصورة (الكتابي على اليسار والصوتي على اليمين)
مرسومة فوق تصميمك، وتقرأ من جداول levels.py.

ما يعدّل على أي ملف عندك. الربط: جنب سطري levels بـ bot.py ضيف:

    import leaderboard
    leaderboard.setup_leaderboard(bot)

الملفات المطلوبة بنفس مجلد bot.py:
  - leaderboard_bg.png  (صورة التصميم اللي رفعتها، غيّر اسمها لهذا الاسم)
  - خط يدعم العربي: يشتغل مع DejaVuSans-Bold.ttf و DejaVuSans.ttf (مرفقين)،
    ولو حطيت Cairo-Bold.ttf / Cairo-Regular.ttf يستخدمها أول (شكلها أحلى).
  - للنص العربي: ضيف arabic-reshaper و python-bidi في requirements.txt
    (لو Pillow عندك مبني مع raqm ما تحتاجهم، بس ما يضرون).

الأمر: .متصدرين
  - أول 5 بالكتابي + أول 5 بالصوتي.
  - الصف الأخير (التاج) يعرض ترتيبك أنت.
  - لو أقل من 5 أشخاص، الخانات الفاضية تبقى بشكل التصميم الأصلي.
"""
import asyncio
import io
import os
import re
import time
import unicodedata

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, features

# ================= إعدادات =================
TEMPLATE_PATH = "leaderboard_bg.png"
COMMAND_COOLDOWN_SECONDS = 10     # كولداون لكل سيرفر (الرسم ياخذ ثواني)

FONT_BOLD_CANDIDATES = ["Cairo-Bold.ttf", "Tajawal-Bold.ttf", "IBMPlexSansArabic-Bold.ttf",
                        "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONT_REG_CANDIDATES = ["Cairo-Regular.ttf", "Tajawal-Regular.ttf", "IBMPlexSansArabic-Regular.ttf",
                       "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

# ---- إحداثيات التصميم (مقاسة من صورتك 1759×894 — لا تغيّرها إلا لو غيرت التصميم) ----
ROW_CENTERS = [353, 431.5, 510.5, 590.5, 669.5]   # مراكز الصفوف الخمسة (y)
CROWN_CENTER = 771                                # مركز صف التاج (y)
PANELS = {
    "chat":  {"avatar_cx": 129.5, "name_x": 172,  "value_right": 822},
    "voice": {"avatar_cx": 962.0, "name_x": 1005, "value_right": 1659},
}
AVATAR_SIZE = 48          # القطر الكلي (مع الإطار)
RING_WIDTH = 3
RING_COLORS = [(176, 50, 62), (150, 152, 170), (140, 72, 72), (72, 72, 90), (72, 72, 90)]

COLOR_NAME = (238, 238, 244)
COLOR_USER = (128, 131, 148)
COLOR_LABEL = (150, 153, 168)     # LVL / XP / -
COLOR_VALUE = (238, 238, 244)
COLOR_CROWN = (222, 72, 82)

NAME_SIZE, USER_SIZE, VALUE_SIZE = 23, 18, 20


# ============================================================
# نصوص وخطوط
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))
_RAQM = features.check("raqm")
_font_cache: dict = {}


def _load_font(candidates: list[str], size: int):
    key = (tuple(candidates), size)
    if key in _font_cache:
        return _font_cache[key]
    font = None
    for c in candidates:
        for base in (os.getcwd(), _HERE):
            path = os.path.join(base, c)
            if os.path.isfile(path):
                try:
                    font = ImageFont.truetype(path, size)
                    break
                except OSError:
                    continue
        if font:
            break
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _shape(text: str) -> str:
    """يجهّز النص العربي للرسم (وصل الحروف + اتجاه). لو raqm متوفر يسويها Pillow بنفسه."""
    if _RAQM:
        return text
    try:
        import arabic_reshaper
        try:
            from bidi import get_display
        except ImportError:
            from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE00-\uFE0F\u200D\u20E3\U000E0000-\U000E007F]")


def _clean(text: str) -> str:
    """يشيل الإيموجي والرموز اللي الخط ما يدعمها، ويحوّل الخطوط المزخرفة لحروف عادية."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _EMOJI_RE.sub("", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return re.sub(r"\s+", " ", text).strip()


def _width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(_shape(text), font=font)


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    if _width(draw, text, font) <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        candidate = text.rstrip() + "…"
        if _width(draw, candidate, font) <= max_w:
            return candidate
    return text


def _draw_text(draw, x: float, baseline: float, text: str, font, fill, anchor: str = "ls") -> None:
    draw.text((x, baseline), _shape(text), font=font, fill=fill, anchor=anchor)


def _cap_height(font) -> float:
    box = font.getbbox("H", anchor="ls")
    return -box[1]


# ============================================================
# الأفتار الدائري
# ============================================================
def _make_badge(avatar_bytes: bytes | None, ring_color: tuple, fallback_font) -> Image.Image:
    S = 4
    big = AVATAR_SIZE * S
    ring = RING_WIDTH * S
    inner = big - 2 * ring
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(out).ellipse((0, 0, big - 1, big - 1), fill=ring_color + (255,))

    av = None
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((inner, inner), Image.LANCZOS)
        except Exception:
            av = None
    if av is None:
        av = Image.new("RGBA", (inner, inner), (44, 44, 58, 255))
        d = ImageDraw.Draw(av)
        d.text((inner / 2, inner / 2), "?", font=_load_font(FONT_BOLD_CANDIDATES, inner // 2),
               fill=(150, 153, 168), anchor="mm")

    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    out.paste(av, (ring, ring), mask)
    return out.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)


# ============================================================
# رسم الصفوف
# ============================================================
def _erase_placeholder(img: Image.Image, base: Image.Image, panel: dict, cy: float) -> None:
    """يمسح نص "LVL - XP" الأصلي بنسخ شريط نظيف من نفس الصف (الخلفية موحدة تقريبًا)."""
    x0 = int(panel["value_right"] - 104)
    x1 = int(panel["value_right"] + 10)
    y0, y1 = int(cy - 14), int(cy + 15)
    strip = base.crop((x0 - 170, y0, x1 - 170, y1))
    img.paste(strip, (x0, y0))


def _draw_values(draw, panel: dict, cy: float, level: int, xp: int) -> float:
    """يرسم "LVL 12 - 3,450 XP" محاذي لليمين، ويرجع بداية النص (x) عشان نعرف وين نقطع الاسم."""
    font = _load_font(FONT_BOLD_CANDIDATES, VALUE_SIZE)
    segments = [("LVL", COLOR_LABEL), (str(level), COLOR_VALUE), ("-", COLOR_LABEL),
                (f"{xp:,}", COLOR_VALUE), ("XP", COLOR_LABEL)]
    gap = 9
    total = sum(_width(draw, t, font) for t, _ in segments) + gap * (len(segments) - 1)
    x = panel["value_right"] - total
    baseline = cy + _cap_height(font) / 2
    start = x
    for text, color in segments:
        _draw_text(draw, x, baseline, text, font, color)
        x += _width(draw, text, font) + gap
    return start


def _draw_name(draw, panel: dict, cy: float, name: str, username: str, max_x: float,
               prefix: str | None = None) -> None:
    name_font = _load_font(FONT_BOLD_CANDIDATES, NAME_SIZE)
    user_font = _load_font(FONT_REG_CANDIDATES, USER_SIZE)
    x = panel["name_x"]
    baseline = cy + _cap_height(name_font) / 2

    if prefix:
        _draw_text(draw, x, baseline, prefix, name_font, COLOR_CROWN)
        x += _width(draw, prefix, name_font) + 14

    avail = max_x - x
    name = _clean(name)
    username = _clean(username)
    if not name:
        name, username = username, ""
    if username and username.lower() == name.lower():
        username = ""

    user_txt = ""
    user_w = 0.0
    gap = 8
    if username:
        user_txt = _fit(draw, f"({username})", user_font, avail * 0.42)
        user_w = _width(draw, user_txt, user_font) + gap
    name_txt = _fit(draw, name, name_font, avail - user_w)
    _draw_text(draw, x, baseline, name_txt, name_font, COLOR_NAME)
    if user_txt:
        ux = x + _width(draw, name_txt, name_font) + gap
        _draw_text(draw, ux, baseline, user_txt, user_font, COLOR_USER)


_template_cache: dict[str, Image.Image] = {}


def _load_template(path: str) -> Image.Image:
    if path not in _template_cache:
        for candidate in (path, os.path.join(_HERE, path)):
            if os.path.isfile(candidate):
                _template_cache[path] = Image.open(candidate).convert("RGB")
                break
        else:
            raise FileNotFoundError(path)
    return _template_cache[path]


def render_leaderboard(chat_rows: list[dict], voice_rows: list[dict],
                       chat_me: dict | None, voice_me: dict | None,
                       template_path: str = TEMPLATE_PATH) -> bytes:
    """يرسم الصورة ويرجعها PNG bytes.
    كل صف: {name, username, avatar (bytes|None), level, xp}، وصف التاج يزيد عليه {rank}."""
    base = _load_template(template_path)
    img = base.copy()
    draw = ImageDraw.Draw(img)
    name_font = _load_font(FONT_BOLD_CANDIDATES, NAME_SIZE)

    jobs = []   # (panel, cy, row, ring_color|None, prefix)
    for key, rows, me in (("chat", chat_rows, chat_me), ("voice", voice_rows, voice_me)):
        panel = PANELS[key]
        for i, row in enumerate(rows[:5]):
            jobs.append((panel, ROW_CENTERS[i], row, RING_COLORS[i], None))
        if me is not None:
            prefix = f"#{me['rank']}" if me.get("rank") else "—"
            jobs.append((panel, CROWN_CENTER, me, None, prefix))

    # 1) نمسح كل النصوص الأصلية أول (قبل ما نرسم أي شي، عشان الشريط المنسوخ يكون نظيف)
    for panel, cy, *_ in jobs:
        _erase_placeholder(img, base, panel, cy)

    # 2) نرسم الأفتار والأسماء والأرقام
    for panel, cy, row, ring_color, prefix in jobs:
        if ring_color is not None:
            badge = _make_badge(row.get("avatar"), ring_color, name_font)
            img.paste(badge, (int(round(panel["avatar_cx"] - AVATAR_SIZE / 2)),
                              int(round(cy - AVATAR_SIZE / 2))), badge)
        values_x = _draw_values(draw, panel, cy, row["level"], row["xp"])
        _draw_name(draw, panel, cy, row.get("name", ""), row.get("username", ""),
                   max_x=values_x - 26, prefix=prefix)

    buf = io.BytesIO()
    # ملاحظة: optimize=True كان يبطّئ الحفظ جدًا (6+ ثواني على جهاز سريع)، compress_level=1 ياخذ أقل من ثانية
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


# ============================================================
# جلب البيانات من ديسكورد + الأمر
# ============================================================
_avatar_cache: dict = {}   # (user_id, avatar_key) -> bytes


async def _avatar_bytes(user) -> bytes | None:
    key = (user.id, getattr(user.display_avatar, "key", None))
    if key in _avatar_cache:
        return _avatar_cache[key]
    try:
        data = await user.display_avatar.replace(size=128, format="png").read()
    except Exception:
        return None
    if len(_avatar_cache) > 300:
        _avatar_cache.clear()
    _avatar_cache[key] = data
    return data


async def _make_row(bot: commands.Bot, guild: discord.Guild, uid: int, xp: int, level: int) -> dict:
    user = guild.get_member(uid)
    if user is None:
        try:
            user = await bot.fetch_user(uid)
        except Exception:
            user = None
    if user is None:
        return {"name": "عضو غادر", "username": "", "avatar": None, "level": level, "xp": xp}
    return {
        "name": getattr(user, "display_name", None) or user.name,
        "username": user.name,
        "avatar": await _avatar_bytes(user),
        "level": level, "xp": xp,
    }


_last_use: dict[int, float] = {}
_render_cache: dict = {}   # (guild_id, user_id) -> (signature, png_bytes, time)
RENDER_CACHE_SECONDS = 120


def _signature(chat_rows, voice_rows, chat_me, voice_me) -> tuple:
    def r(row):
        return (row.get("name"), row.get("username"), row.get("level"), row.get("xp"),
                row.get("rank"), hash(row.get("avatar")))
    return (tuple(map(r, chat_rows)), tuple(map(r, voice_rows)), r(chat_me), r(voice_me))


def setup_leaderboard(bot: commands.Bot) -> None:
    @bot.command(name="متصدرين")
    async def leaderboard_cmd(ctx: commands.Context):
        import levels   # نستورده هنا عشان نتأكد إن levels.py موجود ومربوط

        if ctx.guild is None:
            return
        if not os.path.isfile(TEMPLATE_PATH) and not os.path.isfile(os.path.join(_HERE, TEMPLATE_PATH)):
            await ctx.send(f"⚠️ ما لقيت صورة التصميم `{TEMPLATE_PATH}` بجنب ملف البوت.")
            return
        now = time.monotonic()
        if now - _last_use.get(ctx.guild.id, 0) < COMMAND_COOLDOWN_SECONDS:
            await ctx.send("⏳ انتظر شوي وجرب مرة ثانية.", delete_after=5)
            return
        _last_use[ctx.guild.id] = now

        status = await ctx.send("⏳ جاري تجهيز الصورة...")
        async with ctx.typing():
            gid = ctx.guild.id
            chat_top = levels._get_top(levels.CHAT_TABLE, gid, 5)
            voice_top = levels._get_top(levels.VOICE_TABLE, gid, 5)

            async def me_row(table: str) -> dict:
                xp, _ = levels._get_row(table, gid, ctx.author.id)
                level, _, _ = levels.level_from_xp(xp)
                row = await _make_row(bot, ctx.guild, ctx.author.id, xp, level)
                row["rank"] = levels._get_rank(table, gid, xp) if xp > 0 else None
                return row

            chat_rows, voice_rows, chat_me, voice_me = await asyncio.gather(
                asyncio.gather(*(_make_row(bot, ctx.guild, u, xp, lv) for u, xp, lv in chat_top)),
                asyncio.gather(*(_make_row(bot, ctx.guild, u, xp, lv) for u, xp, lv in voice_top)),
                me_row(levels.CHAT_TABLE),
                me_row(levels.VOICE_TABLE),
            )
            sig = _signature(chat_rows, voice_rows, chat_me, voice_me)
            cached = _render_cache.get((gid, ctx.author.id))
            if cached and cached[0] == sig and time.monotonic() - cached[2] < RENDER_CACHE_SECONDS:
                png = cached[1]
            else:
                try:
                    png = await asyncio.to_thread(
                        render_leaderboard, list(chat_rows), list(voice_rows), chat_me, voice_me)
                except Exception as e:
                    print(f"[Leaderboard] فشل رسم الصورة: {e}")
                    await status.edit(content="❌ ما قدرت أرسم الصورة، راجع الكونسول.")
                    return
                _render_cache[(gid, ctx.author.id)] = (sig, png, time.monotonic())
        await ctx.send(file=discord.File(io.BytesIO(png), filename="leaderboard.png"))
        try:
            await status.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
