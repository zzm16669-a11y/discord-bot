"""
levels.py — نظام لفلات مستقل: كتابي (رسائل) + صوتي (وقت بالرومات الصوتية).

- اللفل الكتابي يعطي رتب تلقائية، واللفل الصوتي بدون رتب (بس رسالة ترقية).
- ما يعدّل على db.py ولا bot.py ولا tickets.py: يستخدم اتصال SQLite خاص فيه
  (بنفس ملف bot_data.db) وينشئ جدولين لحالهم: levels و voice_levels.

طريقة الربط ببوتك (بعد سطري التكتات):

    import levels
    levels.setup_levels(bot)

الأوامر:
  .لفل [@عضو]        — لفلك الكتابي والصوتي مع الـ XP والترتيب
  .لفلات             — أعلى 10 باللفل الكتابي (alias: .توب_لفل)
  .لفلات صوت         — أعلى 10 باللفل الصوتي
"""
import random
import re
import sqlite3
import threading
import time

import discord
from discord.ext import commands, tasks

# ================= إعدادات (غيّرها هنا لو تبي) =================
DB_PATH = "bot_data.db"

# ---- الكتابي ----
XP_MIN, XP_MAX = 15, 25          # XP عشوائي لكل رسالة
XP_COOLDOWN_SECONDS = 60         # كم ثانية بين رسالة تعطي XP والثانية
MIN_MESSAGE_LENGTH = 3           # رسائل أقصر من كذا ما تعطي XP

# ---- الصوتي ----
VOICE_XP_MIN, VOICE_XP_MAX = 8, 12   # XP لكل دقيقة بالروم الصوتي
VOICE_MIN_HUMANS = 2                 # لازم يكون بالروم شخصين حقيقيين على الأقل (يمنع تكديس XP وحدك)

# رتب اللفلات (للكتابي بس): {اللفل: "اسم الرتبة"}
LEVEL_ROLES = {
    1: "🌑 1+ level .",
    3: "🌘 3+ level .",
    5: "🌔 5+ level .",
    7: "🌖 7+ level .",
    10: "🌗 10+ level .",
    20: "🌓 20+ level .",
    30: "🪐 30+ level .",
    50: "𓈉 🌕 50+ level .",
}
KEEP_ALL_LEVEL_ROLES = False     # False = يشيل الرتبة القديمة ويحط الجديدة، True = يحتفظ بكل الرتب
AUTO_CREATE_LEVEL_ROLES = False  # True = ينشئ الرتبة تلقائيًا لو ما لقاها

# رسالة الترقية
LEVEL_UP_CHANNEL_NAME = "level"  # اسم روم الترقيات
LEVEL_UP_TEXT = "┃ مبروك {mention}، ارتقيت إلى المستوى {level} ! استمر في نشاطك. {tag}"
CHAT_TAG = "💬 (كتابي)"
VOICE_TAG = "🎙️ (صوتي)"

NO_XP_CHANNEL_NAMES = []         # أسماء رومات (كتابية/صوتية) ما تعطي XP
NO_XP_ROLE_NAMES = []            # أسماء رتب ما تكسب XP

CHAT_TABLE = "levels"
VOICE_TABLE = "voice_levels"


# ============================================================
# قاعدة البيانات (اتصال خاص، ما يلمس db.py)
# ============================================================
_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
_conn.execute("PRAGMA journal_mode=WAL")
_conn.row_factory = sqlite3.Row
for _t in (CHAT_TABLE, VOICE_TABLE):
    _conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_t} (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
_conn.commit()


def _get_row(table: str, guild_id: int, user_id: int) -> tuple[int, int]:
    with _lock:
        row = _conn.execute(
            f"SELECT xp, level FROM {table} WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id))).fetchone()
    return (row["xp"], row["level"]) if row else (0, 0)


def _save_row(table: str, guild_id: int, user_id: int, xp: int, level: int) -> None:
    with _lock:
        _conn.execute(
            f"INSERT INTO {table} (guild_id, user_id, xp, level) VALUES (?,?,?,?) "
            f"ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp, level=excluded.level",
            (str(guild_id), str(user_id), xp, level))
        _conn.commit()


def _get_rank(table: str, guild_id: int, xp: int) -> int:
    with _lock:
        row = _conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE guild_id=? AND xp > ?",
            (str(guild_id), xp)).fetchone()
    return row["c"] + 1


def _get_top(table: str, guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
    with _lock:
        rows = _conn.execute(
            f"SELECT user_id, xp, level FROM {table} WHERE guild_id=? AND xp > 0 "
            f"ORDER BY xp DESC LIMIT ?", (str(guild_id), limit)).fetchall()
    return [(int(r["user_id"]), r["xp"], r["level"]) for r in rows]


# ============================================================
# معادلة اللفلات (شبيهة بـ MEE6)
# ============================================================
def xp_needed(level: int) -> int:
    """كم XP تحتاج عشان تنتقل من هذا اللفل للي بعده."""
    return 5 * level * level + 50 * level + 100


def level_from_xp(total_xp: int) -> tuple[int, int, int]:
    """يرجع (اللفل، XP داخل اللفل الحالي، XP المطلوب للفل اللي بعده)."""
    level = 0
    remaining = total_xp
    while remaining >= xp_needed(level):
        remaining -= xp_needed(level)
        level += 1
    return level, remaining, xp_needed(level)


def _add_xp(table: str, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
    """يضيف XP ويرجع (اللفل القديم، اللفل الجديد)."""
    xp, old_level = _get_row(table, guild_id, user_id)
    xp += amount
    new_level, _, _ = level_from_xp(xp)
    _save_row(table, guild_id, user_id, xp, new_level)
    return old_level, new_level


# ============================================================
# رسالة الترقية
# ============================================================
def _find_level_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if not LEVEL_UP_CHANNEL_NAME:
        return None
    target = LEVEL_UP_CHANNEL_NAME.lower()
    for ch in guild.text_channels:
        if ch.name.lower() == target:
            return ch
    for ch in guild.text_channels:   # لو اسم الروم فيه زخرفة/إيموجي
        if target in ch.name.lower().replace("_", "-"):
            return ch
    return None


async def _announce_level_up(member: discord.Member, level: int, tag: str,
                              fallback: discord.abc.Messageable | None = None) -> None:
    channel = _find_level_channel(member.guild) or fallback
    if channel is None:
        return
    try:
        await channel.send(LEVEL_UP_TEXT.format(mention=member.mention, level=level, tag=tag))
    except (discord.Forbidden, discord.HTTPException):
        pass


# ============================================================
# رتب اللفلات (الكتابي بس)
# ============================================================
def _find_level_role(guild: discord.Guild, level: int, name: str) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name=name)
    if role is not None:
        return role
    # احتياط: لو الاسم فيه فرق بسيط (مسافات/رموز) نطابق بالرقم، مثال "10+ level"
    pattern = re.compile(rf"(?<!\d){level}\+\s*level", re.IGNORECASE)
    for r in guild.roles:
        if pattern.search(r.name):
            return r
    return None


async def _get_or_create_role(guild: discord.Guild, level: int, name: str) -> discord.Role | None:
    role = _find_level_role(guild, level, name)
    if role is None and AUTO_CREATE_LEVEL_ROLES:
        try:
            role = await guild.create_role(name=name, reason="رتبة لفل - إنشاء تلقائي")
        except (discord.Forbidden, discord.HTTPException):
            role = None
    if role is None:
        print(f"[Levels] ما لقيت رتبة '{name}' بالسيرفر.")
    return role


async def _sync_level_roles(member: discord.Member, level: int) -> None:
    eligible = sorted(l for l in LEVEL_ROLES if l <= level)
    if not eligible:
        return
    guild = member.guild
    try:
        if KEEP_ALL_LEVEL_ROLES:
            to_add = []
            for l in eligible:
                role = await _get_or_create_role(guild, l, LEVEL_ROLES[l])
                if role and role not in member.roles:
                    to_add.append(role)
            if to_add:
                await member.add_roles(*to_add, reason=f"ترقية للفل {level}")
            return

        target_level = eligible[-1]
        target = await _get_or_create_role(guild, target_level, LEVEL_ROLES[target_level])
        if target is None:
            return
        to_remove = []
        for l, name in LEVEL_ROLES.items():
            if l == target_level:
                continue
            r = _find_level_role(guild, l, name)
            if r and r in member.roles:
                to_remove.append(r)
        if target not in member.roles:
            await member.add_roles(target, reason=f"ترقية للفل {level}")
        if to_remove:
            await member.remove_roles(*to_remove, reason=f"ترقية للفل {level}")
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"[Levels] فشل تحديث رتب {member}: {e} (تأكد إن رتبة البوت أعلى من رتب اللفلات)")


# ============================================================
# كسب الـ XP الكتابي
# ============================================================
_cooldowns: dict[tuple[int, int], float] = {}


def _member_excluded(member: discord.Member) -> bool:
    return bool(NO_XP_ROLE_NAMES) and any(r.name in NO_XP_ROLE_NAMES for r in member.roles)


async def _on_message_levels(message: discord.Message) -> None:
    if message.author.bot or message.guild is None:
        return
    if not isinstance(message.author, discord.Member):
        return
    content = message.content.strip()
    if content.startswith(".") or len(content) < MIN_MESSAGE_LENGTH:
        return
    if message.channel.name in NO_XP_CHANNEL_NAMES or _member_excluded(message.author):
        return

    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    if now - _cooldowns.get(key, 0) < XP_COOLDOWN_SECONDS:
        return
    _cooldowns[key] = now

    old_level, new_level = _add_xp(CHAT_TABLE, message.guild.id, message.author.id,
                                    random.randint(XP_MIN, XP_MAX))
    if new_level > old_level:
        await _announce_level_up(message.author, new_level, CHAT_TAG, fallback=message.channel)
        await _sync_level_roles(message.author, new_level)


# ============================================================
# الربط بالبوت
# ============================================================
def setup_levels(bot: commands.Bot) -> None:
    bot.add_listener(_on_message_levels, "on_message")

    # ---------- الصوتي: كل دقيقة نعطي XP للي بالرومات الصوتية ----------
    @tasks.loop(seconds=60)
    async def voice_xp_task():
        for guild in bot.guilds:
            afk_id = guild.afk_channel.id if guild.afk_channel else None
            for vc in guild.voice_channels:
                if vc.id == afk_id or vc.name in NO_XP_CHANNEL_NAMES:
                    continue
                humans = [m for m in vc.members if not m.bot]
                if len(humans) < VOICE_MIN_HUMANS:
                    continue
                for m in humans:
                    try:
                        if m.voice and (m.voice.self_deaf or m.voice.deaf):
                            continue
                        if _member_excluded(m):
                            continue
                        old_level, new_level = _add_xp(
                            VOICE_TABLE, guild.id, m.id, random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                        if new_level > old_level:
                            await _announce_level_up(m, new_level, VOICE_TAG)
                    except Exception as e:
                        print(f"[Levels] خطأ بالـXP الصوتي لـ {m}: {e}")

    async def _on_ready_levels():
        if not voice_xp_task.is_running():
            voice_xp_task.start()

    bot.add_listener(_on_ready_levels, "on_ready")

    # ---------- الأوامر ----------
    def _progress(into: int, needed: int) -> str:
        filled = int(into / needed * 10) if needed else 0
        return "█" * filled + "░" * (10 - filled)

    @bot.command(name="لفل")
    async def level_cmd(ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        lines = [f"📊 **لفلات {member.display_name}**"]
        for title, table in (("💬 الكتابي", CHAT_TABLE), ("🎙️ الصوتي", VOICE_TABLE)):
            xp, _ = _get_row(table, ctx.guild.id, member.id)
            level, into, needed = level_from_xp(xp)
            rank = f"#{_get_rank(table, ctx.guild.id, xp)}" if xp > 0 else "—"
            lines.append(
                f"\n**{title}**\n"
                f"🏅 اللفل: **{level}**\n"
                f"✨ XP: **{into}/{needed}** `{_progress(into, needed)}`\n"
                f"🏆 الترتيب: **{rank}**")
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())

    @bot.command(name="لفلات", aliases=["توب_لفل"])
    async def levels_top_cmd(ctx: commands.Context, kind: str = None):
        voice = kind is not None and kind.strip() in ("صوت", "صوتي", "voice")
        table = VOICE_TABLE if voice else CHAT_TABLE
        top = _get_top(table, ctx.guild.id, 10)
        if not top:
            await ctx.send("📉 ما فيه أحد كسب XP لين الحين.")
            return
        medals = ["🥇", "🥈", "🥉"]
        title = "🎙️ الصوتي" if voice else "💬 الكتابي"
        lines = [f"🏆 **توب 10 — أعلى اللفلات ({title})**\n"]
        for i, (uid, xp, level) in enumerate(top):
            member = ctx.guild.get_member(uid)
            name = member.mention if member else f"عضو غادر (`{uid}`)"
            rank = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{rank} {name} — لفل **{level}** ({xp} XP)")
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())
