"""
protection.py — نظام حماية للسيرفر (مستقل، ما يلمس أي ملف ثاني).

الميزات:
  1) منع السبام: رسائل كثيرة بوقت قصير → تنحذف + تايم أوت.
  2) منع روابط الدعوات: الرابط ينحذف + تنبيه للعضو.
  3) حماية من الريد: دخول أعداد كبيرة بوقت قصير → البوت يطرد (أو يكتم) الدفعة.
  4) حماية من التخريب (anti-nuke): حذف رومات/رتب أو حظر/طرد أعضاء بسرعة → تنسحب رتب الفاعل.
  5) منع إضافة البوتات: أي بوت يدخل يُطرد إلا لو اللي أضافه مالك السيرفر أو رتبة عليا.

المستثنون من كل شي: مالك السيرفر + الرتب بـ EXEMPT_ROLE_NAMES.
كل العقوبات تنسجل بروم security-logs (وإذا ما لقاه، mod-logs).

الربط ببوتك (جنب باقي الأنظمة):

    import protection
    protection.setup_protection(bot)

صلاحيات البوت اللازمة: Manage Messages، Moderate Members، Kick Members،
Manage Roles، View Audit Log — ورتبته لازم تكون أعلى من الرتب/الأعضاء اللي يتعامل معهم.
(الإعدادات كلها هنا بالكود، فما تضيع مع إعادة تشغيل البوت.)
"""
import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

# ================= إعدادات (غيّرها هنا لو تبي) =================
EXEMPT_ROLE_NAMES = ["Owner", "Co-Owner", "Vice Owner"]
LOG_CHANNEL_HINTS = ["security-logs", "mod-logs"]

# ---- 1) السبام ----
SPAM_ENABLED = True
SPAM_MESSAGES = 6                # عدد الرسائل
SPAM_SECONDS = 5                 # خلال كم ثانية
SPAM_TIMEOUT_MINUTES = 10
SPAM_IGNORED_CHANNELS = []       # أسماء رومات ما تنطبق عليها الحماية (مثال: ["games"])

# ---- 2) روابط الدعوات ----
INVITE_ENABLED = True
ALLOWED_INVITE_CODES = []        # أكواد دعوات مسموحة (مثال سيرفرك): ["abc123"]

# ---- 3) الريد ----
RAID_ENABLED = True
RAID_JOINS = 8                   # عدد الداخلين
RAID_SECONDS = 15                # خلال كم ثانية
RAID_LOCK_SECONDS = 120          # كم ثانية يستمر وضع الحماية (كل داخل جديد يتعاقب)
RAID_ACTION = "kick"             # "kick" = طرد، "timeout" = كتم ساعة

# ---- 4) التخريب (anti-nuke) ----
NUKE_ENABLED = True
NUKE_RULES = {
    "حذف رومات/رتب": ({discord.AuditLogAction.channel_delete, discord.AuditLogAction.role_delete}, 3, 30),
    "حظر/طرد أعضاء": ({discord.AuditLogAction.ban, discord.AuditLogAction.kick,
                        discord.AuditLogAction.member_prune}, 4, 30),
}   # {الاسم: (الأفعال، العدد المسموح قبل العقوبة، خلال كم ثانية)}

# ---- 5) البوتات ----
BOT_ADD_ENABLED = True
ALLOWED_BOT_IDS = []             # آيديات بوتات مسموحة دائمًا (مثال: بوت الموسيقى): [123456789012345678]


# ============================================================
# دوال مساعدة
# ============================================================
_bot_ref: commands.Bot | None = None
INVITE_PATTERN = re.compile(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)([a-zA-Z0-9-]+)", re.IGNORECASE)


def _is_exempt(member: discord.Member) -> bool:
    if member.id == member.guild.owner_id:
        return True
    return any(r.name in EXEMPT_ROLE_NAMES for r in member.roles)


def _find_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    for hint in LOG_CHANNEL_HINTS:
        for ch in guild.text_channels:
            if hint in ch.name.lower().replace("_", "-"):
                return ch
    return None


async def _log(guild: discord.Guild, title: str, color: discord.Color, fields: list[tuple[str, object]],
               ping_owner: bool = False) -> None:
    channel = _find_log_channel(guild)
    if channel is None:
        return
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    for name, value in fields:
        embed.add_field(name=name, value=str(value)[:1000] or "—", inline=False)
    try:
        await channel.send(content=(f"<@{guild.owner_id}>" if ping_owner else None), embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


# ============================================================
# 1) السبام
# ============================================================
_spam: dict[tuple[int, int], deque] = defaultdict(deque)


async def _handle_spam(message: discord.Message) -> None:
    if len(_spam) > 3000:
        _spam.clear()
    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    q = _spam[key]
    q.append((now, message))
    while q and now - q[0][0] > SPAM_SECONDS:
        q.popleft()
    if len(q) < SPAM_MESSAGES:
        return

    msgs = [m for _, m in q]
    q.clear()
    by_channel: dict = defaultdict(list)
    for m in msgs:
        by_channel[m.channel].append(m)
    for ch, lst in by_channel.items():
        try:
            if len(lst) == 1:
                await lst[0].delete()
            else:
                await ch.delete_messages(lst)
        except (discord.Forbidden, discord.HTTPException):
            pass

    timed_out = True
    try:
        await message.author.timeout(timedelta(minutes=SPAM_TIMEOUT_MINUTES), reason="حماية: سبام")
    except (discord.Forbidden, discord.HTTPException):
        timed_out = False

    try:
        note = (f"{message.author.mention} ⛔ سبام! تم حذف رسائلك"
                + (f" وإعطاؤك تايم {SPAM_TIMEOUT_MINUTES} دقيقة." if timed_out else "."))
        await message.channel.send(note, delete_after=10)
    except (discord.Forbidden, discord.HTTPException):
        pass
    await _log(message.guild, "🛡️ سبام", discord.Color.orange(), [
        ("العضو", f"{message.author.mention} (`{message.author.id}`)"),
        ("الروم", message.channel.mention),
        ("الرسائل المحذوفة", len(msgs)),
        ("العقوبة", f"تايم {SPAM_TIMEOUT_MINUTES} دقيقة" if timed_out else "ما قدرت أعطيه تايم (صلاحية/رتبة)"),
    ])


# ============================================================
# 2) روابط الدعوات
# ============================================================
async def _handle_invite(message: discord.Message) -> bool:
    codes = [c.lower() for c in INVITE_PATTERN.findall(message.content)]
    if not codes or all(c in (x.lower() for x in ALLOWED_INVITE_CODES) for c in codes):
        return False
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass
    try:
        await message.channel.send(f"{message.author.mention} ❌ ممنوع نشر روابط الدعوات هنا.", delete_after=8)
    except (discord.Forbidden, discord.HTTPException):
        pass
    return True   # (نشر الرابط يتسجل أصلًا ببوتك بـ security-logs، فما نكرره)


# ============================================================
# 3) الريد
# ============================================================
_joins: dict[int, deque] = defaultdict(deque)
_raid_state: dict[int, dict] = {}


async def _raid_action(member: discord.Member) -> bool:
    try:
        if RAID_ACTION == "timeout":
            await member.timeout(timedelta(hours=1), reason="حماية: ريد")
        else:
            await member.kick(reason="حماية: ريد")
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def _end_raid(guild: discord.Guild, state: dict) -> None:
    await asyncio.sleep(RAID_LOCK_SECONDS)
    if _raid_state.get(guild.id) is state:
        _raid_state.pop(guild.id, None)
    await _log(guild, "✅ انتهى وضع الحماية من الريد", discord.Color.green(),
               [("عدد الحسابات اللي انعاقبت", state["count"])])


async def _handle_raid(member: discord.Member) -> None:
    guild = member.guild
    now = time.monotonic()
    state = _raid_state.get(guild.id)
    if state and now < state["until"]:
        if await _raid_action(member):
            state["count"] += 1
        return

    q = _joins[guild.id]
    q.append((now, member))
    while q and now - q[0][0] > RAID_SECONDS:
        q.popleft()
    if len(q) < RAID_JOINS:
        return

    batch = [m for _, m in q]
    q.clear()
    state = {"until": now + RAID_LOCK_SECONDS, "count": 0}
    _raid_state[guild.id] = state
    for m in batch:
        if await _raid_action(m):
            state["count"] += 1
    await _log(guild, "🚨 هجوم ريد!", discord.Color.red(), [
        ("التفاصيل", f"دخل {len(batch)} حساب خلال {RAID_SECONDS} ثانية."),
        ("الإجراء", ("طرد" if RAID_ACTION != "timeout" else "كتم ساعة") +
                    f" لكل داخل جديد لمدة {RAID_LOCK_SECONDS} ثانية."),
        ("انعاقبوا لين الحين", state["count"]),
    ], ping_owner=True)
    asyncio.create_task(_end_raid(guild, state))


# ============================================================
# 5) البوتات
# ============================================================
async def _handle_bot_join(member: discord.Member) -> None:
    if member.id in ALLOWED_BOT_IDS:
        return
    guild = member.guild
    await asyncio.sleep(1.5)   # ننتظر ينكتب سجل التدقيق
    adder = None
    try:
        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.bot_add):
            if entry.target is not None and entry.target.id == member.id:
                adder = entry.user
                break
    except (discord.Forbidden, discord.HTTPException):
        pass
    adder_member = guild.get_member(adder.id) if adder else None
    if adder_member is not None and _is_exempt(adder_member):
        return

    kicked = True
    try:
        await member.kick(reason="حماية: بوت أضافه شخص غير مصرّح")
    except (discord.Forbidden, discord.HTTPException):
        kicked = False
    await _log(guild, "🤖 بوت غير مصرّح", discord.Color.red(), [
        ("البوت", f"{member} (`{member.id}`)"),
        ("أضافه", f"{adder.mention} (`{adder.id}`)" if adder else "ما قدرت أعرف (تأكد من صلاحية View Audit Log)"),
        ("الإجراء", "تم طرد البوت" if kicked else "ما قدرت أطرده (صلاحية/رتبة)"),
    ], ping_owner=True)


# ============================================================
# 4) التخريب (anti-nuke)
# ============================================================
_nuke: dict[tuple, deque] = defaultdict(deque)


async def _punish_nuker(guild: discord.Guild, member: discord.Member, label: str, count: int) -> None:
    removed_names: list[str] = []
    ok = True
    try:
        if member.bot:
            await member.kick(reason=f"حماية: تخريب ({label})")
            action = "تم طرد البوت"
        else:
            me = guild.me
            keep = [r for r in member.roles if not r.is_default() and (r.managed or r >= me.top_role)]
            removed_names = [r.name for r in member.roles
                             if not r.is_default() and r not in keep]
            await member.edit(roles=keep, reason=f"حماية: تخريب ({label})")
            action = "تم سحب رتبه"
    except (discord.Forbidden, discord.HTTPException):
        ok = False
        action = "فشل (رتبته أعلى من رتبة البوت أو ناقص صلاحية) — تصرف يدويًا فورًا!"

    fields = [
        ("الفاعل", f"{member.mention} (`{member.id}`)"),
        ("النشاط", f"{label}: {count} عمليات بوقت قصير"),
        ("الإجراء", action),
    ]
    if ok and removed_names:
        fields.append(("الرتب اللي انسحبت (للاسترجاع يدويًا)", "، ".join(removed_names)))
    await _log(guild, "🚨 نشاط تخريبي", discord.Color.red(), fields, ping_owner=True)


async def _on_audit_entry(entry: discord.AuditLogEntry) -> None:
    if not NUKE_ENABLED or _bot_ref is None:
        return
    guild = entry.guild
    executor_id = entry.user_id
    if executor_id is None or executor_id == _bot_ref.user.id or executor_id == guild.owner_id:
        return
    member = guild.get_member(executor_id)
    if member is None or _is_exempt(member):
        return
    for label, (actions, limit, window) in NUKE_RULES.items():
        if entry.action not in actions:
            continue
        key = (guild.id, executor_id, label)
        now = time.monotonic()
        q = _nuke[key]
        q.append(now)
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            count = len(q)
            q.clear()
            await _punish_nuker(guild, member, label, count)
        break


# ============================================================
# الربط بالبوت
# ============================================================
def setup_protection(bot: commands.Bot) -> None:
    global _bot_ref
    _bot_ref = bot

    async def _on_message_protection(message: discord.Message):
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if _is_exempt(message.author):
            return
        if INVITE_ENABLED and await _handle_invite(message):
            return
        if SPAM_ENABLED and message.channel.name not in SPAM_IGNORED_CHANNELS:
            await _handle_spam(message)

    async def _on_join_protection(member: discord.Member):
        if member.id == bot.user.id:
            return
        if member.bot:
            if BOT_ADD_ENABLED:
                await _handle_bot_join(member)
            return
        if RAID_ENABLED:
            await _handle_raid(member)

    bot.add_listener(_on_message_protection, "on_message")
    bot.add_listener(_on_join_protection, "on_member_join")
    bot.add_listener(_on_audit_entry, "on_audit_log_entry_create")
