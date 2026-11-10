"""
بوت ديسكورد شامل — نسخة كاملة مدموجة (مع مركز الألعاب الموسّع)
=====================================================================
الأقسام:
  1) نظام التحذيرات (تحذير + أزرار أسباب)
  2) نظام الاقتصاد / النقاط (رصيد / نقاطي / يومي / تحويل)
  3) نظام الجولات العام (لألعاب "أول من يجاوب يفوز")
  4) مركز الألعاب
  5) نظام الإدارة الكامل (أعضاء / رومات / صوت) — بدون بريفكس، حسب الرتب
  6) .العاب و .شرح <اسم اللعبة> و .اوامر
  7) أوامر u / s / r / a / p بدون بريفكس (p = بطاقة البروفايل)
  8) زينة البروفايل بالمتجر (مثال: `.لبس سماعة راس`)

ملاحظات مهمة قبل التشغيل:
  - أوامر الأعضاء (نقاط / ألعاب / متجر) تبدأ بعلامة "." (مثال: .نقاطي ، .متجر).
  - أوامر u / s / r / a / p بدون أي بريفكس (اكتب  p  أو  p @عضو  ).
  - أوامر الإدارة بدون بريفكس (تحذير ، برا ، سجن ... إلخ):
        * ما عنده صلاحية  ← البوت يحط رياكشن ❌ بس (بدون رد)
        * نفّذ الأمر     ← رياكشن ✅
        * كتبه غلط       ← البوت يرد "استخدم الأمر بطريقة صحيحة" مع مثال
  - ملف صورة البطاقة لازم يكون جنب الملف بهذا الاسم:  Dai.png  (غيّره من PROFILE_BG_PATH)
  - مكتبات إضافية للنص العربي بالصورة (مهمة، بدونها يطلع الكلام مقلوب):
        pip install -r requirements.txt
  - رتبتا "سجن" و"اخرس" (Jailed / Muted) تتحددان بالآيدي (JAIL_ROLE_ID / MUTE_ROLE_ID).
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import itertools
import json
import math
import os
import re
import random
import threading
from io import BytesIO
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

try:
    from PIL import Image, ImageDraw, ImageFont, ImageChops
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_SHAPING_OK = True
except ImportError:
    ARABIC_SHAPING_OK = False

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
WARN_LOG_WEBHOOK_URL = os.environ.get("WARN_WEBHOOK_URL", "")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
WARNS_FILE = "warns.json"
ECONOMY_FILE = "economy.json"
JAIL_FILE = "jail_data.json"
ROLES_REMOVED_FILE = "removed_roles.json"
GAME_STATS_FILE = "game_stats.json"
SHOP_ACTIVE_FILE = "shop_active.json"
AFK_FILE = "afk.json"
PROFILE_ITEMS_FILE = "profile_items.json"

JAIL_ROLE_ID = 1552237859740844095   # رتبة السجن (Jailed)
MUTE_ROLE_ID = 1538669784395415552   # رتبة الإسكات (Muted)
WARN_LOG_CHANNEL_NAMES = ["warn-log", "توثيق-التنبيهات", "سجل-التنبيهات", "تنبيهات-اللوق", "log-تنبيهات"]
WARN_LOG_CHANNEL_ID = 1547197859169042442

# ============================================================
# 0) نظام اللوقات العام (روومات تسجيل منفصلة لكل نوع حدث)
# ============================================================
LOG_CHANNEL_IDS = {
    "member": 1538326595994001448,
    "role": 1538326865469505576,
    "mod": 1538326815142060072,
    "channel": 1538326970755063808,
    "voice": 1538327045342502942,
    "ban": 1538335749920006246,
    "modified_message": 1538339026065690624,
    "server": 1538327009837449266,
    "bot": 1538327078162927716,
    "security": 1538327174124408872,
    "delete": 1552223827449221140,
}

LOG_CHANNEL_NAMES = {
    "member": ["member-logs"],
    "role": ["role-logs"],
    "mod": ["mod-logs"],
    "channel": ["channel-logs"],
    "voice": ["voice-logs"],
    "ban": ["ban-log"],
    "modified_message": ["modified-message"],
    "server": ["server-logs"],
    "bot": ["bot-logs"],
    "security": ["security-logs"],
    "delete": ["delete-logs"],
}


def find_log_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    """يدور على روم لوق معيّن بالآيدي أول، وإذا ما لقاه يدور بالاسم."""
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
    """يرسل embed لروم اللوق المناسب لو موجود، ويتجاهل بصمت لو ما فيه روم أو ما فيه صلاحية."""
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
    """يسجل عقوبة إدارية (كتم/طرد/مسح جماعي) بروم mod-logs."""
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


async def get_audit_executor(guild: discord.Guild, action: discord.AuditLogAction,
                              target_id: int, max_age: int = 20):
    """يدور بسجل التدقيق (Audit Log) على آخر عملية من نوع معيّن على هدف معيّن ويرجع اللي سواها (أو None)."""
    await asyncio.sleep(1.5)  # ننتظر شوي عشان ديسكورد يسجل العملية بالأوديت لوق
    try:
        async for entry in guild.audit_logs(action=action, limit=10):
            if entry.target is None or entry.target.id != target_id:
                continue
            if (discord.utils.utcnow() - entry.created_at).total_seconds() > max_age:
                continue
            return entry.user
    except (discord.Forbidden, discord.HTTPException):
        pass
    return None


async def audit_who(guild: discord.Guild, action: discord.AuditLogAction, target_id: int,
                    max_age: int = 15, fallback: str = "غير معروف") -> str:
    """يرجع منشن اللي سوا العملية (من سجل التدقيق) أو fallback لو ما انعرف."""
    user = await get_audit_executor(guild, action, target_id, max_age)
    return user.mention if user else fallback


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=".", intents=intents)

import tickets
tickets.setup_tickets(bot)
import protection
protection.setup_protection(bot)
import voice_stay
voice_stay.setup_voice_stay(bot)
import ajr
ajr.setup_ajr(bot)
import bank
bank.setup_bank(bot)
import games
games.setup_games(bot)
import colors
colors.setup_colors(bot)
import card_backgrounds
# ============================================================
# فلتر المنشن الصريح (يمنع إن مجرد "الرد" على رسالة حد يعتبر منشن له)
# ============================================================
EXPLICIT_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

# رابط دعوة ديسكورد (نستخدمه لتنبيهات security-logs)
INVITE_LINK_PATTERN = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)[a-zA-Z0-9-]+", re.IGNORECASE)


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
# أدوات الرياكشن + رسالة "استخدم الأمر بطريقة صحيحة"
# ============================================================
async def react(message: discord.Message, emoji: str) -> None:
    """يحط رياكشن على رسالة الأمر (يتجاهل الأخطاء بصمت)."""
    try:
        await message.add_reaction(emoji)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass


async def usage_error(message: discord.Message, example: str) -> None:
    """يرد على الإداري إن الأمر انكتب غلط ويعطيه مثال صحيح."""
    await message.channel.send(
        f"{message.author.mention} ⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`{example}`")


# ============================================================
# 1) نظام التحذيرات (أمر "تحذير" + أزرار الأسباب)
# ============================================================
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
    """يدور على روم لوق التحذيرات بالآيدي أول، وإذا ما لقاه يدور بالاسم."""
    ch = guild.get_channel(WARN_LOG_CHANNEL_ID)
    if ch is not None:
        return ch
    for ch in guild.text_channels:
        normalized_name = ch.name.lower().replace("_", "-")
        for target_name in WARN_LOG_CHANNEL_NAMES:
            if target_name.lower() in normalized_name:
                return ch
    return None


async def send_warn_log(guild: discord.Guild, target, moderator, reason, warn_number, channel_name):
    """يرسل لوق التحذير لروم مخصص — عبر الويب هوك أولًا، وإذا ما نجح يرسله مباشرة عبر البوت لروم اللوق."""
    embed = discord.Embed(
        title="⚠️ تم تسجيل تحذير رسمي",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="العضو", value=target.mention, inline=True)
    embed.add_field(name="بواسطة", value=moderator.mention, inline=True)
    embed.add_field(name="رقم التحذير", value=f"#{warn_number}", inline=True)
    embed.add_field(name="السبب", value=reason or "لم يُذكر سبب", inline=False)
    embed.add_field(name="القناة", value=f"#{channel_name}", inline=True)
    embed.set_footer(text=f"معرف العضو: {target.id}")
    if target.display_avatar:
        embed.set_thumbnail(url=target.display_avatar.url)

    delivered = False

    if WARN_LOG_WEBHOOK_URL:
        payload = {
            "username": "نظام التحذيرات",
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
        print("[WarnSystem] ⚠️ ما قدرت أوصل لوق التحذير — لا الويب هوك اشتغل ولا لقيت روم warn-log.")


# ---------- قائمة الأسباب (منيو منسدلة — تستخدم لأمر تحذير ولكل أوامر العقوبات) ----------
REASON_BUTTONS = [
    ("🤬", "سب وشتم"), ("📢", "إزعاج"), ("🔁", "سبام"), ("🔗", "نشر روابط"), ("📣", "إعلان وترويج"),
    ("🔊", "إزعاج صوتي"), (None, "قلة احترام للإدارة"),
    ("📜", "مخالفة القوانين"), ("💥", "تخريب"), ("♻️", "تكرار المخالفة"),
]
REASON_TIMEOUT = 60


def is_staff_member(member) -> bool:
    """أي إداري (Trial Moderator وفوق) أو مالك السيرفر أو صاحب صلاحية Administrator."""
    if not isinstance(member, discord.Member):
        return False
    if member.id == member.guild.owner_id or member.guild_permissions.administrator:
        return True
    return has_role(member, TRIAL_ROLES)


class ReasonSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=text, value=text, emoji=emoji_text)
                   for emoji_text, text in REASON_BUTTONS]
        super().__init__(placeholder="اختر السبب من القائمة...", min_values=1, max_values=1,
                         options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: ReasonView = self.view
        if not await view.check_owner(interaction):
            return
        await view.finish(interaction, self.values[0])


class CustomReasonModal(discord.ui.Modal, title="سبب آخر"):
    reason_input = discord.ui.TextInput(label="اكتب السبب", placeholder="اكتب السبب هنا...",
                                         max_length=200, required=True)

    def __init__(self, parent_view: "ReasonView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        text = str(self.reason_input.value).strip() or "لم يُذكر سبب"
        await self.parent_view.finish(interaction, text)


class CustomReasonButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✍️ سبب آخر", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        view: ReasonView = self.view
        if not await view.check_owner(interaction):
            return
        await interaction.response.send_modal(CustomReasonModal(view))


class CancelReasonButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="❌ إلغاء", style=discord.ButtonStyle.danger, row=1)

    async def callback(self, interaction: discord.Interaction):
        view: ReasonView = self.view
        if not await view.check_owner(interaction):
            return
        await view.cancel(interaction)


class ReasonView(discord.ui.View):
    """رسالة فيها أزرار أسباب، بس الإداري اللي كتب الأمر يقدر يضغط."""

    def __init__(self, moderator: discord.Member, target, action_title: str, action_emoji: str):
        super().__init__(timeout=REASON_TIMEOUT)
        self.moderator = moderator
        self.target = target
        self.action_title = action_title
        self.action_emoji = action_emoji
        self.reason: str | None = None
        self.message: discord.Message | None = None
        self.add_item(ReasonSelect())
        self.add_item(CustomReasonButton())
        self.add_item(CancelReasonButton())

    def _embed(self, heading: str, color: discord.Color, reason: str | None = None, footer: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"{self.action_emoji} {heading}", color=color)
        desc = f"**العضو:** {self.target.mention}\n**الإداري:** {self.moderator.mention}"
        if reason:
            desc += f"\n**السبب:** {reason}"
        embed.description = desc
        embed.set_thumbnail(url=self.target.display_avatar.url)
        if footer:
            embed.set_footer(text=footer)
        return embed

    def prompt_embed(self) -> discord.Embed:
        return self._embed(f"{self.action_title} — اختر السبب", discord.Color.orange(),
                            footer=f"اختر السبب من القائمة تحت (عندك {REASON_TIMEOUT} ثانية)")

    async def check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.moderator.id:
            await interaction.response.send_message("⚠️ هذي الأزرار للإداري اللي كتب الأمر بس.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction: discord.Interaction, reason: str):
        self.reason = reason
        for c in self.children:
            c.disabled = True
        embed = self._embed(self.action_title, discord.Color.green(), reason=reason, footer="تم اختيار السبب ✅")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def cancel(self, interaction: discord.Interaction):
        self.reason = None
        for c in self.children:
            c.disabled = True
        embed = self._embed(self.action_title, discord.Color.red(), footer="تم إلغاء الأمر ❌")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    embed=self._embed(self.action_title, discord.Color.dark_grey(),
                                       footer="⏳ انتهى الوقت — ما تم تنفيذ أي شيء"),
                    view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


async def ask_reason(message: discord.Message, target, action_title: str, action_emoji: str) -> str | None:
    """يرسل رسالة أزرار أسباب وينتظر الإداري يختار. يرجع السبب، أو None لو لغى أو انتهى الوقت."""
    view = ReasonView(message.author, target, action_title, action_emoji)
    view.message = await message.channel.send(embed=view.prompt_embed(), view=view)
    await view.wait()
    return view.reason


async def get_reason(message: discord.Message, args: str, target, action_title: str, action_emoji: str) -> str | None:
    """لو الإداري كتب السبب بالأمر نستخدمه مباشرة، وإلا نطلع له أزرار الأسباب."""
    typed = strip_mentions(args, message.mentions)
    if typed:
        return typed
    return await ask_reason(message, target, action_title, action_emoji)


WARN_COMMAND_PATTERN = re.compile(r"^تحذير(?:\s|$)")


async def handle_warn_command(message: discord.Message):
    author = message.author

    # ما عنده صلاحية ← رياكشن ❌ بس
    if not is_staff_member(author):
        await react(message, "❌")
        return

    if not message.mentions:
        await usage_error(message, "تحذير @العضو سبب")
        return

    target = message.mentions[0]
    if target.bot or target.id == author.id:
        await react(message, "❌")
        return

    # تسلسل الرتب: ما تقدر تحذر عضو رتبته أعلى منك أو مساوية لك
    if not can_act_on(author, target):
        await react(message, "❌")
        return

    typed = strip_mentions(message.content.strip()[len("تحذير"):], message.mentions)
    reason = typed or await ask_reason(message, target, "تحذير", "⚠️")
    if reason is None:
        return

    warn_number = add_warn(message.guild.id, target.id, reason, author.id)
    await send_warn_log(message.guild, target, author, reason, warn_number, message.channel.name)
    await react(message, "✅")


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


@commands.command(name="توب", aliases=["ليدربورد"])
async def leaderboard_cmd(ctx: commands.Context):
    data = load_json(ECONOMY_FILE)
    guild_data = data.get(str(ctx.guild.id), {})
    scores = []
    for key, value in guild_data.items():
        if key.isdigit() and isinstance(value, int):
            scores.append((int(key), value))
    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:10]
    if not top:
        await ctx.send("📉 ما فيه أي نقاط مسجلة بهذا السيرفر إلى الآن.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 **توب 10 — أعلى النقاط بالسيرفر**\n"]
    for i, (uid, pts) in enumerate(top):
        member = ctx.guild.get_member(uid)
        name = member.mention if member else f"عضو غادر (`{uid}`)"
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{rank} {name} — **{pts}** نقطة")
    await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())


# يتسجل بس لو ما فيه أمر "توب" ثاني (من games.py أو غيره) — هذا يمنع خطأ "الأمر مسجل مرتين"
if bot.get_command("توب") is None and bot.get_command("ليدربورد") is None:
    bot.add_command(leaderboard_cmd)


@bot.command(name="سجلي", aliases=["سجل"])
async def game_log_cmd(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    data = load_json(GAME_STATS_FILE)
    stats = data.get(str(ctx.guild.id), {}).get(str(member.id), {"wins": 0, "losses": 0})
    wins, losses = stats.get("wins", 0), stats.get("losses", 0)
    total = wins + losses
    rate = f"{(wins / total * 100):.0f}%" if total else "—"
    await ctx.send(
        f"📊 **سجل {member.display_name}**\n"
        f"✅ فوز: **{wins}**\n"
        f"❌ خسارة: **{losses}**\n"
        f"📈 نسبة الفوز: **{rate}**"
    )


@bot.command(name="اصدار")
async def mint_points_cmd(ctx: commands.Context, amount: int):
    """يضيف نقاط من العدم لرصيد صاحب الأمر — بس لصاحب رول Owner / founder أو مالك السيرفر."""
    has_owner_role = isinstance(ctx.author, discord.Member) and has_role(ctx.author, [OWNER, FOUNDER])
    is_guild_owner = ctx.guild is not None and ctx.author.id == ctx.guild.owner_id
    if not (has_owner_role or is_guild_owner):
        await react(ctx.message, "❌")
        return
    if amount <= 0:
        await ctx.send("⚠️ المبلغ لازم يكون أكبر من صفر.")
        return
    new_balance = add_balance(ctx.guild.id, ctx.author.id, amount)
    await ctx.send(f"💰 {ctx.author.mention} تمت إضافة **{amount}** نقطة لرصيدك. رصيدك الحين: **{new_balance}** نقطة")


# ============================================================
# 3) أدوات عامة (تطبيع النص + تسجيل حذف الرسائل)
# ============================================================
def normalize(text: str) -> str:
    """تطبيع النص عشان المقارنة تكون متسامحة مع الهمزات والتاء المربوطة والتشكيل."""
    text = text.strip()
    text = re.sub(r"[إأآا]", "ا", text)
    text = text.replace("ى", "ي")
    text = text.replace("ة", "ه")
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return text.strip().lower()


# آيديات رسائل ".قول" اللي حذفها البوت نفسه — ما نسجلها بروم delete-logs
silent_deleted_ids: set[int] = set()


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    """يسجل حذف الرسائل بروم delete-logs."""
    skip_log = payload.message_id in silent_deleted_ids
    silent_deleted_ids.discard(payload.message_id)

    cached = payload.cached_message
    if cached is not None and cached.guild is not None and not skip_log:
        embed = discord.Embed(title="🗑️ تم حذف رسالة", color=discord.Color.red(),
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="الكاتب", value=cached.author.mention, inline=True)
        embed.add_field(name="الروم", value=cached.channel.mention, inline=True)
        embed.add_field(name="المحتوى", value=(cached.content[:1000] if cached.content else "(بدون نص)"), inline=False)
        deleter = await get_audit_executor(cached.guild, discord.AuditLogAction.message_delete,
                                           cached.author.id, max_age=10)
        embed.add_field(name="اللي حذفها",
                        value=deleter.mention if deleter else "الكاتب نفسه (أو غير معروف)", inline=True)
        embed.set_footer(text=f"معرف العضو: {cached.author.id}")
        await send_log(cached.guild, "delete", embed)


# ============================================================
# 10) .اوامر
# ============================================================
HELP_PUBLIC_SECTIONS = {
    "points": ("⭐ النقاط والاقتصاد", [
        "`.رصيد [@عضو]` — تشوف رصيدك أو رصيد عضو ثاني.",
        "`.نقاطي` — تشوف رصيد نقاطك.",
        "`.يومي` — تاخذ جائزتك اليومية (مرة كل 24 ساعة).",
        "`.تحويل @عضو المبلغ` — تحول نقاط لعضو ثاني.",
        "`.توب` — لوحة الصدارة، أعلى 10 لاعبين بالنقاط.",
        "`.سجلي [@عضو]` — عدد مرات الفوز والخسارة بالألعاب.",
        "`.متجر` — يفتح المتجر بأزرار، تضغط على المنتج وتشتريه.",
        "`.شراء <العنصر>` — بديل للأزرار، تشتري بالاسم (مثال: `.شراء قبعة كاوبوي`).",
        "`.لبس <العنصر>` — تلبس زينة اشتريتها على بطاقتك (مثال: `.لبس سماعة راس`).",
        "`.خلع` — تخلع كل الزينة اللي لابسها.",
    ]),
    "games": ("🎮 الألعاب", [
        "`.العاب` — قائمة كل الألعاب (الجماعية والفردية).",
        "`.شرح اسم_اللعبة` — شرح أي لعبة بالتفصيل.",
    ]),
    "info": ("🔎 معلومات (بدون نقطة)", [
        "`p [@عضو]` — بطاقة البروفايل: الصورة + فلوس البنك + النقاط + الزينة.",
        "`u [@عضو]` — معلومات الحساب.",
        "`s` — معلومات السيرفر.",
        "`r` — رتب السيرفر.",
        "`a [@عضو]` — صورة الحساب (الافتار).",
    ]),
    "general": ("ℹ️ عام", [
        "`.قول <النص>` — يحذف رسالتك والبوت يكتب النص عنك.",
        "`.afk <السبب>` — تفعّل وضع AFK.",
        "`.اوامر` — تعرض هذي القائمة.",
    ]),
}

HELP_BUTTONS = [
    ("points", "النقاط", "⭐", discord.ButtonStyle.secondary),
    ("games", "الألعاب", "🎮", discord.ButtonStyle.secondary),
    ("info", "معلومات", "🔎", discord.ButtonStyle.secondary),
    ("general", "عام", "ℹ️", discord.ButtonStyle.secondary),
    ("admin", "الإدارة", "🛡️", discord.ButtonStyle.danger),
]


def _help_embed(title: str, description: str, user) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    if bot.user is not None:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text=f"طلب بواسطة {user.display_name}")
    return embed


def _can_see_admin_help(member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    return member.id == member.guild.owner_id or has_role(member, TRIAL_ROLES)


class HelpCategoryButton(discord.ui.Button):
    def __init__(self, key: str, label: str, emoji: str, style: discord.ButtonStyle):
        super().__init__(label=label, emoji=emoji, style=style)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        if self.key == "admin":
            if not _can_see_admin_help(user):
                await interaction.response.send_message("❌ هذا القسم لأصحاب رتب الإدارة بس.", ephemeral=True)
                return
            await interaction.response.send_message(embeds=build_admin_help_embeds(), ephemeral=True)
            return
        title, lines = HELP_PUBLIC_SECTIONS[self.key]
        embed = _help_embed(title, "\n".join(lines), user)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.message: discord.Message | None = None
        for key, label, emoji, style in HELP_BUTTONS:
            self.add_item(HelpCategoryButton(key, label, emoji, style))

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


@bot.command(name="اوامر", aliases=["الاوامر"])
async def commands_list_cmd(ctx: commands.Context):
    embed = _help_embed(
        "📋 قائمة الأوامر",
        "أوامر الأعضاء تبدأ بـ `.` ما عدا أوامر المعلومات (`p` `u` `s` `r` `a`) فهي بدون نقطة.\n"
        "اضغط على القسم اللي تبيه من الأزرار تحت وتطلع لك أوامره.\n\n"
        "🛡️ قسم الإدارة يشوفه بس أصحاب رتب الإدارة",
        ctx.author)
    view = HelpView()
    view.message = await ctx.send(embed=embed, view=view)


# ---------- .قول: البوت يكرر النص اللي تكتبه ----------
SAY_COMMAND_PATTERN = re.compile(r"^\.قول\s+\S")


@bot.command(name="قول")
async def say_cmd(ctx: commands.Context, *, text: str = None):
    if not text or not text.strip():
        await ctx.send("⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`.قول النص اللي تبيه`")
        return
    if ctx.guild is not None and message_has_blocked_link(text) and not is_link_exempt(ctx.author):
        await ctx.send(f"{ctx.author.mention} ❌ ما أقدر أرسل روابط.")
        return
    await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())


# ---------- .تست: يتأكد إن البوت شغال ----------
@bot.command(name="تست")
async def test_cmd(ctx: commands.Context):
    ms = round(bot.latency * 1000)
    await ctx.send(f"✅ البوت شغال — سرعة الاتصال: **{ms}ms**")


# ============================================================
# 11) نظام الإدارة الكامل — بدون بريفكس، حسب الرتب
# ============================================================
FOUNDER = 1557117850508992552
OWNER = 1524910780875673652
CO_OWNER = 1524916030718214325
VICE_OWNER = 1544178168678580234
ADMIN = 1524915462943801374
MANAGEMENT = 1545041689444614264
VERIFICATION_HEAD = 1554430227688718456
HEAD_MOD = 1544180741015998486
MODERATOR = 1524915277266026537
TRIAL_MOD = 1548014045825863750
SUPPORT = 1544184383626281030
STAFF = 1545041865869365309

ROLE_LABELS = {
    FOUNDER: "founder",
    OWNER: "Owner",
    CO_OWNER: "Co-Owner",
    VICE_OWNER: "Vice Owner",
    ADMIN: "Admin",
    MANAGEMENT: "Management",
    VERIFICATION_HEAD: "Verification Head",
    HEAD_MOD: "Head Moderator",
    MODERATOR: "Moderator",
    TRIAL_MOD: "Trial Moderator",
    SUPPORT: "Support",
    STAFF: "staff",
}

TOP_ROLES = [VICE_OWNER, CO_OWNER, OWNER, FOUNDER]
ADMIN_ROLES = [ADMIN] + TOP_ROLES
MANAGEMENT_ROLES = [MANAGEMENT] + ADMIN_ROLES
HEAD_MOD_ROLES = [HEAD_MOD] + MANAGEMENT_ROLES
MOD_ROLES = [MODERATOR] + HEAD_MOD_ROLES
TRIAL_ROLES = [TRIAL_MOD] + MOD_ROLES


def has_role(member: discord.Member, allowed: list[int]) -> bool:
    ids = {r.id for r in member.roles}
    return any(rid in ids for rid in allowed)


HIERARCHY_DENY_TEXT = "❌ ما تقدر تنفذ هذا الأمر على عضو رتبته أعلى منك أو مساوية لرتبتك."


def get_rank(member) -> int:
    """رقم رتبة العضو بتسلسل الإدارة (-1 = ما معه رتبة إدارة). مالك السيرفر أعلى من الكل."""
    if not isinstance(member, discord.Member):
        return -1
    if member.id == member.guild.owner_id:
        return 999
    ids = {r.id for r in member.roles}
    rank = -1
    for i, role_id in enumerate(TRIAL_ROLES):
        if role_id in ids:
            rank = max(rank, i)
    if rank < 0 and member.guild_permissions.administrator:
        rank = TRIAL_ROLES.index(ADMIN)
    return rank


def can_act_on(author, target, allow_self: bool = False) -> bool:
    """يرجع True فقط لو رتبة المنفّذ أعلى من رتبة الهدف (مو مساوية)."""
    if allow_self and author.id == target.id:
        return True
    return get_rank(author) > get_rank(target)


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
    return timedelta(minutes=value)


async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, reason="نظام الإدارة - إنشاء تلقائي")
    return role


async def reply(message: discord.Message, text: str):
    await message.channel.send(text)


# ------------------------------------------------------------
# كل دالة أمر إداري ترجع:
#   True  ← نجح الأمر      (رياكشن ✅)
#   False ← فشل الأمر      (رياكشن ❌)
#   None  ← ما يحتاج رياكشن (كتب الأمر غلط / ألغى / انمسحت رسالة الأمر)
# ------------------------------------------------------------

# ---------- إدارة الأعضاء ----------
async def cmd_ban(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "برا @العضو سبب")
        return None
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "حظر", "🔨")
    if reason is None:
        return None
    try:
        await target.ban(reason=reason)
        return True
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أحظر هذا العضو (صلاحياتي أقل من رتبته).")
        return False


async def cmd_unban(message: discord.Message, args: str):
    arg = args.strip()
    if not arg.isdigit():
        await usage_error(message, "سماح 123456789012345678")
        return None
    try:
        user = discord.Object(id=int(arg))
        await message.guild.unban(user, reason=f"بواسطة {message.author}")
        return True
    except discord.NotFound:
        await reply(message, "❌ ما فيه حظر بهذا الآيدي.")
        return False


async def cmd_kick(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "ترحيل @العضو سبب")
        return None
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "طرد", "👢")
    if reason is None:
        return None
    try:
        await target.kick(reason=reason)
        await log_mod_action(message.guild, "👢 طرد عضو", message.author, target, reason)
        return True
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أطرد هذا العضو.")
        return False


async def cmd_timeout(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "تايم @العضو 10m سبب")
        return None
    target = message.mentions[0]
    remainder = strip_mentions(args, message.mentions)
    tokens = remainder.split()
    if tokens and re.match(r"^\d+\s*[smhdدسي]?$", tokens[0]):
        duration = parse_duration(tokens[0])
        typed_reason = " ".join(tokens[1:])
    else:
        duration = timedelta(minutes=10)
        typed_reason = remainder
    reason = typed_reason or await ask_reason(message, target, "تايم", "⏱️")
    if reason is None:
        return None
    try:
        await target.timeout(discord.utils.utcnow() + duration, reason=reason)
        await log_mod_action(message.guild, "⏱️ تايم (كتم مؤقت)", message.author, target, reason,
                              {"المدة": str(duration)})
        return True
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أعطي هذا العضو تايم.")
        return False


async def cmd_untimeout(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "تحرير @العضو")
        return None
    target = message.mentions[0]
    await target.timeout(None, reason=f"بواسطة {message.author}")
    await log_mod_action(message.guild, "✅ فك تايم", message.author, target)
    return True


async def cmd_textmute(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "اخرس @العضو سبب")
        return None
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "إسكات بالشات", "🔇")
    if reason is None:
        return None
    role = message.guild.get_role(MUTE_ROLE_ID)
    if role is None:
        await reply(message, "❌ رتبة الإسكات (Muted) مو موجودة بالسيرفر — تأكد من الآيدي بالكود.")
        return False
    await target.add_roles(role, reason=f"بواسطة {message.author} — {reason}")
    await log_mod_action(message.guild, "🔇 إسكات بالشات", message.author, target, reason)
    return True


async def cmd_textunmute(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "تكلم @العضو")
        return None
    target = message.mentions[0]
    role = message.guild.get_role(MUTE_ROLE_ID)
    if role and role in target.roles:
        await target.remove_roles(role, reason=f"بواسطة {message.author}")
    await log_mod_action(message.guild, "🔊 فك إسكات بالشات", message.author, target)
    return True


async def cmd_jail(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "سجن @العضو سبب")
        return None
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "سجن", "🔒")
    if reason is None:
        return None
    jail_role = message.guild.get_role(JAIL_ROLE_ID)
    if jail_role is None:
        await reply(message, "❌ رتبة السجن (Jailed) مو موجودة بالسيرفر — تأكد من الآيدي بالكود.")
        return False

    keep_roles = [r for r in target.roles if r.name != "@everyone"]
    data = load_json(JAIL_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    data.setdefault(gid, {})
    data[gid][mid] = [r.id for r in keep_roles]
    save_json(JAIL_FILE, data)

    try:
        await target.remove_roles(*keep_roles, reason="سجن")
        await target.add_roles(jail_role, reason=f"سجن بواسطة {message.author} — {reason}")
        await log_mod_action(message.guild, "🔒 سجن عضو", message.author, target, reason)
        return True
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أسجن هذا العضو.")
        return False


async def cmd_unjail(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "فك @العضو")
        return None
    target = message.mentions[0]
    data = load_json(JAIL_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    saved_ids = data.get(gid, {}).get(mid, [])
    roles = [message.guild.get_role(rid) for rid in saved_ids if message.guild.get_role(rid)]

    jail_role = message.guild.get_role(JAIL_ROLE_ID)
    if jail_role and jail_role in target.roles:
        await target.remove_roles(jail_role, reason="فك السجن")
    if roles:
        await target.add_roles(*roles, reason="فك السجن — استرجاع الرتب")
        data[gid].pop(mid, None)
        save_json(JAIL_FILE, data)
    return True


async def cmd_nick(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "لقب @العضو الاسم_الجديد")
        return None
    target = message.mentions[0]
    new_nick = strip_mentions(args, message.mentions)
    try:
        if not new_nick:
            await target.edit(nick=None, reason=f"بواسطة {message.author} — إرجاع الاسم الأصلي")
        else:
            await target.edit(nick=new_nick, reason=f"بواسطة {message.author}")
        return True
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أغيّر لقب هذا العضو.")
        return False


def find_role_from_text(guild: discord.Guild, text: str) -> discord.Role | None:
    """يدور على رتبة بالآيدي أو بالاسم (بدون منشن، عشان ما ينزعج أصحاب الرتبة)."""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        role = guild.get_role(int(text))
        if role:
            return role
    lowered = text.lower()
    for r in guild.roles:
        if not r.is_default() and r.name.lower() == lowered:
            return r
    matches = [r for r in guild.roles if not r.is_default() and lowered in r.name.lower()]
    if len(matches) == 1:
        return matches[0]
    return None


async def cmd_remove_role(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "تنزيل @العضو اسم الرتبة")
        return None
    target = message.mentions[0]
    if message.role_mentions:
        role = message.role_mentions[0]
    else:
        role_text = strip_mentions(args, message.mentions)
        role = find_role_from_text(message.guild, role_text)
        if role is None:
            await usage_error(message, "تنزيل @العضو اسم الرتبة")
            return None
    if role not in target.roles:
        await reply(message, f"⚠️ {target.mention} أصلًا ما عنده رتبة {role.name}")
        return False
    reason = await ask_reason(message, target, f"سحب رتبة {role.name}", "📤")
    if reason is None:
        return None
    await target.remove_roles(role, reason=f"بواسطة {message.author} — {reason}")
    data = load_json(ROLES_REMOVED_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    data.setdefault(gid, {})
    data[gid][mid] = role.id
    save_json(ROLES_REMOVED_FILE, data)
    await log_mod_action(message.guild, "📤 سحب رتبة", message.author, target, reason, {"الرتبة": role.name})
    return True


async def cmd_restore_role(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "رجع @العضو")
        return None
    target = message.mentions[0]
    data = load_json(ROLES_REMOVED_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    role_id = data.get(gid, {}).get(mid)
    if not role_id:
        await reply(message, f"⚠️ ما فيه رتبة محفوظة نرجعها لـ {target.mention}")
        return False
    role = message.guild.get_role(role_id)
    if role:
        await target.add_roles(role, reason=f"بواسطة {message.author}")
        data[gid].pop(mid, None)
        save_json(ROLES_REMOVED_FILE, data)
        return True
    return False


async def cmd_give_role(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "رول @العضو اسم الرتبة")
        return None
    target = message.mentions[0]
    if message.role_mentions:
        role = message.role_mentions[0]
    else:
        role_text = strip_mentions(args, message.mentions)
        role = find_role_from_text(message.guild, role_text)
        if role is None:
            await usage_error(message, "رول @العضو اسم الرتبة")
            return None
    author = message.author
    if role.is_default() or role in target.roles:
        return False
    if author.id != message.guild.owner_id and role >= author.top_role:
        return False
    try:
        await target.add_roles(role, reason=f"بواسطة {author}")
        return True
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أعطي هذي الرتبة (رتبتي أقل منها).")
        return False


# ---------- إدارة الرومات ----------
async def cmd_purge(message: discord.Message, args: str):
    amount_text = args.strip().split()[0] if args.strip() else "50"
    if not amount_text.isdigit():
        await usage_error(message, "مسح 50")
        return None
    amount = min(int(amount_text), 200)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass
    deleted = await message.channel.purge(limit=amount, before=message)
    await message.channel.send(f"🧹 تم حذف {len(deleted)} رسالة.", delete_after=7)
    await log_mod_action(message.guild, "🧹 مسح جماعي", message.author, None, None,
                          {"العدد": str(len(deleted)), "الروم": message.channel.mention})
    return None  # رسالة الأمر انحذفت، ما نقدر نحط رياكشن


async def cmd_lock(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.send_messages = False
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    return True


async def cmd_unlock(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.send_messages = None
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    return True


async def cmd_hide(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.view_channel = False
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    return True


async def cmd_show(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.view_channel = None
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    return True


# ---------- إدارة الصوت ----------
async def cmd_vc_kick(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "بره @العضو سبب")
        return None
    target = message.mentions[0]
    if not (target.voice and target.voice.channel):
        await reply(message, "⚠️ العضو مو بروم صوتي.")
        return False
    reason = await get_reason(message, args, target, "إخراج من الروم الصوتي", "👋")
    if reason is None:
        return None
    await target.move_to(None, reason=f"بواسطة {message.author} — {reason}")
    await log_mod_action(message.guild, "👋 إخراج من الروم الصوتي", message.author, target, reason)
    return True


async def cmd_vc_mute(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "اصمت @العضو سبب")
        return None
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "إسكات صوتي", "🔇")
    if reason is None:
        return None
    await target.edit(mute=True, reason=f"بواسطة {message.author} — {reason}")
    await log_mod_action(message.guild, "🔇 إسكات صوتي", message.author, target, reason)
    return True


async def cmd_vc_unmute(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "انطق @العضو")
        return None
    target = message.mentions[0]
    await target.edit(mute=False, reason=f"بواسطة {message.author}")
    return True


async def cmd_vc_pull(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "اسحب @العضو")
        return None
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل روم صوتي عشان تسحب له أحد.")
        return False
    target = message.mentions[0]
    if target.voice:
        await target.move_to(message.author.voice.channel, reason=f"بواسطة {message.author}")
        return True
    await reply(message, "⚠️ العضو مو داخل أي روم صوتي حاليًا.")
    return False


async def cmd_vc_gather(message: discord.Message, args: str):
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل روم صوتي عشان تجمع الكل عندك.")
        return False
    destination = message.author.voice.channel
    for vc in message.guild.voice_channels:
        if vc.id == destination.id:
            continue
        for member in list(vc.members):
            await member.move_to(destination, reason=f"تجميع بواسطة {message.author}")
    return True


async def cmd_vc_comehere(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "تعال @العضو")
        return None
    target = message.mentions[0]
    if not message.author.voice:
        await reply(message, "⚠️ لازم تكون داخل روم صوتي عشان أنقلك لعند العضو.")
        return False
    if target.voice and target.voice.channel:
        await message.author.move_to(target.voice.channel, reason="تعال")
        return True
    await reply(message, "⚠️ هذا العضو مو داخل روم صوتي.")
    return False


async def cmd_vc_kicklock(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "اطلع @العضو سبب")
        return None
    target = message.mentions[0]
    if not (target.voice and target.voice.channel):
        await reply(message, "⚠️ العضو مو داخل روم صوتي.")
        return False
    channel = target.voice.channel
    reason = await get_reason(message, args, target, "طرد من الصوت وقفل الروم", "🚫")
    if reason is None:
        return None
    await target.move_to(None, reason=f"بواسطة {message.author} — {reason}")
    overwrite = channel.overwrites_for(message.guild.default_role)
    overwrite.connect = False
    await channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await log_mod_action(message.guild, "🚫 طرد من الصوت وقفل الروم", message.author, target, reason,
                          {"الروم": channel.name})
    return True


async def cmd_vc_open(message: discord.Message, args: str):
    """فتح_صوتي ← يفتح الروم الصوتي اللي أنت فيه (يشيل القفل اللي حطه أمر اطلع)."""
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل الروم الصوتي عشان تفتحه.")
        return False
    channel = message.author.voice.channel
    overwrite = channel.overwrites_for(message.guild.default_role)
    overwrite.connect = None
    await channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await log_mod_action(message.guild, "🔓 فتح روم صوتي", message.author, None, None,
                          {"الروم": channel.name})
    return True


async def cmd_vc_allow(message: discord.Message, args: str):
    if not message.mentions:
        await usage_error(message, "مسموح @العضو")
        return None
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل الروم الصوتي المقفول عشان تسمح لأحد.")
        return False
    target = message.mentions[0]
    channel = message.author.voice.channel
    overwrite = channel.overwrites_for(target)
    overwrite.connect = True
    await channel.set_permissions(target, overwrite=overwrite)
    return True


async def cmd_remove_warn(message: discord.Message, args: str):
    """شيل تحذير @عضو  ← يشيل آخر تحذير | شيل تحذير @عضو الكل  ← يشيل كل تحذيراته."""
    if not message.mentions:
        await usage_error(message, "شيل تحذير @العضو")
        return None
    target = message.mentions[0]
    if target.id == message.author.id:
        return False
    remove_all = strip_mentions(args, message.mentions).strip() in ("الكل", "كل", "all")

    data = load_json(WARNS_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    user_warns = data.get(gid, {}).get(mid, [])
    if not user_warns:
        await reply(message, f"⚠️ {target.mention} ما عليه أي تحذير.")
        return False

    if remove_all:
        data[gid][mid] = []
    else:
        user_warns.pop()
        data[gid][mid] = user_warns
    save_json(WARNS_FILE, data)
    await log_mod_action(message.guild, "🧹 إزالة تحذير", message.author, target,
                         extra={"المحذوف": "الكل" if remove_all else "آخر تحذير",
                                "المتبقي": len(data[gid][mid])})
    return True


# ---------- جدول الأوامر الإدارية ----------
ADMIN_COMMANDS = {
    # إدارة الأعضاء
    "برا": (TOP_ROLES, cmd_ban),
    "سماح": (TOP_ROLES, cmd_unban),
    "ترحيل": (MOD_ROLES, cmd_kick),
    "كيك": (MOD_ROLES, cmd_kick),
    "تايم": (TRIAL_ROLES, cmd_timeout),
    "اص": (TRIAL_ROLES, cmd_timeout),
    "تحرير": (TRIAL_ROLES, cmd_untimeout),
    "اخرس": (MANAGEMENT_ROLES, cmd_textmute),
    "تكلم": (MANAGEMENT_ROLES, cmd_textunmute),
    "سجن": (ADMIN_ROLES, cmd_jail),
    "فك": (ADMIN_ROLES, cmd_unjail),
    "لقب": (MOD_ROLES, cmd_nick),
    "اسم": (MOD_ROLES, cmd_nick),
    "تنزيل": (ADMIN_ROLES, cmd_remove_role),
    "رجع": (ADMIN_ROLES, cmd_restore_role),
    "رول": (TOP_ROLES, cmd_give_role),
    "شيل تحذير": (MOD_ROLES, cmd_remove_warn),
    # إدارة الرومات
    "اباده": (MANAGEMENT_ROLES, cmd_purge),
    "مسح": (MANAGEMENT_ROLES, cmd_purge),
    "قفل": (ADMIN_ROLES, cmd_lock),
    "فتح": (ADMIN_ROLES, cmd_unlock),
    "اخفاء": (TOP_ROLES, cmd_hide),
    "خفي": (TOP_ROLES, cmd_hide),
    "اظهار": (TOP_ROLES, cmd_show),
    # إدارة الصوت
    "بره": (MOD_ROLES, cmd_vc_kick),
    "اصمت": (MOD_ROLES, cmd_vc_mute),
    "انطق": (MOD_ROLES, cmd_vc_unmute),
    "اسحب": (MOD_ROLES, cmd_vc_pull),
    "اجمعهم": (HEAD_MOD_ROLES, cmd_vc_gather),
    "تعال": (HEAD_MOD_ROLES, cmd_vc_comehere),
    "كم هير بيبي": (HEAD_MOD_ROLES, cmd_vc_comehere),
    "اطلع": (ADMIN_ROLES, cmd_vc_kicklock),
    "مسموح": (ADMIN_ROLES, cmd_vc_allow),
    "فتح_صوتي": (ADMIN_ROLES, cmd_vc_open),
}

HIERARCHY_TRIGGERS = {
    "برا", "ترحيل", "كيك", "تايم", "اص", "تحرير", "اخرس", "تكلم", "سجن", "فك",
    "لقب", "اسم", "تنزيل", "رجع", "شيل تحذير",
    "بره", "اصمت", "انطق", "اسحب", "اطلع", "مسموح",
}
HIERARCHY_SELF_ALLOWED = {"لقب", "اسم"}

SORTED_TRIGGERS = sorted(ADMIN_COMMANDS.keys(), key=len, reverse=True)


async def try_dispatch_admin_command(message: discord.Message) -> bool:
    content = message.content.strip()
    for trigger in SORTED_TRIGGERS:
        if content == trigger or content.startswith(trigger + " "):
            allowed_roles, handler = ADMIN_COMMANDS[trigger]

            # ما عنده صلاحية ← رياكشن ❌ بدون أي رد
            if not isinstance(message.author, discord.Member) or not has_role(message.author, allowed_roles):
                await react(message, "❌")
                return True

            # تسلسل الرتب ← رياكشن ❌
            if trigger in HIERARCHY_TRIGGERS and message.mentions:
                target = message.mentions[0]
                if not can_act_on(message.author, target, allow_self=(trigger in HIERARCHY_SELF_ALLOWED)):
                    await react(message, "❌")
                    return True

            args = content[len(trigger):].strip()
            try:
                result = await handler(message, args)
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"[Admin] فشل تنفيذ '{trigger}': {e}")
                result = False

            if result is True:
                await react(message, "✅")
            elif result is False:
                await react(message, "❌")
            return True
    return False


# ---------- .اوامر اداريه: قائمة الأوامر الإدارية مع الرتب المسموح لها ----------
ADMIN_HELP_SECTIONS = [
    ("👥 إدارة الأعضاء", [
        (["برا"], "برا @عضو [السبب]", "حظر عضو من السيرفر.", None),
        (["سماح"], "سماح <آيدي العضو>", "فك الحظر عن عضو بالآيدي.", None),
        (["ترحيل", "كيك"], "ترحيل / كيك @عضو [السبب]", "طرد عضو من السيرفر.", None),
        (["تايم", "اص"], "تايم / اص @عضو [المدة] [السبب]", "كتم مؤقت (تايم أوت)، المدة مثل 10m أو 2h أو 1d.", None),
        (["تحرير"], "تحرير @عضو", "فك التايم عن عضو.", None),
        (["اخرس"], "اخرس @عضو [السبب]", "إسكات عضو بالشات (رتبة Muted).", None),
        (["تكلم"], "تكلم @عضو", "فك الإسكات بالشات.", None),
        (["سجن"], "سجن @عضو [السبب]", "سجن عضو (يسحب رتبه ويعطيه رتبة Jailed).", None),
        (["فك"], "فك @عضو", "فك السجن وإرجاع رتب العضو.", None),
        (["لقب", "اسم"], "لقب / اسم @عضو [الاسم_الجديد]", "تغيير لقب عضو بالسيرفر، وبدون اسم جديد يرجع اسمه الأصلي.", None),
        (["تنزيل"], "تنزيل @عضو اسم_الرتبة", "سحب رتبة من عضو (السبب من الأزرار).", None),
        (["رجع"], "رجع @عضو", "إرجاع آخر رتبة سُحبت من العضو.", None),
        (["رول"], "رول @عضو اسم_الرتبة", "إعطاء رتبة لعضو (بشرط تكون أقل من رتبتك).", None),
        (["تحذير"], "تحذير @عضو [السبب]", "تسجيل تحذير رسمي على عضو، وتطلع لك أزرار أسباب تختار منها.",
         f"أي إداري (**{ROLE_LABELS[TRIAL_MOD]}** وأعلى)"),
        (["شيل تحذير"], "شيل تحذير @عضو [الكل]", "يشيل آخر تحذير مسجل على عضو، أو كل تحذيراته لو كتبت «الكل».", None),
    ]),
    ("💬 إدارة الرومات", [
        (["اباده", "مسح"], "اباده / مسح [العدد]", "مسح رسائل من الروم (افتراضي 50، أقصى 200).", None),
        (["قفل"], "قفل", "قفل الروم الحالي عن الكتابة.", None),
        (["فتح"], "فتح", "فتح الروم الحالي للكتابة.", None),
        (["اخفاء", "خفي"], "اخفاء / خفي", "إخفاء الروم الحالي عن الأعضاء.", None),
        (["اظهار"], "اظهار", "إظهار الروم الحالي للأعضاء.", None),
    ]),
    ("🔊 إدارة الصوت", [
        (["بره"], "بره @عضو [السبب]", "إخراج عضو من الروم الصوتي.", None),
        (["اصمت"], "اصمت @عضو [السبب]", "إسكات عضو صوتيًا.", None),
        (["انطق"], "انطق @عضو", "فك الإسكات الصوتي عن عضو.", None),
        (["اسحب"], "اسحب @عضو", "سحب عضو لروم صوتي أنت فيه.", None),
        (["اجمعهم"], "اجمعهم", "جمع كل اللي بالرومات الصوتية عندك.", None),
        (["تعال", "كم هير بيبي"], "تعال / كم هير بيبي @عضو", "ينقلك لروم العضو الصوتي.", None),
        (["اطلع"], "اطلع @عضو [السبب]", "طرد عضو من الروم الصوتي وقفل الروم.", None),
        (["مسموح"], "مسموح @عضو", "السماح لعضو بدخول روم صوتي مقفول.", None),
        (["فتح_صوتي"], "فتح_صوتي", "فتح الروم الصوتي اللي أنت فيه للكل (يشيل القفل).", None),
    ]),
]


def build_admin_help_embeds() -> list[discord.Embed]:
    hierarchy = " ➜ ".join(ROLE_LABELS[r] for r in TRIAL_ROLES)
    embeds = [discord.Embed(
        title="📋 الأوامر الإدارية",
        description=(
            "الأوامر الإدارية تنكتب **بدون نقطة** (مثال: `تايم @عضو 10m`).\n"
            "الرتبة المكتوبة تحت كل أمر هي **أقل رتبة** تقدر تستخدمه، وكل الرتب الأعلى منها تقدر تستخدمه بعد.\n"
            "لو ما كتبت سبب بأوامر العقوبات، يطلع لك البوت أزرار أسباب تختار منها.\n"
            "✅ رياكشن صح = انفّذ الأمر | ❌ رياكشن اكس = ما عندك صلاحية أو ما انفّذ.\n"
            "⚠️ الأوامر اللي على الأعضاء تمشي بتسلسل الرتب: ما تقدر تنفذها على عضو رتبته أعلى منك أو مساوية لك.\n\n"
            f"**ترتيب الرتب من الأدنى للأعلى:**\n{hierarchy}"
        ),
        color=discord.Color.blurple(),
    )]
    for title, entries in ADMIN_HELP_SECTIONS:
        lines = []
        for triggers, usage, desc, roles_text in entries:
            if roles_text is None:
                roles_text = f"**{ROLE_LABELS[ADMIN_COMMANDS[triggers[0]][0][0]]}** وأعلى"
            lines.append(f"`{usage}`\n{desc}\n🔑 الرتبة: {roles_text}\n")
        embeds.append(discord.Embed(title=title, description="\n".join(lines), color=discord.Color.blurple()))
    return embeds


@bot.command(name="اوامر_اداريه")
async def send_admin_commands_help(ctx: commands.Context):
    author = ctx.author
    is_guild_owner = ctx.guild is not None and author.id == ctx.guild.owner_id
    if not (isinstance(author, discord.Member) and (is_guild_owner or has_role(author, TRIAL_ROLES))):
        await react(ctx.message, "❌")
        return

    await ctx.send(embeds=build_admin_help_embeds())


# ============================================================
# 12) المتجر — شراء أشياء بالنقاط
# ============================================================
SHOP_COLOR_ROLES = {
    "احمر": 0xE74C3C,
    "ازرق": 0x3498DB,
    "اخضر": 0x2ECC71,
    "بنفسجي": 0x9B59B6,
    "ذهبي": 0xF1C40F,
}
SHOP_COLOR_DURATION_HOURS = 24
SHOP_TITLE_DURATION_HOURS = 24
SHOP_TITLE_PRICE = 300
SHOP_COLOR_PRICE = 250
SHOP_WARN_CLEAR_PRICE = 500

# ---------- زينة بطاقة البروفايل (أمر p) — تنشترى مرة وحدة وتبقى للأبد ----------
# slot: head = فوق الراس (واحدة بس تنلبس) / ears = سماعات / face = نظارات وأقنعة / mouth = شنب ولحية
# tilt: ميلان الزينة بالدرجات (موجب = لليسار، سالب = لليمين). id: اسم ملف الصورة الاختياري.
# تقدر تحط صورة PNG شفافة واقعية بمجلد profile_items باسم <id>.png (مثال: profile_items/crown.png)
# وبدل الرسم الجاهز يستخدمها البوت (img_w = عرضها بوحدة نصف قطر الصورة، img_y = ارتفاعها فوق/تحت المركز).
PROFILE_ITEMS_DIR = "profile_items"
PROFILE_ITEMS = {
    # ----- فوق الراس -----
    "تاج":          {"id": "crown",    "price": 1500, "slot": "head",  "tilt": -14, "img_w": 1.6, "img_y": -1.35},
    "قبعة":         {"id": "tophat",   "price": 800,  "slot": "head",  "tilt": -12, "img_w": 1.7, "img_y": -1.35},
    "كاب":          {"id": "cap",      "price": 600,  "slot": "head",  "tilt": -13, "img_w": 1.9, "img_y": -1.15},
    "هالة":         {"id": "halo",     "price": 1200, "slot": "head",  "tilt": -10, "img_w": 1.4, "img_y": -1.55},
    "قبعة كاوبوي":  {"id": "cowboy",   "price": 900,  "slot": "head",  "tilt": -14, "img_w": 2.3, "img_y": -1.2},
    "قبعة ساحر":    {"id": "wizard",   "price": 1000, "slot": "head",  "tilt": -12, "img_w": 1.8, "img_y": -1.4},
    "قبعة طباخ":    {"id": "chef",     "price": 700,  "slot": "head",  "tilt": -10, "img_w": 1.5, "img_y": -1.3},
    "خوذة فايكنج":  {"id": "viking",   "price": 1100, "slot": "head",  "tilt": -9,  "img_w": 2.5, "img_y": -1.2},
    "قرون":         {"id": "horns",    "price": 900,  "slot": "head",  "tilt": -8,  "img_w": 1.6, "img_y": -1.3},
    "قبعة سانتا":   {"id": "santa",    "price": 750,  "slot": "head",  "tilt": -15, "img_w": 1.9, "img_y": -1.3},
    "بيريه":        {"id": "beret",    "price": 650,  "slot": "head",  "tilt": -16, "img_w": 1.9, "img_y": -1.15},
    "غترة":         {"id": "ghutra",   "price": 1000, "slot": "head",  "tilt": -6,  "img_w": 2.3, "img_y": -0.8},
    # ----- النظارات -----
    "نظارة":        {"id": "glasses",  "price": 500,  "slot": "face",  "tilt": -5,  "img_w": 1.9, "img_y": -0.05},
    "نظارة شمسية":  {"id": "aviator",  "price": 700,  "slot": "face",  "tilt": -5,  "img_w": 1.9, "img_y": -0.05},
    "نظارة قلوب":   {"id": "hearts",   "price": 600,  "slot": "face",  "tilt": -5,  "img_w": 1.9, "img_y": -0.05},
    # ----- الفم -----
    "شنب":          {"id": "mustache", "price": 400,  "slot": "mouth", "tilt": 0,   "img_w": 1.5, "img_y": 0.45},
    # ----- قبعات وتيجان إضافية -----
    "قبعة قش":      {"id": "straw",    "price": 650,  "slot": "head",  "tilt": -13, "img_w": 2.6, "img_y": -1.15},
    "قبعة حفلة":    {"id": "party",    "price": 500,  "slot": "head",  "tilt": -14, "img_w": 1.2, "img_y": -1.4},
    "قبعة تخرج":    {"id": "grad",     "price": 1200, "slot": "head",  "tilt": -12, "img_w": 2.3, "img_y": -1.2},
    "قبعة قراصنة":  {"id": "pirate",   "price": 1300, "slot": "head",  "tilt": -11, "img_w": 2.6, "img_y": -1.25},
    "طاقية شتوية":  {"id": "beanie",   "price": 600,  "slot": "head",  "tilt": -10, "img_w": 1.9, "img_y": -1.2},
    "اذنان قطة":    {"id": "cat",      "price": 1100, "slot": "head",  "tilt": -7,  "img_w": 1.9, "img_y": -1.2},
    "اذنان ارنب":   {"id": "bunny",    "price": 1100, "slot": "head",  "tilt": -6,  "img_w": 1.2, "img_y": -1.5},
    "اكليل ورد":    {"id": "flowers",  "price": 900,  "slot": "head",  "tilt": -5,  "img_w": 2.2, "img_y": -0.7},
    "اكليل غار":    {"id": "laurel",   "price": 1500, "slot": "head",  "tilt": -4,  "img_w": 2.4, "img_y": -0.7},
    "تاج ماسي":     {"id": "diamond",  "price": 3500, "slot": "head",  "tilt": -14, "img_w": 1.7, "img_y": -1.35},
    # ----- سماعات الراس -----
    "سماعة راس":    {"id": "phones",      "price": 900,  "slot": "ears", "tilt": -4, "img_w": 2.8, "img_y": -0.2},
    "سماعة جيمنج":  {"id": "gaming",      "price": 1400, "slot": "ears", "tilt": -4, "img_w": 2.8, "img_y": -0.1},
    "سماعة وردية":  {"id": "phonespink",  "price": 1000, "slot": "ears", "tilt": -4, "img_w": 2.8, "img_y": -0.2},
    # ----- نظارات وأقنعة -----
    "نظارة دائرية":    {"id": "round",       "price": 550,  "slot": "face", "tilt": -5, "img_w": 1.9, "img_y": -0.05},
    "نظارة نجوم":      {"id": "starglasses", "price": 800,  "slot": "face", "tilt": -5, "img_w": 2.0, "img_y": -0.05},
    "نظارة ثلاثية":    {"id": "glasses3d",   "price": 650,  "slot": "face", "tilt": -5, "img_w": 2.0, "img_y": -0.05},
    "قناع بطل":        {"id": "mask",        "price": 900,  "slot": "face", "tilt": -4, "img_w": 2.1, "img_y": -0.05},
    "عصبة قرصان":      {"id": "eyepatch",    "price": 700,  "slot": "face", "tilt": -5, "img_w": 2.0, "img_y": -0.3},
    "نظارة مستقبلية":  {"id": "visor",       "price": 1600, "slot": "face", "tilt": -5, "img_w": 2.2, "img_y": -0.1},
    # ----- الفم واللحية -----
    "شنب مفتول":    {"id": "handlebar", "price": 700, "slot": "mouth", "tilt": 0,  "img_w": 2.2, "img_y": 0.45},
    "لحية":         {"id": "beard",     "price": 800, "slot": "mouth", "tilt": 0,  "img_w": 1.9, "img_y": 0.65},
    "ذقن":          {"id": "goatee",    "price": 450, "slot": "mouth", "tilt": 0,  "img_w": 0.9, "img_y": 0.85},
    "احمر شفاه":    {"id": "lips",      "price": 500, "slot": "mouth", "tilt": 0,  "img_w": 0.9, "img_y": 0.65},
    "وردة":         {"id": "rose",      "price": 600, "slot": "mouth", "tilt": -8, "img_w": 1.2, "img_y": 0.65},
    "مصاصة":        {"id": "lollipop",  "price": 350, "slot": "mouth", "tilt": -6, "img_w": 1.2, "img_y": 0.9},
}

# أقسام المتجر (للأزرار): (مفتاح, اسم القسم, [أسماء العناصر بالترتيب])
SHOP_CATEGORIES = [
    ("hats",    "🎩 قبعات",           ["قبعة", "كاب", "قبعة كاوبوي", "قبعة ساحر", "قبعة طباخ", "قبعة سانتا", "بيريه", "غترة",
                                     "قبعة قش", "قبعة حفلة", "قبعة تخرج", "قبعة قراصنة", "طاقية شتوية", "خوذة فايكنج"]),
    ("crowns",  "👑 تيجان وزينة الراس", ["تاج", "تاج ماسي", "هالة", "قرون", "اذنان قطة", "اذنان ارنب", "اكليل ورد", "اكليل غار"]),
    ("phones",  "🎧 سماعات",          ["سماعة راس", "سماعة جيمنج", "سماعة وردية"]),
    ("glasses", "👓 نظارات وأقنعة",    ["نظارة", "نظارة شمسية", "نظارة قلوب", "نظارة دائرية", "نظارة نجوم", "نظارة ثلاثية",
                                     "قناع بطل", "عصبة قرصان", "نظارة مستقبلية"]),
    ("mouth",   "🧔 الفم واللحية",     ["شنب", "شنب مفتول", "لحية", "ذقن", "احمر شفاه", "وردة", "مصاصة"]),
]
PROFILE_ITEM_ALIASES = {
    "كاوبوي": "قبعة كاوبوي", "ساحر": "قبعة ساحر", "طباخ": "قبعة طباخ", "سانتا": "قبعة سانتا",
    "فايكنج": "خوذة فايكنج", "فايكنغ": "خوذة فايكنج", "خوذة": "خوذة فايكنج",
    "شماغ": "غترة", "شماق": "غترة", "عقال": "غترة", "قرن": "قرون", "قبعه": "قبعة", "قبوع": "قبعة",
    "نضارة": "نظارة", "نضاره": "نظارة", "شمسيه": "نظارة شمسية", "نظارة طيار": "نظارة شمسية",
    "قلوب": "نظارة قلوب", "طاقيه": "كاب", "طاقية": "كاب", "شوارب": "شنب", "شارب": "شنب",
    "سماعة": "سماعة راس", "سماعات": "سماعة راس", "هيدفون": "سماعة راس", "هيدفونز": "سماعة راس",
    "جيمنج": "سماعة جيمنج", "قيمنق": "سماعة جيمنج", "سماعة قيمنق": "سماعة جيمنج", "سماعة وردي": "سماعة وردية",
    "قش": "قبعة قش", "حفلة": "قبعة حفلة", "حفله": "قبعة حفلة", "تخرج": "قبعة تخرج", "قراصنة": "قبعة قراصنة",
    "قرصان": "عصبة قرصان", "بحار": "قبعة قراصنة", "بنيه": "طاقية شتوية", "بيني": "طاقية شتوية", "شتوية": "طاقية شتوية",
    "قطة": "اذنان قطة", "قطه": "اذنان قطة", "ارنب": "اذنان ارنب", "أرنب": "اذنان ارنب", "أذنان قطة": "اذنان قطة",
    "أذنان ارنب": "اذنان ارنب", "ورد": "اكليل ورد", "إكليل ورد": "اكليل ورد", "اكليل": "اكليل ورد",
    "إكليل غار": "اكليل غار", "غار": "اكليل غار", "ماسي": "تاج ماسي", "تاج الماس": "تاج ماسي", "الماس": "تاج ماسي",
    "دائرية": "نظارة دائرية", "نجوم": "نظارة نجوم", "ثلاثية": "نظارة ثلاثية", "3d": "نظارة ثلاثية",
    "نظارة 3d": "نظارة ثلاثية", "قناع": "قناع بطل", "ماسك": "قناع بطل", "مستقبلية": "نظارة مستقبلية",
    "مستقبل": "نظارة مستقبلية", "لحيه": "لحية", "لحى": "لحية", "ذقن": "ذقن", "مفتول": "شنب مفتول",
    "شفاه": "احمر شفاه", "روج": "احمر شفاه", "احمر": "احمر شفاه", "ورده": "وردة", "مصاصه": "مصاصة", "لوليبوب": "مصاصة",
}


def resolve_profile_item(text: str | None) -> str | None:
    """يفهم اسم الزينة بأي صيغة (قبعه/قبعة، كاوبوي/قبعة كاوبوي...) ويرجع اسمها الرسمي أو None."""
    text = " ".join((text or "").split())
    if not text:
        return None
    if text in PROFILE_ITEMS:
        return text
    if text in PROFILE_ITEM_ALIASES:
        return PROFILE_ITEM_ALIASES[text]
    fixed = " ".join(w[:-1] + "ة" if w.endswith("ه") and len(w) > 2 else w for w in text.split())
    if fixed in PROFILE_ITEMS:
        return fixed
    if fixed in PROFILE_ITEM_ALIASES:
        return PROFILE_ITEM_ALIASES[fixed]
    # كلمة وحدة من الاسم (مثل "ساحر") لو تدل على عنصر واحد بس
    hits = [n for n in PROFILE_ITEMS if fixed and fixed in n.split()]
    return hits[0] if len(hits) == 1 else None


# روم الأوامر (الثيرمنل) — حط آيدي الروم هنا عشان البوت يوجّه الناس له بعد الشراء.
# لو خليته 0 يدور على روم اسمه فيه terminal / ثيرمنل / ترمنل.
COMMANDS_CHANNEL_ID = 1541668492871335987
_COMMANDS_CHANNEL_HINTS = ("terminal", "ثيرمنل", "ترمنل", "تيرمنل", "ثرمنل")


def commands_channel_text(guild: discord.Guild) -> str:
    """منشن روم الأوامر لو لقيناه، وإلا عبارة عامة."""
    ch = guild.get_channel(COMMANDS_CHANNEL_ID) if COMMANDS_CHANNEL_ID else None
    if ch is None:
        for c in guild.text_channels:
            if any(h in c.name.lower() for h in _COMMANDS_CHANNEL_HINTS):
                ch = c
                break
    return ch.mention if ch is not None else "روم الأوامر"


def get_profile_items(guild_id: int, user_id: int) -> dict:
    data = load_json(PROFILE_ITEMS_FILE)
    entry = data.get(str(guild_id), {}).get(str(user_id), {})
    return {
        "owned": list(entry.get("owned", [])),
        "head": entry.get("head"),
        "face": entry.get("face"),
        "mouth": entry.get("mouth"),
        "ears": entry.get("ears"),
    }


def save_profile_items(guild_id: int, user_id: int, entry: dict) -> None:
    data = load_json(PROFILE_ITEMS_FILE)
    data.setdefault(str(guild_id), {})[str(user_id)] = entry
    save_json(PROFILE_ITEMS_FILE, data)


def _shop_set_active(guild_id: int, user_id: int, item_type: str, hours: int, extra: dict) -> None:
    data = load_json(SHOP_ACTIVE_FILE)
    gid, uid = str(guild_id), str(user_id)
    data.setdefault(gid, {})
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    data[gid][uid] = {"type": item_type, "expires": expires, **extra}
    save_json(SHOP_ACTIVE_FILE, data)


def _shop_clear_active(guild_id: int, user_id: int) -> dict | None:
    data = load_json(SHOP_ACTIVE_FILE)
    gid, uid = str(guild_id), str(user_id)
    entry = data.get(gid, {}).pop(uid, None)
    if entry is not None:
        save_json(SHOP_ACTIVE_FILE, data)
    return entry


# ---------- منطق الشراء (يستخدمه أمر .شراء وأزرار المتجر) ----------
async def purchase_title(guild: discord.Guild, author: discord.Member, title_text: str) -> tuple[bool, str]:
    title_text = (title_text or "").strip()
    if not title_text:
        return False, "⚠️ اكتب اللقب اللي تبيه."
    price = SHOP_TITLE_PRICE
    if get_balance(guild.id, author.id) < price:
        return False, f"❌ رصيدك ما يكفي (تحتاج {price} نقطة)."
    old_entry = _shop_clear_active(guild.id, author.id)
    original_nick = (old_entry.get("original_nick")
                     if (old_entry and old_entry.get("type") == "title") else author.nick)
    new_nick = f"{original_nick or author.name} | {title_text}"[:32]
    try:
        await author.edit(nick=new_nick, reason="شراء لقب مؤقت من المتجر")
    except discord.Forbidden:
        return False, "❌ ما أقدر أغيّر لقبك (رتبتك أعلى من رتبتي أو ينقصني صلاحية)."
    add_balance(guild.id, author.id, -price)
    _shop_set_active(guild.id, author.id, "title", SHOP_TITLE_DURATION_HOURS, {"original_nick": original_nick})
    return True, f"✅ تم! لقبك الحين **{new_nick}** لمدة {SHOP_TITLE_DURATION_HOURS} ساعة."


async def purchase_color(guild: discord.Guild, author: discord.Member, color_name: str) -> tuple[bool, str]:
    if color_name not in SHOP_COLOR_ROLES:
        return False, "⚠️ اللون غير متوفر، الألوان: " + "، ".join(SHOP_COLOR_ROLES)
    price = SHOP_COLOR_PRICE
    if get_balance(guild.id, author.id) < price:
        return False, f"❌ رصيدك ما يكفي (تحتاج {price} نقطة)."
    for name in SHOP_COLOR_ROLES:
        old_role = discord.utils.get(guild.roles, name=f"🎨 {name}")
        if old_role and old_role in author.roles:
            await author.remove_roles(old_role, reason="تبديل لون المتجر")
    role_name = f"🎨 {color_name}"
    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        role = await guild.create_role(name=role_name, color=discord.Color(SHOP_COLOR_ROLES[color_name]),
                                       reason="رتبة لون من المتجر - إنشاء تلقائي")
    try:
        await author.add_roles(role, reason="شراء لون من المتجر")
    except discord.Forbidden:
        return False, "❌ ما أقدر أعطيك هذي الرتبة (رتبتها أعلى من رتبة البوت — رتّبها بإعدادات السيرفر)."
    add_balance(guild.id, author.id, -price)
    _shop_set_active(guild.id, author.id, "color", SHOP_COLOR_DURATION_HOURS, {"role_id": role.id})
    return True, f"✅ تم! صار لونك **{color_name}** لمدة {SHOP_COLOR_DURATION_HOURS} ساعة."


def purchase_warn_clear(guild: discord.Guild, author: discord.Member) -> tuple[bool, str]:
    price = SHOP_WARN_CLEAR_PRICE
    warns_data = load_json(WARNS_FILE)
    gid, uid = str(guild.id), str(author.id)
    user_warns = warns_data.get(gid, {}).get(uid, [])
    if not user_warns:
        return False, "⚠️ ما عندك أي تنبيه تحذفه."
    if get_balance(guild.id, author.id) < price:
        return False, f"❌ رصيدك ما يكفي (تحتاج {price} نقطة)."
    user_warns.pop(0)
    warns_data[gid][uid] = user_warns
    save_json(WARNS_FILE, warns_data)
    add_balance(guild.id, author.id, -price)
    return True, f"✅ تم حذف أقدم تنبيه عندك. باقي عندك **{len(user_warns)}** تنبيه."


def purchase_profile_item(guild: discord.Guild, author: discord.Member, item: str) -> tuple[bool, str]:
    info = PROFILE_ITEMS[item]
    entry = get_profile_items(guild.id, author.id)
    if item in entry["owned"]:
        return False, f"⚠️ تملك **{item}** مسبقًا، البسه بـ `.لبس {item}`"
    if get_balance(guild.id, author.id) < info["price"]:
        return False, f"❌ رصيدك ما يكفي (تحتاج {info['price']} نقطة)."
    add_balance(guild.id, author.id, -info["price"])
    entry["owned"].append(item)
    entry[info["slot"]] = item
    save_profile_items(guild.id, author.id, entry)
    return True, f"✅ اشتريت **{item}** وانلبست على بطاقتك! جرّب اكتب `p` في {commands_channel_text(guild)}"


def toggle_profile_item(guild: discord.Guild, author: discord.Member, item: str) -> str:
    """يلبس أو يخلع زينة تملكها (يستخدمها زر المتجر لما تضغط على شي مشتريه)."""
    info = PROFILE_ITEMS[item]
    entry = get_profile_items(guild.id, author.id)
    if entry.get(info["slot"]) == item:
        entry[info["slot"]] = None
        save_profile_items(guild.id, author.id, entry)
        return f"✅ خلعت **{item}**."
    entry[info["slot"]] = item
    save_profile_items(guild.id, author.id, entry)
    return f"✅ لبست **{item}** — جرّب اكتب `p` في {commands_channel_text(guild)}"


# ---------- واجهة المتجر بالأزرار ----------
SHOP_PAGE_SIZE = 4
SHOP_EMBED_COLOR = 0x2ECC71
SHOP_SERVICE_KEY = "services"
SHOP_COLOR_EMOJI = {"احمر": "🔴", "ازرق": "🔵", "اخضر": "🟢", "بنفسجي": "🟣", "ذهبي": "🟡"}


def _shop_cat_items(key: str) -> list[str]:
    for k, _, names in SHOP_CATEGORIES:
        if k == key:
            return names
    return []


class ShopModal(discord.ui.Modal, title="🎭 لقب مؤقت"):
    title_input = discord.ui.TextInput(label="اكتب اللقب اللي تبيه", max_length=20, placeholder="مثال: الملك")

    def __init__(self, shop_view: "ShopView"):
        super().__init__()
        self.shop_view = shop_view

    async def on_submit(self, interaction: discord.Interaction):
        ok, msg = await purchase_title(interaction.guild, interaction.user, str(self.title_input.value))
        await interaction.response.send_message(msg, ephemeral=True)
        await self.shop_view.refresh_message()


class ShopView(discord.ui.View):
    def __init__(self, member: discord.Member, mode: str = "home", cat: str | None = None, page: int = 0):
        super().__init__(timeout=180)
        self.member, self.mode, self.cat, self.page = member, mode, cat, page
        self.message: discord.Message | None = None
        self.build()

    # ----- شكل الرسالة -----
    def embed(self) -> discord.Embed:
        g = self.member.guild
        bal = get_balance(g.id, self.member.id)
        e = discord.Embed(color=SHOP_EMBED_COLOR)
        e.set_author(name=f"متجر {g.name}", icon_url=g.icon.url if g.icon else None)
        if self.mode == "home":
            e.title = "🛍️ المتجر"
            e.description = (f"💰 رصيدك: **{bal}** نقطة\n\nاختر القسم، وبعدها اضغط على المنتج اللي تبيه يتشرى مباشرة.\n"
                             "الزينة تشتريها مرة وحدة وتبقى لك، وتنلبس على بطاقتك (أمر `p`).")
        elif self.mode == "services":
            e.title = "🎭 خدمات مؤقتة"
            e.description = (f"💰 رصيدك: **{bal}** نقطة\n\n"
                             f"• **لقب مؤقت** يضاف لاسمك ({SHOP_TITLE_DURATION_HOURS} ساعة)\n"
                             f"• **لون رول** ({SHOP_COLOR_DURATION_HOURS} ساعة)\n"
                             "• **حذف تنبيه** يشيل أقدم تنبيه مسجل عليك")
        elif self.mode == "colors":
            e.title = "🎨 اختر لونك"
            e.description = f"💰 رصيدك: **{bal}** نقطة\nالسعر: **{SHOP_COLOR_PRICE}** نقطة لمدة {SHOP_COLOR_DURATION_HOURS} ساعة."
        else:
            names = _shop_cat_items(self.cat)
            title = next((t for k, t, _ in SHOP_CATEGORIES if k == self.cat), "المتجر")
            pages = max(1, math.ceil(len(names) / SHOP_PAGE_SIZE))
            e.title = title
            e.description = (f"💰 رصيدك: **{bal}** نقطة\n\nاضغط على المنتج عشان تشتريه.\n"
                             "✅ = تملكه — اضغط عليه يلبسه أو يخلعه.")
            e.set_footer(text=f"صفحة {self.page + 1} / {pages}")
        return e

    def _item_button(self, name: str, row: int) -> discord.ui.Button:
        info = PROFILE_ITEMS[name]
        entry = get_profile_items(self.member.guild.id, self.member.id)
        bal = get_balance(self.member.guild.id, self.member.id)
        if name in entry["owned"]:
            worn = entry.get(info["slot"]) == name
            label = f"{name} — {'ملبوس (اضغط للخلع)' if worn else 'تملكه (اضغط للبس)'}"
            style = discord.ButtonStyle.success
            emoji = "✅"
        else:
            label = f"{name} — {info['price']} نقطة"
            style = discord.ButtonStyle.primary if bal >= info["price"] else discord.ButtonStyle.secondary
            emoji = None
        btn = discord.ui.Button(label=label[:80], style=style, row=row, emoji=emoji)

        async def cb(interaction: discord.Interaction, _n=name):
            await self.on_item(interaction, _n)
        btn.callback = cb
        return btn

    def _btn(self, label, style, row, cb, emoji=None, disabled=False):
        b = discord.ui.Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)
        b.callback = cb
        self.add_item(b)

    def build(self):
        self.clear_items()
        S = discord.ButtonStyle
        if self.mode == "home":
            cats = [(k, t) for k, t, _ in SHOP_CATEGORIES] + [(SHOP_SERVICE_KEY, "🎭 خدمات مؤقتة"), ("bg", "🖼️ خلفية")]
            for i, (k, t) in enumerate(cats):
                async def cb(interaction, _k=k):
                    if _k == "bg":
                        await card_backgrounds.open_backgrounds(interaction, self.member)
                        return
                    await self.go(interaction, "services" if _k == SHOP_SERVICE_KEY else "cat", _k, 0)
                self._btn(t, S.primary, i // 3, cb)
        elif self.mode == "services":
            async def title_cb(interaction):
                await interaction.response.send_modal(ShopModal(self))

            async def color_cb(interaction):
                await self.go(interaction, "colors")

            async def clear_cb(interaction):
                ok, msg = purchase_warn_clear(interaction.guild, interaction.user)
                await interaction.response.edit_message(embed=self.embed(), view=self.rebuilt())
                await interaction.followup.send(msg, ephemeral=True)
            self._btn(f"لقب مؤقت — {SHOP_TITLE_PRICE} نقطة", S.primary, 0, title_cb, "🎭")
            self._btn(f"لون رول — {SHOP_COLOR_PRICE} نقطة", S.primary, 1, color_cb, "🎨")
            self._btn(f"حذف تنبيه — {SHOP_WARN_CLEAR_PRICE} نقطة", S.primary, 2, clear_cb, "🧹")
            self._btn("القائمة الرئيسية", S.secondary, 4, self._home_cb, "🏠")
        elif self.mode == "colors":
            for i, name in enumerate(SHOP_COLOR_ROLES):
                async def cb(interaction, _n=name):
                    ok, msg = await purchase_color(interaction.guild, interaction.user, _n)
                    await interaction.response.edit_message(embed=self.embed(), view=self.rebuilt())
                    await interaction.followup.send(msg, ephemeral=True)
                self._btn(f"{name} — {SHOP_COLOR_PRICE} نقطة", S.secondary, i // 3, cb, SHOP_COLOR_EMOJI.get(name))
            async def back(interaction):
                await self.go(interaction, "services")
            self._btn("رجوع", S.secondary, 4, back, "◀️")
        else:
            names = _shop_cat_items(self.cat)
            pages = max(1, math.ceil(len(names) / SHOP_PAGE_SIZE))
            self.page = max(0, min(self.page, pages - 1))
            chunk = names[self.page * SHOP_PAGE_SIZE:(self.page + 1) * SHOP_PAGE_SIZE]
            for i, n in enumerate(chunk):
                self.add_item(self._item_button(n, i))

            async def prev_cb(interaction):
                await self.go(interaction, "cat", self.cat, self.page - 1)

            async def next_cb(interaction):
                await self.go(interaction, "cat", self.cat, self.page + 1)
            self._btn("السابق", S.secondary, 4, prev_cb, "◀️", disabled=self.page <= 0)
            self._btn("القائمة", S.secondary, 4, self._home_cb, "🏠")
            self._btn("التالي", S.secondary, 4, next_cb, "▶️", disabled=self.page >= pages - 1)

    # ----- تنقل وتحديث -----
    def rebuilt(self) -> "ShopView":
        self.build()
        return self

    async def go(self, interaction: discord.Interaction, mode: str, cat: str | None = None, page: int = 0):
        self.mode, self.page = mode, page
        if cat is not None:
            self.cat = cat
        self.build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _home_cb(self, interaction: discord.Interaction):
        await self.go(interaction, "home")

    async def refresh_message(self):
        if self.message is not None:
            self.build()
            try:
                await self.message.edit(embed=self.embed(), view=self)
            except discord.HTTPException:
                pass

    async def on_item(self, interaction: discord.Interaction, name: str):
        entry = get_profile_items(interaction.guild.id, interaction.user.id)
        if name in entry["owned"]:
            msg = toggle_profile_item(interaction.guild, interaction.user, name)
        else:
            _, msg = purchase_profile_item(interaction.guild, interaction.user, name)
        self.build()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("هذا المتجر مو لك، اكتب `.متجر` تفتح متجرك.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


@bot.command(name="متجر")
async def shop_cmd(ctx: commands.Context):
    view = ShopView(ctx.author)
    view.message = await ctx.send(embed=view.embed(), view=view)


@bot.command(name="شراء")
async def buy_cmd(ctx: commands.Context, item: str = None, *, extra_text: str = None):
    if not item:
        await ctx.send("⚠️ اكتب `.متجر` وتشتري بالأزرار، أو استخدم مثال:\n`.شراء تاج`")
        return
    item = item.strip()
    author = ctx.author
    if item == "لقب":
        if not extra_text or not extra_text.strip():
            await ctx.send("⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`.شراء لقب النص_اللي_تبيه`")
            return
        _, msg = await purchase_title(ctx.guild, author, extra_text)
    elif item == "لون":
        color_name = (extra_text or "").strip()
        if color_name not in SHOP_COLOR_ROLES:
            await ctx.send("⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`.شراء لون احمر`\nالألوان المتوفرة: " + "، ".join(SHOP_COLOR_ROLES))
            return
        _, msg = await purchase_color(ctx.guild, author, color_name)
    elif item == "تنظيف":
        _, msg = purchase_warn_clear(ctx.guild, author)
    else:
        key = resolve_profile_item(f"{item} {extra_text or ''}")
        if key is None:
            await ctx.send("⚠️ ما لقيت هذا العنصر، اكتب `.متجر` عشان تشوف الأشياء المتوفرة.")
            return
        _, msg = purchase_profile_item(ctx.guild, author, key)
    await ctx.send(msg)


@bot.command(name="لبس")
async def wear_cmd(ctx: commands.Context, *, name: str = None):
    if not name or not name.strip():
        await ctx.send("⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`.لبس تاج`")
        return
    name = resolve_profile_item(name)
    if name is None or name not in PROFILE_ITEMS:
        await ctx.send("⚠️ ما فيه عنصر بهذا الاسم، اكتب `.متجر` تشوف الزينة المتوفرة.")
        return
    entry = get_profile_items(ctx.guild.id, ctx.author.id)
    if name not in entry["owned"]:
        await ctx.send(f"❌ ما تملك **{name}** — اشتره أول بـ `.شراء {name}`")
        return
    info = PROFILE_ITEMS[name]
    entry[info["slot"]] = name
    save_profile_items(ctx.guild.id, ctx.author.id, entry)
    await ctx.send(f"✅ لبست **{name}** — جرّب اكتب `p` في {commands_channel_text(ctx.guild)}")


@bot.command(name="خلع")
async def unwear_cmd(ctx: commands.Context):
    entry = get_profile_items(ctx.guild.id, ctx.author.id)
    entry["head"] = None
    entry["face"] = None
    entry["mouth"] = None
    entry["ears"] = None
    save_profile_items(ctx.guild.id, ctx.author.id, entry)
    await ctx.send("✅ خلعت كل الزينة (تقدر تلبسها مرة ثانية بـ `.لبس`).")


@tasks.loop(minutes=5)
async def shop_expiry_task():
    data = load_json(SHOP_ACTIVE_FILE)
    now = datetime.now(timezone.utc)
    changed = False
    for gid, users in list(data.items()):
        guild = bot.get_guild(int(gid))
        if guild is None:
            continue
        for uid, entry in list(users.items()):
            try:
                expires = datetime.fromisoformat(entry["expires"])
            except (KeyError, ValueError):
                del data[gid][uid]
                changed = True
                continue
            if now < expires:
                continue
            member = guild.get_member(int(uid))
            if member is not None:
                try:
                    if entry.get("type") == "title":
                        await member.edit(nick=entry.get("original_nick"), reason="انتهت مدة اللقب المؤقت")
                    elif entry.get("type") == "color":
                        role = guild.get_role(entry.get("role_id"))
                        if role and role in member.roles:
                            await member.remove_roles(role, reason="انتهت مدة لون المتجر")
                except discord.Forbidden:
                    pass
            del data[gid][uid]
            changed = True
    if changed:
        save_json(SHOP_ACTIVE_FILE, data)


# ============================================================
# 12.4) بطاقة البروفايل (أمر p) — رسم الصورة
# ============================================================
# اسم ملف الصورة (القالب) — حطه جنب ملف البوت بهذا الاسم بالضبط
PROFILE_BG_PATH = "Dai.png"

# مواقع العناصر على القالب (القالب 1060 × 1484)
PROFILE_CIRCLE_CENTER = (861, 875)
PROFILE_CIRCLE_RADIUS = 163
PROFILE_LEFT_BOX = (32, 1143, 520, 1398)     # البنك
PROFILE_RIGHT_BOX = (540, 1143, 1028, 1398)  # النقاط

PROFILE_FONT_CANDIDATES = [
    "font.ttf",
    "arial.ttf", "Arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

BANK_FILE_GUESSES = ["bank.json", "bank_data.json", "bank_accounts.json"]


def get_bank_money(guild_id: int, user_id: int) -> int:
    """يجيب فلوس العضو بالبنك. يجرب دوال شائعة داخل bank.py، وإذا ما لقى يقرأ ملف json للبنك."""
    for fn_name in ("get_bank_balance", "get_bank_money", "get_bank", "get_account_balance",
                    "get_balance", "get_money"):
        fn = getattr(bank, fn_name, None)
        if callable(fn):
            try:
                value = fn(guild_id, user_id)
                if asyncio.iscoroutine(value):
                    value.close()
                    continue
                return int(value)
            except Exception:
                continue
    for path in BANK_FILE_GUESSES:
        data = load_json(path)
        entry = data.get(str(guild_id), {}).get(str(user_id))
        if isinstance(entry, (int, float)):
            return int(entry)
        if isinstance(entry, dict):
            for key in ("balance", "bank", "money", "amount"):
                if isinstance(entry.get(key), (int, float)):
                    return int(entry[key])
    return 0


def _load_font(size: int):
    """يحمّل الخط بمحرك BASIC عشان Pillow ما يسوي معالجة اتجاه النص بنفسه
    (لو raqm مفعّل كان يقلب النص مرتين مع arabic_reshaper + bidi فيطلع مقلوب)."""
    try:
        basic = ImageFont.Layout.BASIC
    except AttributeError:
        basic = getattr(ImageFont, "LAYOUT_BASIC", None)
    for path in PROFILE_FONT_CANDIDATES:
        try:
            if basic is not None:
                return ImageFont.truetype(path, size, layout_engine=basic)
            return ImageFont.truetype(path, size)
        except OSError:
            continue
        except TypeError:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


_ARABIC_CHARS = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def _shape(text: str) -> str:
    """يوصّل الحروف العربية ويعدل الاتجاه. النص الإنجليزي/الأرقام ما نلمسها أبدًا (عشان ما تنقلب)."""
    if not text or not ARABIC_SHAPING_OK or not _ARABIC_CHARS.search(text):
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _fit_font(draw, text: str, max_width: int, start_size: int, min_size: int = 20):
    size = start_size
    while size > min_size:
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _load_font(min_size)


def _circle_avatar(avatar_bytes: bytes, diameter: int):
    av = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((diameter, diameter), Image.LANCZOS)
    big = diameter * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    mask = mask.resize((diameter, diameter), Image.LANCZOS)
    av.putalpha(mask)
    return av


# ---------- رسم الزينة (واقعية بتدرجات وظلال، وتنرسم مايلة) ----------
class _Canvas:
    """لوحة رسم للزينة: الإحداثيات بوحدة نصف قطر الصورة (u أفقي، v عمودي، 0,0 = مركز الصورة)."""

    def __init__(self, r: int, k: int = 2):
        self.r, self.k = r, k
        self.half = int(r * 2.0)
        self.side = self.half * 2
        self.size = self.side * k
        self.img = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        self.c = self.size / 2

    def P(self, u, v):
        return (self.c + u * self.r * self.k, self.c + v * self.r * self.k)

    def w(self, f):
        return max(1, int(f * self.r * self.k))

    def draw(self):
        return ImageDraw.Draw(self.img, "RGBA")

    def _fill(self, bbox, mask_fn, c1, c2=None, horizontal=False):
        x0, y0, x1, y1 = [int(v) for v in bbox]
        x0, y0 = max(0, x0 - 1), max(0, y0 - 1)
        x1, y1 = min(self.size, x1 + 2), min(self.size, y1 + 2)
        w, h = x1 - x0, y1 - y0
        if w < 2 or h < 2:
            return
        c2 = c2 or c1
        grad = Image.new("RGBA", (w, h))
        gd = ImageDraw.Draw(grad)
        n = w if horizontal else h
        for i in range(n):
            t = i / max(1, n - 1)
            col = tuple(int(c1[j] + (c2[j] - c1[j]) * t) for j in range(4))
            gd.line([(i, 0), (i, h)] if horizontal else [(0, i), (w, i)], fill=col)
        mask = Image.new("L", (w, h), 0)
        mask_fn(ImageDraw.Draw(mask), x0, y0)
        grad.putalpha(mask)
        self.img.alpha_composite(grad, (x0, y0))

    def poly(self, pts, c1, c2=None, outline=None, ow=0.025, horizontal=False):
        pp = [self.P(*p) for p in pts]
        xs, ys = [p[0] for p in pp], [p[1] for p in pp]
        self._fill((min(xs), min(ys), max(xs), max(ys)),
                   lambda d, x0, y0: d.polygon([(x - x0, y - y0) for x, y in pp], fill=255), c1, c2, horizontal)
        if outline:
            self.draw().line(pp + [pp[0]], fill=outline, width=self.w(ow), joint="curve")

    def shape(self, kind, u1, v1, u2, v2, c1, c2=None, outline=None, ow=0.025,
              horizontal=False, start=0, end=360, rad=0.05):
        (x1, y1), (x2, y2) = self.P(u1, v1), self.P(u2, v2)

        def mk(d, x0, y0):
            b = [x1 - x0, y1 - y0, x2 - x0, y2 - y0]
            if kind == "ellipse":
                d.ellipse(b, fill=255)
            elif kind == "rrect":
                d.rounded_rectangle(b, radius=self.w(rad), fill=255)
            elif kind == "pie":
                d.pieslice(b, start, end, fill=255)
            elif kind == "chord":
                d.chord(b, start, end, fill=255)

        self._fill((x1, y1, x2, y2), mk, c1, c2, horizontal)
        if outline:
            d, b, wd = self.draw(), [x1, y1, x2, y2], self.w(ow)
            if kind == "ellipse":
                d.ellipse(b, outline=outline, width=wd)
            elif kind == "rrect":
                d.rounded_rectangle(b, radius=self.w(rad), outline=outline, width=wd)
            else:
                d.arc(b, start, end, fill=outline, width=wd)

    def circ(self, u, v, rad, c1, c2=None, outline=None, ow=0.02):
        self.shape("ellipse", u - rad, v - rad, u + rad, v + rad, c1, c2, outline, ow)

    def line(self, pts, color, width):
        self.draw().line([self.P(*p) for p in pts], fill=color, width=self.w(width), joint="curve")

    def shine(self, u1, v1, u2, v2, alpha=110):
        """لمعة بيضاء شفافة (بيضاوية صغيرة) تعطي إحساس المعدن/اللمعان."""
        (x1, y1), (x2, y2) = self.P(u1, v1), self.P(u2, v2)
        self.draw().ellipse([x1, y1, x2, y2], fill=(255, 255, 255, alpha))

    def finish(self):
        return self.img.resize((self.side, self.side), Image.LANCZOS)


def _star_pts(cx, cy, R, n=5):
    pts = []
    for i in range(n * 2):
        ang = -math.pi / 2 + i * math.pi / n
        rr = R if i % 2 == 0 else R * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return pts


GOLD_L, GOLD_D, GOLD_X = (255, 232, 130, 255), (196, 134, 14, 255), (120, 76, 6, 255)


def _acc_crown(c):
    pts = [(-0.66, -0.78), (-0.76, -1.60), (-0.36, -1.20), (0, -1.80), (0.36, -1.20), (0.76, -1.60), (0.66, -0.78)]
    c.poly(pts, GOLD_L, GOLD_D, outline=GOLD_X, ow=0.03)
    c.poly([(-0.30, -1.18), (0, -1.78), (0.30, -1.18), (0, -0.95)], (255, 244, 180, 255), (230, 170, 40, 255))
    c.shape("rrect", -0.70, -1.02, 0.70, -0.76, GOLD_L, GOLD_D, outline=GOLD_X, ow=0.03, rad=0.06)
    for u in (-0.42, -0.14, 0.14, 0.42):
        c.circ(u, -0.89, 0.045, (255, 255, 255, 255), (210, 220, 235, 255))
    c.circ(-0.76, -1.60, 0.085, (255, 120, 140, 255), (190, 20, 50, 255), outline=GOLD_X)
    c.circ(0, -1.80, 0.10, (150, 200, 255, 255), (30, 90, 210, 255), outline=GOLD_X)
    c.circ(0.76, -1.60, 0.085, (255, 120, 140, 255), (190, 20, 50, 255), outline=GOLD_X)
    c.shine(-0.52, -1.0, -0.2, -0.93, 150)


def _acc_tophat(c):
    c.shape("ellipse", -1.0, -1.0, 1.0, -0.70, (58, 58, 66, 255), (10, 10, 12, 255), outline=(0, 0, 0, 255))
    c.shape("rrect", -0.56, -1.86, 0.0, -0.86, (14, 14, 18, 255), (74, 74, 86, 255), horizontal=True, rad=0.0)
    c.shape("rrect", 0.0, -1.86, 0.56, -0.86, (74, 74, 86, 255), (14, 14, 18, 255), horizontal=True, rad=0.0)
    c.shape("ellipse", -0.56, -1.96, 0.56, -1.74, (104, 104, 116, 255), (46, 46, 54, 255), outline=(0, 0, 0, 255))
    c.shape("rrect", -0.56, -1.17, 0.56, -0.96, (200, 40, 55, 255), (120, 14, 26, 255), rad=0.0)
    c.shape("rrect", -0.12, -1.20, 0.12, -0.93, (255, 226, 120, 255), (190, 130, 14, 255), outline=GOLD_X, ow=0.015, rad=0.02)
    c.line([(-0.40, -1.74), (-0.40, -1.25)], (255, 255, 255, 60), 0.04)


def _acc_cap(c):
    c.shape("pie", -0.90, -1.52, 0.90, -0.46, (70, 160, 225, 255), (24, 84, 150, 255), outline=(16, 60, 110, 255),
            start=180, end=360)
    c.line([(0, -1.5), (0, -0.96)], (16, 60, 110, 255), 0.02)
    c.line([(-0.5, -1.4), (-0.35, -0.96)], (16, 60, 110, 255), 0.02)
    c.line([(0.5, -1.4), (0.35, -0.96)], (16, 60, 110, 255), 0.02)
    c.shape("rrect", -0.90, -1.0, 0.90, -0.90, (36, 110, 175, 255), (18, 70, 120, 255), rad=0.03)
    c.shape("ellipse", 0.05, -1.02, 1.40, -0.78, (36, 110, 175, 255), (14, 62, 108, 255), outline=(10, 44, 80, 255))
    c.circ(0, -1.52, 0.06, (36, 110, 175, 255), (14, 62, 108, 255))
    c.shine(-0.55, -1.38, -0.2, -1.2, 90)


def _acc_halo(c):
    box = (-0.64, -1.66, 0.64, -1.24)
    d = c.draw()
    (x1, y1), (x2, y2) = c.P(box[0], box[1]), c.P(box[2], box[3])
    for wd, a in ((0.22, 36), (0.16, 64), (0.11, 100)):
        d.ellipse([x1, y1, x2, y2], outline=(255, 232, 120, a), width=c.w(wd))
    d.ellipse([x1, y1, x2, y2], outline=(255, 206, 60, 255), width=c.w(0.065))
    d.ellipse([x1, y1, x2, y2], outline=(255, 246, 190, 255), width=c.w(0.022))


def _acc_cowboy(c):
    c.poly([(-0.56, -0.86), (-0.52, -1.55), (-0.30, -1.66), (0, -1.46), (0.30, -1.66), (0.52, -1.55), (0.56, -0.86)],
           (190, 134, 74, 255), (126, 80, 38, 255), outline=(70, 40, 18, 255), ow=0.03)
    c.shape("ellipse", -1.22, -1.04, 1.22, -0.62, (206, 152, 88, 255), (118, 74, 34, 255), outline=(70, 40, 18, 255), ow=0.03)
    c.poly([(-0.56, -0.86), (-0.55, -1.12), (0.55, -1.12), (0.56, -0.86)], (96, 58, 28, 255), (58, 32, 14, 255))
    c.shape("rrect", -0.12, -1.10, 0.12, -0.88, (255, 226, 120, 255), (190, 130, 14, 255), outline=GOLD_X, ow=0.015, rad=0.02)
    c.line([(0, -1.46), (0, -1.14)], (70, 40, 18, 160), 0.03)
    c.line([(-1.18, -0.86), (-1.0, -1.0)], (70, 40, 18, 200), 0.03)
    c.line([(1.18, -0.86), (1.0, -1.0)], (70, 40, 18, 200), 0.03)


def _acc_wizard(c):
    c.shape("ellipse", -1.02, -1.0, 1.02, -0.70, (96, 56, 160, 255), (48, 24, 96, 255), outline=(30, 14, 64, 255))
    c.poly([(-0.64, -0.86), (-0.14, -1.60), (0.44, -1.94), (0.22, -1.52), (0.64, -0.86)],
           (140, 92, 214, 255), (60, 30, 122, 255), outline=(30, 14, 64, 255), ow=0.03)
    c.shape("rrect", -0.64, -1.04, 0.64, -0.86, (255, 226, 120, 255), (190, 130, 14, 255), outline=GOLD_X, ow=0.015, rad=0.02)
    for (u, v, R) in ((-0.05, -1.26, 0.10), (0.20, -1.55, 0.075), (0.30, -1.14, 0.06)):
        c.poly(_star_pts(u, v, R), (255, 240, 150, 255), (240, 190, 40, 255))


def _acc_chef(c):
    w1, w2, ol = (255, 255, 255, 255), (214, 220, 230, 255), (176, 184, 198, 255)
    for (u, v, R) in ((-0.48, -1.42, 0.38), (0.48, -1.42, 0.38), (0, -1.66, 0.46), (-0.2, -1.3, 0.44), (0.2, -1.3, 0.44)):
        c.circ(u, v, R, w1, w2, outline=ol, ow=0.015)
    c.shape("rrect", -0.62, -1.14, 0.62, -0.78, w1, w2, outline=ol, ow=0.02, rad=0.05)
    for u in (-0.3, 0, 0.3):
        c.line([(u, -1.1), (u, -0.82)], (190, 196, 210, 255), 0.015)


def _acc_viking(c):
    for sgn in (-1, 1):
        pts = [(sgn * u, v) for u, v in [(0.70, -0.92), (1.02, -0.98), (1.25, -1.18), (1.28, -1.45),
                                          (1.15, -1.52), (1.12, -1.30), (0.95, -1.15), (0.74, -1.16)]]
        c.poly(pts, (252, 246, 228, 255), (176, 158, 124, 255), outline=(92, 78, 54, 255), ow=0.025)
    c.shape("pie", -0.84, -1.52, 0.84, -0.46, (206, 214, 224, 255), (92, 100, 114, 255), outline=(50, 56, 66, 255),
            start=180, end=360)
    c.shape("rrect", -0.84, -1.02, 0.84, -0.88, (130, 138, 150, 255), (70, 76, 88, 255), outline=(50, 56, 66, 255), ow=0.02, rad=0.03)
    for u in (-0.6, -0.3, 0, 0.3, 0.6):
        c.circ(u, -0.95, 0.03, (240, 244, 250, 255), (150, 156, 168, 255))
    c.shine(-0.5, -1.4, -0.2, -1.22, 120)


def _acc_horns(c):
    for sgn in (-1, 1):
        pts = [(sgn * u, v) for u, v in [(0.80, -0.85), (0.52, -0.92), (0.40, -1.25), (0.30, -1.70), (0.62, -1.45), (0.82, -1.15)]]
        c.poly(pts, (240, 70, 70, 255), (112, 8, 18, 255), outline=(60, 0, 8, 255), ow=0.025)
        c.line([(sgn * 0.62, -1.0), (sgn * 0.46, -1.45)], (255, 190, 190, 120), 0.025)


def _acc_santa(c):
    c.poly([(-0.76, -0.88), (-0.72, -1.34), (-0.34, -1.72), (0.50, -1.78), (0.96, -1.46), (0.80, -1.20), (0.72, -0.88)],
           (240, 60, 70, 255), (146, 12, 24, 255), outline=(96, 6, 14, 255), ow=0.03)
    c.circ(0.92, -1.40, 0.17, (255, 255, 255, 255), (214, 220, 230, 255), outline=(176, 184, 198, 255), ow=0.015)
    c.shape("rrect", -0.84, -1.10, 0.84, -0.78, (255, 255, 255, 255), (214, 220, 230, 255), outline=(176, 184, 198, 255), ow=0.02, rad=0.14)
    for u in (-0.6, -0.2, 0.2, 0.6):
        c.circ(u, -0.94, 0.07, (255, 255, 255, 255), (222, 228, 238, 255))


def _acc_beret(c):
    c.shape("ellipse", -0.96, -1.46, 0.86, -0.80, (176, 30, 48, 255), (88, 8, 20, 255), outline=(60, 4, 12, 255), ow=0.03)
    c.shape("ellipse", -0.60, -1.40, -0.1, -1.18, (210, 70, 86, 255), (150, 24, 40, 255))
    c.shape("rrect", -0.04, -1.58, 0.1, -1.42, (96, 8, 20, 255), (60, 4, 12, 255), rad=0.03)


def _acc_ghutra(c):
    c.shape("chord", -1.14, -1.14, 1.14, 1.14, (255, 255, 255, 255), (222, 226, 234, 255),
            outline=(170, 176, 190, 255), ow=0.03, start=205, end=335)
    # مربعات الغترة الحمراء
    (x1, y1), (x2, y2) = c.P(-1.14, -1.14), c.P(1.14, 1.14)
    chord = Image.new("L", (c.size, c.size), 0)
    ImageDraw.Draw(chord).chord([x1, y1, x2, y2], 205, 335, fill=255)
    lines = Image.new("L", (c.size, c.size), 0)
    ld = ImageDraw.Draw(lines)
    step, wd = int(0.17 * c.r * c.k), c.w(0.035)
    for i in range(0, c.size, step):
        ld.line([(i, 0), (i, c.size)], fill=255, width=wd)
        ld.line([(0, i), (c.size, i)], fill=255, width=wd)
    solid = Image.new("RGBA", (c.size, c.size), (200, 30, 40, 255))
    solid.putalpha(ImageChops.multiply(chord, lines))
    c.img.alpha_composite(solid)
    d = c.draw()
    for off, wd2 in ((0, 0.10), (0.13, 0.08)):
        (a1, b1), (a2, b2) = c.P(-0.94, -1.12 + off), c.P(0.94, -0.72 + off)
        d.ellipse([a1, b1, a2, b2], outline=(18, 18, 20, 255), width=c.w(wd2))


def _acc_glasses(c):
    for (u1, u2) in ((-0.90, -0.06), (0.06, 0.90)):
        c.shape("rrect", u1, -0.30, u2, 0.20, (52, 58, 70, 255), (8, 10, 14, 255), outline=(14, 14, 18, 255), ow=0.05, rad=0.14)
    c.line([(-0.06, -0.12), (0.06, -0.12)], (14, 14, 18, 255), 0.06)
    c.line([(-0.90, -0.15), (-1.02, -0.2)], (14, 14, 18, 255), 0.05)
    c.line([(0.90, -0.15), (1.02, -0.2)], (14, 14, 18, 255), 0.05)
    c.line([(-0.74, -0.2), (-0.5, -0.2)], (255, 255, 255, 120), 0.03)
    c.line([(0.22, -0.2), (0.46, -0.2)], (255, 255, 255, 120), 0.03)


def _acc_aviator(c):
    for (u1, u2) in ((-0.92, -0.06), (0.06, 0.92)):
        c.shape("ellipse", u1, -0.28, u2, 0.34, (120, 96, 40, 255), (14, 12, 8, 255), outline=(222, 176, 52, 255), ow=0.045)
    c.line([(-0.06, -0.14), (0.06, -0.14)], (222, 176, 52, 255), 0.05)
    c.line([(-0.92, -0.14), (-1.04, -0.2)], (222, 176, 52, 255), 0.04)
    c.line([(0.92, -0.14), (1.04, -0.2)], (222, 176, 52, 255), 0.04)
    c.shine(-0.74, -0.16, -0.5, -0.06, 110)
    c.shine(0.22, -0.16, 0.46, -0.06, 110)


def _acc_hearts(c):
    for cx in (-0.48, 0.48):
        cy = -0.10
        for sg in (-1, 1):
            c.circ(cx + sg * 0.2, cy - 0.06, 0.23, (255, 130, 170, 255), (200, 20, 70, 255))
        c.poly([(cx - 0.42, cy), (cx + 0.42, cy), (cx, cy + 0.46)], (240, 70, 120, 255), (190, 14, 60, 255))
        c.shine(cx - 0.34, cy - 0.20, cx - 0.12, cy - 0.10, 150)
    c.line([(-0.08, -0.14), (0.08, -0.14)], (150, 10, 50, 255), 0.05)


def _acc_mustache(c):
    for sgn in (-1, 1):
        pts = [(sgn * u, v) for u, v in [(0, 0.40), (0.18, 0.33), (0.45, 0.35), (0.72, 0.50), (0.64, 0.60),
                                          (0.42, 0.52), (0.18, 0.52), (0, 0.54)]]
        c.poly(pts, (74, 44, 24, 255), (20, 10, 4, 255), outline=(12, 6, 2, 255), ow=0.015)


# ---------- زينة إضافية ----------
def _ell_pts(cx, cy, a, b, ang=0.0, n=48):
    """نقاط بيضاوي مايل (للأوراق والآذان)."""
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = a * math.cos(t), b * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def _hole(c, u1, v1, u2, v2):
    """يفرّغ بيضاوي من الرسم (شفاف) — مثل فتحات العيون بالقناع."""
    (x1, y1), (x2, y2) = c.P(u1, v1), c.P(u2, v2)
    ImageDraw.Draw(c.img).ellipse([x1, y1, x2, y2], fill=(0, 0, 0, 0))


def _acc_straw(c):
    s1, s2, sx = (246, 218, 136, 255), (184, 142, 66, 255), (110, 78, 28, 255)
    c.shape("ellipse", -1.32, -1.06, 1.32, -0.58, s1, s2, outline=sx, ow=0.03)
    c.shape("pie", -0.64, -1.62, 0.64, -0.02, s1, s2, outline=sx, ow=0.03, start=180, end=360)
    for v in (-1.46, -1.32, -1.18):
        c.line([(-0.5, v), (0.5, v)], (110, 78, 28, 60), 0.015)
    c.shape("rrect", -0.64, -0.98, 0.64, -0.80, (214, 52, 64, 255), (140, 18, 30, 255), rad=0.02)
    c.line([(-1.0, -0.82), (-0.6, -0.72)], (110, 78, 28, 70), 0.02)
    c.line([(1.0, -0.82), (0.6, -0.72)], (110, 78, 28, 70), 0.02)


def _acc_party(c):
    c.poly([(-0.54, -0.84), (0.0, -1.86), (0.54, -0.84)], (255, 110, 190, 255), (96, 60, 224, 255),
           outline=(60, 30, 140, 255), ow=0.03, horizontal=True)
    for v in (-1.0, -1.28, -1.56):
        hw = 0.54 * (v + 1.86) / 1.02
        c.line([(-hw, v), (hw, v - 0.09)], (255, 232, 90, 255), 0.05)
    for (u, v) in ((-0.1, -1.15), (0.12, -1.42), (-0.05, -1.7), (0.25, -0.98)):
        c.circ(u, v, 0.03, (255, 255, 255, 255))
    c.shape("rrect", -0.58, -0.94, 0.58, -0.78, (255, 226, 120, 255), (200, 140, 20, 255), outline=GOLD_X, ow=0.012, rad=0.05)
    c.circ(0, -1.9, 0.1, (255, 240, 130, 255), (240, 170, 20, 255), outline=GOLD_X, ow=0.012)


def _acc_grad(c):
    c.shape("rrect", -0.56, -1.22, 0.56, -0.74, (50, 54, 72, 255), (14, 16, 26, 255), outline=(6, 6, 12, 255), ow=0.025, rad=0.1)
    c.poly([(-1.12, -1.18), (0.0, -1.58), (1.12, -1.18), (0.0, -0.84)], (74, 80, 104, 255), (16, 18, 28, 255),
           outline=(6, 6, 12, 255), ow=0.03)
    c.poly([(-0.9, -1.18), (0.0, -1.48), (0.9, -1.18), (0.0, -0.96)], (120, 128, 160, 70), (30, 34, 50, 40))
    c.line([(0, -1.2), (0.84, -1.1), (0.88, -0.66)], (236, 190, 60, 255), 0.035)
    for du in (-0.035, 0, 0.035):
        c.line([(0.88 + du, -0.72), (0.88 + du * 1.6, -0.46)], (230, 180, 40, 255), 0.022)
    c.shape("rrect", 0.82, -0.76, 0.94, -0.64, GOLD_L, GOLD_D, outline=GOLD_X, ow=0.012, rad=0.03)
    c.circ(0, -1.2, 0.07, GOLD_L, GOLD_D, outline=GOLD_X, ow=0.012)


def _acc_pirate(c):
    c.line([(-0.30, -0.88), (0.30, -1.18)], (235, 235, 240, 255), 0.05)
    c.line([(0.30, -0.88), (-0.30, -1.18)], (235, 235, 240, 255), 0.05)
    c.poly([(-1.28, -0.76), (-1.02, -1.28), (-0.5, -1.50), (0, -1.32), (0.5, -1.50), (1.02, -1.28), (1.28, -0.76),
            (0.72, -0.66), (0, -0.86), (-0.72, -0.66)], (70, 70, 84, 255), (10, 10, 14, 255),
           outline=(214, 170, 50, 255), ow=0.04)
    c.line([(-0.30, -0.88), (0.30, -1.18)], (235, 235, 240, 255), 0.05)
    c.line([(0.30, -0.88), (-0.30, -1.18)], (235, 235, 240, 255), 0.05)
    c.circ(0, -1.08, 0.17, (255, 255, 255, 255), (206, 212, 226, 255), outline=(110, 116, 130, 255), ow=0.012)
    c.circ(-0.065, -1.10, 0.04, (20, 20, 24, 255))
    c.circ(0.065, -1.10, 0.04, (20, 20, 24, 255))
    c.shape("rrect", -0.07, -0.99, 0.07, -0.94, (20, 20, 24, 255), (20, 20, 24, 255), rad=0.01)
    c.circ(0.98, -0.96, 0.06, GOLD_L, GOLD_D, outline=GOLD_X, ow=0.01)


def _acc_beanie(c):
    c.shape("pie", -0.86, -1.74, 0.86, -0.18, (230, 66, 66, 255), (118, 14, 26, 255), outline=(70, 8, 16, 255), ow=0.03,
            start=180, end=360)
    for u in (-0.6, -0.36, -0.12, 0.12, 0.36, 0.6):
        c.line([(u, -1.04), (u * 0.5, -1.66)], (80, 6, 16, 90), 0.02)
    c.shape("rrect", -0.92, -1.08, 0.92, -0.78, (250, 250, 252, 255), (196, 202, 218, 255), outline=(150, 156, 172, 255), ow=0.02, rad=0.08)
    for u in (-0.75, -0.55, -0.35, -0.15, 0.05, 0.25, 0.45, 0.65, 0.82):
        c.line([(u, -1.04), (u, -0.82)], (170, 176, 192, 255), 0.018)
    c.circ(0, -1.76, 0.2, (255, 255, 255, 255), (206, 212, 226, 255), outline=(150, 156, 172, 255), ow=0.015)
    for k in range(8):
        a = k * math.pi / 4
        c.circ(0.14 * math.cos(a), -1.76 + 0.14 * math.sin(a), 0.07, (255, 255, 255, 255), (226, 230, 240, 255))


def _acc_cat(c):
    for s in (-1, 1):
        c.poly([(s * 0.84, -0.60), (s * 0.82, -1.64), (s * 0.20, -0.98)], (118, 118, 130, 255), (34, 34, 42, 255),
               outline=(14, 14, 18, 255), ow=0.03)
        c.poly([(s * 0.72, -0.86), (s * 0.70, -1.36), (s * 0.38, -1.02)], (255, 176, 196, 255), (222, 92, 134, 255))


def _acc_bunny(c):
    for s in (-1, 1):
        c.poly(_ell_pts(s * 0.42, -1.5, 0.2, 0.52, s * 10), (255, 255, 255, 255), (222, 226, 238, 255),
               outline=(168, 174, 190, 255), ow=0.025)
        c.poly(_ell_pts(s * 0.42 + s * 0.01, -1.46, 0.1, 0.38, s * 10), (255, 196, 212, 255), (232, 120, 156, 255))


def _acc_flowers(c):
    for t in range(-82, 83, 7):
        a = math.radians(t)
        u, v = 1.02 * math.sin(a), -1.02 * math.cos(a)
        c.poly(_ell_pts(u, v, 0.15, 0.06, t, 24), (120, 190, 70, 255), (40, 110, 36, 255))
    pal = [((255, 160, 190, 255), (224, 70, 120, 255)), ((255, 255, 255, 255), (226, 230, 240, 255)),
           ((200, 160, 250, 255), (130, 90, 204, 255)), ((255, 190, 100, 255), (232, 120, 30, 255))]
    for i, t in enumerate(range(-68, 69, 23)):
        a = math.radians(t)
        u, v = 1.02 * math.sin(a), -1.02 * math.cos(a)
        p1, p2 = pal[i % len(pal)]
        for k in range(5):
            ang = 2 * math.pi * k / 5 - math.pi / 2
            c.circ(u + 0.11 * math.cos(ang), v + 0.11 * math.sin(ang), 0.1, p1, p2, outline=(0, 0, 0, 40), ow=0.008)
        c.circ(u, v, 0.07, (255, 230, 90, 255), (230, 160, 20, 255))


def _acc_laurel(c):
    for t in range(-84, 85, 9):
        if abs(t) < 5:
            continue
        sgn = -1 if t < 0 else 1
        a = math.radians(t)
        for off, rad in ((30, 1.12), (-30, 1.0)):
            ang = t + sgn * off
            u, v = rad * math.sin(a), -rad * math.cos(a)
            c.poly(_ell_pts(u, v, 0.17, 0.065, ang, 24), (150, 210, 80, 255), (44, 116, 40, 255),
                   outline=(30, 80, 26, 255), ow=0.008)
    for t in (-82, 82):
        a = math.radians(t)
        c.circ(1.05 * math.sin(a), -1.05 * math.cos(a), 0.05, (230, 60, 60, 255), (150, 14, 20, 255))


def _acc_diamond_crown(c):
    L, D, X = (240, 250, 255, 255), (118, 160, 214, 255), (46, 76, 128, 255)
    pts = [(-0.68, -0.78), (-0.80, -1.66), (-0.38, -1.22), (0, -1.88), (0.38, -1.22), (0.80, -1.66), (0.68, -0.78)]
    c.poly(pts, L, D, outline=X, ow=0.03)
    c.poly([(-0.30, -1.2), (0, -1.84), (0.30, -1.2), (0, -0.95)], (200, 240, 255, 255), (90, 170, 235, 255))
    c.shape("rrect", -0.72, -1.04, 0.72, -0.76, L, D, outline=X, ow=0.03, rad=0.06)
    for u in (-0.44, -0.15, 0.15, 0.44):
        c.poly([(u - 0.07, -0.9), (u, -1.0), (u + 0.07, -0.9), (u, -0.8)], (210, 250, 255, 255), (40, 170, 230, 255),
               outline=X, ow=0.008)
    for (u, v) in ((-0.80, -1.66), (0.80, -1.66)):
        c.poly([(u - 0.1, v), (u, v - 0.12), (u + 0.1, v), (u, v + 0.12)], (230, 255, 255, 255), (60, 190, 240, 255), outline=X, ow=0.01)
    c.poly([(-0.14, -1.88), (0, -2.0), (0.14, -1.88), (0, -1.72)], (255, 255, 255, 255), (80, 200, 255, 255), outline=X, ow=0.01)
    c.shine(-0.55, -1.0, -0.2, -0.93, 170)


# ----- سماعات الراس -----
def _phones_band(c, outer, hi, rad=1.1, w=0.13):
    d = c.draw()
    (x1, y1), (x2, y2) = c.P(-rad, -rad), c.P(rad, rad)
    d.arc([x1, y1, x2, y2], 180, 360, fill=outer, width=c.w(w))
    (a1, b1), (a2, b2) = c.P(-rad + 0.015, -rad + 0.015), c.P(rad - 0.015, rad - 0.015)
    d.arc([a1, b1, a2, b2], 182, 358, fill=hi, width=c.w(0.03))


def _acc_phones(c):
    _phones_band(c, (26, 26, 32, 255), (110, 112, 126, 255))
    for s in (-1, 1):
        u1, u2 = sorted((s * 0.90, s * 1.34))
        c.shape("rrect", u1, -0.46, u2, 0.46, (84, 86, 100, 255), (14, 14, 18, 255), outline=(4, 4, 6, 255), ow=0.03,
                rad=0.17, horizontal=(s == -1))
        ui1, ui2 = sorted((s * 0.86, s * 0.98))
        c.shape("rrect", ui1, -0.34, ui2, 0.36, (52, 52, 60, 255), (20, 20, 26, 255), rad=0.05)
        c.circ(s * 1.17, 0.0, 0.13, (240, 70, 80, 255), (140, 14, 26, 255), outline=(4, 4, 6, 255), ow=0.012)
        c.shine(s * 1.18 - 0.05, -0.38, s * 1.18 + 0.05, -0.14, 100)


def _acc_gaming(c):
    _phones_band(c, (22, 24, 34, 255), (60, 220, 255, 255), w=0.14)
    d = c.draw()
    for s, col in ((-1, (60, 230, 255)), (1, (255, 70, 210))):
        u1, u2 = sorted((s * 0.90, s * 1.36))
        c.shape("rrect", u1, -0.5, u2, 0.5, (60, 64, 84, 255), (10, 12, 20, 255), outline=(2, 2, 6, 255), ow=0.03,
                rad=0.16, horizontal=(s == -1))
        ui1, ui2 = sorted((s * 0.86, s * 0.98))
        c.shape("rrect", ui1, -0.36, ui2, 0.38, (46, 48, 62, 255), (18, 18, 26, 255), rad=0.05)
        (x1, y1), (x2, y2) = c.P(s * 1.13 - 0.2, -0.2), c.P(s * 1.13 + 0.2, 0.2)
        for wd, al in ((0.10, 50), (0.06, 110)):
            d.ellipse([x1, y1, x2, y2], outline=col + (al,), width=c.w(wd))
        d.ellipse([x1, y1, x2, y2], outline=col + (255,), width=c.w(0.03))
        c.circ(s * 1.13, 0, 0.08, col + (255,), tuple(int(v * 0.5) for v in col) + (255,))
    c.line([(-1.2, 0.46), (-1.12, 0.78), (-0.78, 0.94), (-0.46, 0.9)], (30, 32, 44, 255), 0.07)
    c.line([(-1.2, 0.46), (-1.12, 0.78), (-0.78, 0.94), (-0.46, 0.9)], (120, 126, 150, 255), 0.02)
    c.shape("ellipse", -0.58, 0.8, -0.34, 1.0, (60, 64, 84, 255), (10, 12, 20, 255), outline=(2, 2, 6, 255), ow=0.015)
    c.circ(-0.46, 0.9, 0.04, (255, 70, 80, 255))


def _acc_phones_pink(c):
    _phones_band(c, (246, 140, 186, 255), (255, 224, 238, 255), w=0.12)
    for s in (-1, 1):
        u1, u2 = sorted((s * 0.88, s * 1.34))
        c.shape("ellipse", u1, -0.52, u2, 0.52, (255, 200, 224, 255), (232, 108, 160, 255), outline=(176, 56, 110, 255),
                ow=0.03, horizontal=(s == -1))
        ui1, ui2 = sorted((s * 0.84, s * 0.96))
        c.shape("ellipse", ui1, -0.4, ui2, 0.4, (255, 255, 255, 255), (232, 226, 236, 255))
        c.circ(s * 1.12, 0.0, 0.2, (255, 230, 242, 255), (240, 140, 186, 255), outline=(176, 56, 110, 255), ow=0.015)
        c.shine(s * 1.12 - 0.12, -0.34, s * 1.12 + 0.02, -0.18, 140)


# ----- وجه / نظارات / أقنعة -----
def _acc_round(c):
    ink = (36, 28, 22, 255)
    for cx in (-0.47, 0.47):
        c.circ(cx, -0.06, 0.37, (170, 210, 236, 70), (90, 140, 180, 90), outline=ink, ow=0.05)
        c.shine(cx - 0.24, -0.26, cx - 0.06, -0.14, 130)
    c.line([(-0.12, -0.12), (0, -0.2), (0.12, -0.12)], ink, 0.045)
    c.line([(-0.84, -0.12), (-1.04, -0.16)], ink, 0.04)
    c.line([(0.84, -0.12), (1.04, -0.16)], ink, 0.04)


def _acc_starglasses(c):
    for cx in (-0.5, 0.5):
        c.poly(_star_pts(cx, -0.04, 0.58), (255, 140, 200, 235), (200, 40, 130, 235), outline=(255, 255, 255, 255), ow=0.03)
        c.shine(cx - 0.18, -0.14, cx - 0.04, -0.06, 150)
    c.line([(-0.12, -0.06), (0.12, -0.06)], (255, 255, 255, 255), 0.04)


def _acc_3d(c):
    c.shape("rrect", -1.02, -0.32, 1.02, 0.24, (250, 250, 250, 255), (190, 190, 198, 255), outline=(20, 20, 26, 255), ow=0.035, rad=0.05)
    c.shape("rrect", -0.88, -0.2, -0.1, 0.12, (255, 90, 90, 210), (190, 16, 16, 210), outline=(20, 20, 26, 255), ow=0.02, rad=0.04)
    c.shape("rrect", 0.1, -0.2, 0.88, 0.12, (110, 230, 255, 210), (16, 150, 200, 210), outline=(20, 20, 26, 255), ow=0.02, rad=0.04)
    c.line([(-1.02, -0.18), (-1.14, -0.2)], (20, 20, 26, 255), 0.04)
    c.line([(1.02, -0.18), (1.14, -0.2)], (20, 20, 26, 255), 0.04)


def _acc_mask(c):
    c.poly([(-1.04, -0.30), (-0.56, -0.44), (0, -0.26), (0.56, -0.44), (1.04, -0.30), (0.96, 0.08), (0.64, 0.28),
            (0.30, 0.12), (0, 0.04), (-0.30, 0.12), (-0.64, 0.28), (-0.96, 0.08)],
           (232, 50, 62, 255), (112, 8, 20, 255), outline=(60, 4, 10, 255), ow=0.03)
    _hole(c, -0.80, -0.2, -0.14, 0.12)
    _hole(c, 0.14, -0.2, 0.80, 0.12)
    d = c.draw()
    for (a, b, e, f) in ((-0.80, -0.2, -0.14, 0.12), (0.14, -0.2, 0.80, 0.12)):
        (x1, y1), (x2, y2) = c.P(a, b), c.P(e, f)
        d.ellipse([x1, y1, x2, y2], outline=(60, 4, 10, 255), width=c.w(0.03))
    c.shine(-0.9, -0.38, -0.5, -0.3, 100)


def _acc_eyepatch(c):
    k = (16, 16, 20, 255)
    c.line([(0.46, -0.06), (-0.9, -0.9)], k, 0.05)
    c.line([(0.46, -0.06), (1.02, -0.5)], k, 0.05)
    c.shape("ellipse", 0.10, -0.36, 0.84, 0.26, (66, 66, 76, 255), (8, 8, 10, 255), outline=(0, 0, 0, 255), ow=0.03)
    c.shine(0.22, -0.26, 0.46, -0.12, 90)


def _acc_visor(c):
    d = c.draw()
    (x1, y1), (x2, y2) = c.P(-1.1, -0.38), c.P(1.1, 0.22)
    for wd, al in ((0.14, 26), (0.09, 50), (0.05, 90)):
        d.rounded_rectangle([x1, y1, x2, y2], radius=c.w(0.22), outline=(60, 220, 255, al), width=c.w(wd))
    c.shape("rrect", -1.04, -0.34, 1.04, 0.18, (70, 240, 255, 140), (30, 90, 255, 190), outline=(210, 252, 255, 255),
            ow=0.035, rad=0.22, horizontal=True)
    c.line([(-0.72, 0.12), (-0.48, -0.26)], (255, 255, 255, 120), 0.05)
    c.line([(-0.38, 0.12), (-0.22, -0.14)], (255, 255, 255, 90), 0.03)
    c.line([(0.3, 0.12), (0.54, -0.26)], (255, 255, 255, 110), 0.05)


# ----- الفم / اللحية -----
def _acc_beard(c):
    pts = [(-0.84, 0.24), (-0.90, 0.58), (-0.62, 1.0), (0, 1.16), (0.62, 1.0), (0.90, 0.58), (0.84, 0.24),
           (0.62, 0.34), (0.32, 0.30), (0, 0.38), (-0.32, 0.30), (-0.62, 0.34)]
    c.poly(pts, (98, 60, 32, 255), (28, 14, 6, 255), outline=(16, 8, 3, 255), ow=0.02)
    for (u1, v1, u2, v2) in ((-0.62, 0.52, -0.5, 0.96), (-0.3, 0.6, -0.24, 1.08), (0.0, 0.62, 0.0, 1.1),
                             (0.3, 0.6, 0.24, 1.08), (0.62, 0.52, 0.5, 0.96)):
        c.line([(u1, v1), (u2, v2)], (170, 120, 80, 70), 0.025)


def _acc_goatee(c):
    c.poly([(-0.30, 0.58), (0.30, 0.58), (0.42, 0.84), (0.0, 1.16), (-0.42, 0.84)], (88, 54, 28, 255), (24, 12, 5, 255),
           outline=(14, 7, 2, 255), ow=0.018)
    c.line([(-0.18, 0.7), (-0.1, 1.0)], (170, 120, 80, 70), 0.02)
    c.line([(0.18, 0.7), (0.1, 1.0)], (170, 120, 80, 70), 0.02)


def _acc_handlebar(c):
    for s in (-1, 1):
        pts = [(s * u, v) for u, v in [(0.0, 0.40), (0.22, 0.34), (0.5, 0.38), (0.78, 0.5), (0.96, 0.44), (1.06, 0.28),
                                        (1.14, 0.22), (1.14, 0.40), (1.02, 0.60), (0.78, 0.64), (0.5, 0.56),
                                        (0.22, 0.56), (0.0, 0.56)]]
        c.poly(pts, (46, 30, 20, 255), (6, 4, 2, 255), outline=(0, 0, 0, 255), ow=0.015)
        c.line([(s * 0.12, 0.45), (s * 0.7, 0.52)], (200, 170, 140, 60), 0.02)


def _acc_lips(c):
    c.poly([(-0.44, 0.58), (-0.22, 0.46), (-0.06, 0.50), (0, 0.53), (0.06, 0.50), (0.22, 0.46), (0.44, 0.58), (0.0, 0.62)],
           (242, 66, 96, 255), (170, 14, 50, 255), outline=(110, 6, 30, 255), ow=0.015)
    c.poly([(-0.44, 0.58), (0.0, 0.62), (0.44, 0.58), (0.32, 0.77), (0.0, 0.86), (-0.32, 0.77)],
           (252, 96, 126, 255), (190, 22, 62, 255), outline=(110, 6, 30, 255), ow=0.015)
    c.shine(-0.2, 0.68, 0.08, 0.74, 140)


def _acc_rose(c):
    c.line([(0.0, 0.6), (-0.4, 0.74), (-0.84, 0.62)], (40, 120, 52, 255), 0.07)
    c.poly(_ell_pts(-0.45, 0.88, 0.16, 0.07, -25, 24), (130, 200, 80, 255), (40, 120, 40, 255), outline=(26, 80, 28, 255), ow=0.01)
    c.poly(_ell_pts(-0.25, 0.46, 0.14, 0.06, 20, 24), (130, 200, 80, 255), (40, 120, 40, 255), outline=(26, 80, 28, 255), ow=0.01)
    c.circ(-0.86, 0.58, 0.24, (244, 66, 84, 255), (140, 8, 28, 255), outline=(80, 4, 16, 255), ow=0.02)
    c.circ(-0.86, 0.58, 0.16, (252, 100, 116, 255), (170, 18, 40, 255), outline=(100, 6, 20, 255), ow=0.012)
    c.circ(-0.86, 0.58, 0.08, (255, 130, 144, 255), (190, 24, 50, 255), outline=(100, 6, 20, 255), ow=0.01)


def _acc_lollipop(c):
    c.line([(-0.04, 0.62), (0.7, 0.92)], (240, 240, 244, 255), 0.07)
    c.line([(-0.04, 0.62), (0.7, 0.92)], (190, 196, 210, 255), 0.02)
    c.circ(0.84, 1.0, 0.32, (255, 130, 176, 255), (226, 46, 118, 255), outline=(150, 20, 80, 255), ow=0.02)
    c.circ(0.84, 1.0, 0.23, (255, 255, 255, 255), (240, 232, 240, 255))
    c.circ(0.84, 1.0, 0.15, (255, 130, 176, 255), (226, 46, 118, 255))
    c.circ(0.84, 1.0, 0.07, (255, 255, 255, 255))
    c.shine(0.62, 0.78, 0.74, 0.88, 150)


_ACC_DRAWERS = {
    "crown": _acc_crown, "tophat": _acc_tophat, "cap": _acc_cap, "halo": _acc_halo, "cowboy": _acc_cowboy,
    "wizard": _acc_wizard, "chef": _acc_chef, "viking": _acc_viking, "horns": _acc_horns, "santa": _acc_santa,
    "beret": _acc_beret, "ghutra": _acc_ghutra, "glasses": _acc_glasses, "aviator": _acc_aviator,
    "hearts": _acc_hearts, "mustache": _acc_mustache,
    "straw": _acc_straw, "party": _acc_party, "grad": _acc_grad, "pirate": _acc_pirate, "beanie": _acc_beanie,
    "cat": _acc_cat, "bunny": _acc_bunny, "flowers": _acc_flowers, "laurel": _acc_laurel,
    "diamond": _acc_diamond_crown, "phones": _acc_phones, "gaming": _acc_gaming, "phonespink": _acc_phones_pink,
    "round": _acc_round, "starglasses": _acc_starglasses, "glasses3d": _acc_3d, "mask": _acc_mask,
    "eyepatch": _acc_eyepatch, "visor": _acc_visor, "beard": _acc_beard, "goatee": _acc_goatee,
    "handlebar": _acc_handlebar, "lips": _acc_lips, "rose": _acc_rose, "lollipop": _acc_lollipop,
}


def _custom_item_layer(path: str, info: dict, c: _Canvas):
    """لو حاط صورة PNG واقعية للزينة بمجلد profile_items نستخدمها بدل الرسم الجاهز."""
    img = Image.open(path).convert("RGBA")
    w = max(8, int(info.get("img_w", 1.6) * c.r))
    h = max(8, int(img.height * w / img.width))
    img = img.resize((w, h), Image.LANCZOS)
    layer = Image.new("RGBA", (c.side, c.side), (0, 0, 0, 0))
    x = max(0, c.half - w // 2)
    y = max(0, int(c.half + info.get("img_y", -1.2) * c.r - h // 2))
    layer.alpha_composite(img.crop((0, 0, min(w, c.side - x), min(h, c.side - y))), (x, y))
    return layer


def _accessory_layer(kind: str, r: int):
    """يرجع (طبقة الزينة مايلة, نصف حجمها). الطبقة مركزها = مركز الصورة فتتدور حول الراس."""
    info = PROFILE_ITEMS[kind]
    c = _Canvas(r)
    layer = None
    custom = os.path.join(PROFILE_ITEMS_DIR, f"{info['id']}.png")
    if os.path.exists(custom):
        try:
            layer = _custom_item_layer(custom, info, c)
        except Exception as e:
            print(f"[Profile] تعذّر تحميل صورة الزينة {custom}: {e}")
    if layer is None:
        _ACC_DRAWERS[info["id"]](c)
        layer = c.finish()
    tilt = info.get("tilt", 0)
    if tilt:
        layer = layer.rotate(tilt, resample=Image.BICUBIC)
    return layer, c.half


def render_profile_card(avatar_bytes: bytes, display_name: str, handle: str,
                        bank_money: int, points: int, head: str | None, face: str | None,
                        mouth: str | None = None, ears: str | None = None,
                        bg_num: int | None = None) -> BytesIO:
    base = Image.open(PROFILE_BG_PATH).convert("RGBA")
    base = card_backgrounds.apply_background(base, bg_num)
    draw = ImageDraw.Draw(base)
    cx, cy = PROFILE_CIRCLE_CENTER
    r = PROFILE_CIRCLE_RADIUS

    # الصورة داخل الدائرة
    inner = int(r * 2 * 0.95)
    avatar = _circle_avatar(avatar_bytes, inner)
    base.paste(avatar, (cx - inner // 2, cy - inner // 2), avatar)

    # الزينة (الوجه أول ثم الراس)
    for kind in (mouth, face, ears, head):
        if kind in PROFILE_ITEMS:
            layer, half = _accessory_layer(kind, int(r * 0.95))
            base.paste(layer, (cx - half, cy - half), layer)

    draw = ImageDraw.Draw(base)
    text_main = (225, 245, 248, 255)
    text_dim = (150, 190, 198, 255)

    # الاسم (يتشكّل عربي فقط إذا فيه حروف عربية، والإنجليزي يبقى زي ما هو)
    shaped_name = _shape(display_name)
    name_font = _fit_font(draw, shaped_name, 640, 66, 28)
    draw.text((62, 1040), shaped_name, font=name_font, fill=text_main, anchor="lm")
    handle_font = _load_font(32)
    draw.text((64, 1096), _shape(handle), font=handle_font, fill=text_dim, anchor="lm")

    # صندوقين البنك والنقاط
    bank_label = _shape("البنك") if ARABIC_SHAPING_OK else "BANK"
    points_label = _shape("النقاط") if ARABIC_SHAPING_OK else "POINTS"
    for box_xy, label, value in ((PROFILE_LEFT_BOX, bank_label, bank_money),
                                  (PROFILE_RIGHT_BOX, points_label, points)):
        x1, y1, x2, y2 = box_xy
        mx = (x1 + x2) // 2
        label_font = _load_font(46)
        draw.text((mx, y1 + 62), label, font=label_font, fill=text_dim, anchor="mm")
        value_text = f"{value:,}"
        value_font = _fit_font(draw, value_text, (x2 - x1) - 60, 96, 30)
        draw.text((mx, y1 + 160), value_text, font=value_font, fill=text_main, anchor="mm")

    out = BytesIO()
    base.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out


# ============================================================
# 12.5) أوامر المعلومات — بدون بريفكس: u / s / r / a / p
# ============================================================
VERIFICATION_NAMES_AR = {"none": "بدون", "low": "منخفض", "medium": "متوسط", "high": "عالي", "highest": "أعلى مستوى"}


def _ts(dt: datetime, style: str = "F") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"


def _join_limited(items: list[str], limit: int = 1000, sep: str = " ") -> str:
    out, used = [], 0
    for i, item in enumerate(items):
        extra = len(item) + (len(sep) if out else 0)
        if used + extra > limit - 20:
            out.append(f"... و{len(items) - i} أخرى")
            break
        out.append(item)
        used += extra
    return sep.join(out)


async def info_user(message: discord.Message, member: discord.Member):
    """u [@عضو] — معلومات الحساب."""
    guild = message.guild
    color = member.color if member.color.value else discord.Color.blurple()
    embed = discord.Embed(title=f"👤 معلومات {member.display_name}", color=color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="اسم الحساب", value=str(member), inline=True)
    embed.add_field(name="الآيدي", value=f"`{member.id}`", inline=True)
    embed.add_field(name="بوت؟", value="نعم" if member.bot else "لا", inline=True)
    if member.nick:
        embed.add_field(name="اللقب بالسيرفر", value=member.nick, inline=True)
    embed.add_field(name="تاريخ إنشاء الحساب",
                    value=f"{_ts(member.created_at)}\n({_ts(member.created_at, 'R')})", inline=False)
    if member.joined_at:
        embed.add_field(name="تاريخ الدخول للسيرفر",
                        value=f"{_ts(member.joined_at)}\n({_ts(member.joined_at, 'R')})", inline=False)
    roles = [r for r in reversed(member.roles) if r != guild.default_role]
    embed.add_field(name="أعلى رتبة", value=roles[0].mention if roles else "لا يوجد", inline=True)
    embed.add_field(name=f"الرتب ({len(roles)})",
                    value=_join_limited([r.mention for r in roles]) if roles else "لا يوجد", inline=False)
    embed.set_footer(text=f"طلب بواسطة {message.author.display_name}")
    await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def info_server(message: discord.Message):
    """s — معلومات السيرفر."""
    guild = message.guild
    bots = sum(1 for m in guild.members if m.bot)
    total = guild.member_count or len(guild.members)
    embed = discord.Embed(title=f"🏠 {guild.name}", color=discord.Color.blurple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    if guild.description:
        embed.description = guild.description
    embed.add_field(name="الآيدي", value=f"`{guild.id}`", inline=True)
    embed.add_field(name="المالك", value=f"<@{guild.owner_id}>", inline=True)
    embed.add_field(name="تاريخ الإنشاء",
                    value=f"{_ts(guild.created_at)}\n({_ts(guild.created_at, 'R')})", inline=False)
    embed.add_field(name="الأعضاء", value=f"{total} (👤 {total - bots} • 🤖 {bots})", inline=True)
    embed.add_field(name="الرتب", value=str(max(len(guild.roles) - 1, 0)), inline=True)
    embed.add_field(name="الإيموجي", value=str(len(guild.emojis)), inline=True)
    embed.add_field(
        name="الرومات",
        value=(f"💬 كتابي: {len(guild.text_channels)}\n🔊 صوتي: {len(guild.voice_channels)}\n"
               f"📁 تصنيفات: {len(guild.categories)}"),
        inline=True)
    embed.add_field(name="البوست",
                    value=f"المستوى {guild.premium_tier} • {guild.premium_subscription_count or 0} بوست", inline=True)
    embed.add_field(name="مستوى التحقق",
                    value=VERIFICATION_NAMES_AR.get(guild.verification_level.name, guild.verification_level.name),
                    inline=True)
    embed.set_footer(text=f"طلب بواسطة {message.author.display_name}")
    await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def info_roles(message: discord.Message):
    """r — كل رتب السيرفر (من الأعلى للأدنى) مع عدد أعضاء كل رتبة."""
    guild = message.guild
    roles = [r for r in reversed(guild.roles) if r != guild.default_role]
    if not roles:
        await message.channel.send("⚠️ ما فيه رتب بهذا السيرفر.")
        return
    lines = [f"{r.mention} — **{len(r.members)}**" for r in roles]
    embed = discord.Embed(title=f"🎭 رتب السيرفر ({len(roles)})", color=discord.Color.blurple(),
                          description=_join_limited(lines, limit=4000, sep="\n"))
    embed.set_footer(text="الرقم = عدد الأعضاء بالرتبة")
    await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def info_avatar(message: discord.Message, member: discord.Member):
    """a [@عضو] — صورة الحساب بحجم كبير."""
    avatar = member.display_avatar
    formats = ["png", "jpg", "webp"] + (["gif"] if avatar.is_animated() else [])
    links = " • ".join(f"[{f.upper()}]({avatar.with_format(f).with_size(1024).url})" for f in formats)
    embed = discord.Embed(title=f"🖼️ صورة {member.display_name}", description=links, color=discord.Color.blurple())
    embed.set_image(url=avatar.with_size(1024).url)
    if member.guild_avatar:
        embed.set_footer(text="هذي صورته الخاصة بالسيرفر")
    await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def info_profile(message: discord.Message, member: discord.Member):
    """p [@عضو] — بطاقة البروفايل: الصورة + فلوس البنك + النقاط + الزينة."""
    if not PIL_AVAILABLE:
        await message.channel.send("❌ مكتبة Pillow مو منصّبة (`pip install Pillow`).")
        return
    if not os.path.exists(PROFILE_BG_PATH):
        await message.channel.send(f"❌ ملف القالب `{PROFILE_BG_PATH}` مو موجود جنب ملف البوت.")
        return
    async with message.channel.typing():
        try:
            avatar_bytes = await member.display_avatar.replace(size=256, format="png").read()
            entry = get_profile_items(message.guild.id, member.id)
            bank_money = get_bank_money(message.guild.id, member.id)
            points = get_balance(message.guild.id, member.id)
            buf = await asyncio.to_thread(
                render_profile_card, avatar_bytes, member.display_name, f"@{member.name}",
                bank_money, points, entry.get("head"), entry.get("face"), entry.get("mouth"), entry.get("ears"),
                card_backgrounds.get_active(message.guild.id, member.id))
        except Exception as e:
            print(f"[Profile] خطأ برسم البطاقة: {e}")
            await message.channel.send("❌ صار خطأ وأنا أرسم البطاقة.")
            return
    await message.channel.send(file=discord.File(buf, filename="profile.png"))


async def render_member_card(guild: discord.Guild, member: discord.Member, bg_num):
    """يرسم بطاقة العضو (بالنقاط والبنك والزينة) على خلفية معينة — تستخدمها معاينة المتجر."""
    avatar_bytes = await member.display_avatar.replace(size=256, format="png").read()
    entry = get_profile_items(guild.id, member.id)
    bank_money = get_bank_money(guild.id, member.id)
    points = get_balance(guild.id, member.id)
    return await asyncio.to_thread(
        render_profile_card, avatar_bytes, member.display_name, f"@{member.name}",
        bank_money, points, entry.get("head"), entry.get("face"), entry.get("mouth"), entry.get("ears"), bg_num)


card_backgrounds.set_renderer(render_member_card)
card_backgrounds.set_shop_factory(lambda m: ShopView(m))


INFO_COMMAND_KEYS = {"u", "s", "r", "a", "p"}
_MENTION_ONLY = re.compile(r"^<@!?(\d+)>$")


async def try_dispatch_info_command(message: discord.Message) -> bool:
    """أوامر u / s / r / a / p بدون بريفكس.
    ملاحظة: لو الكلام بعد الحرف مو منشن/آيدي (مثل "a man") نتجاهله عشان ما يتداخل مع الكلام العادي."""
    if message.guild is None:
        return False
    parts = message.content.strip().split(None, 1)
    if not parts:
        return False
    key = parts[0].lower()

    if key not in INFO_COMMAND_KEYS:
        return False
    arg = parts[1].strip() if len(parts) > 1 else ""

    if key in ("s", "r"):
        if arg:
            return False
        if key == "s":
            await info_server(message)
        else:
            await info_roles(message)
        return True

    # u / a / p
    member = message.author
    if arg:
        mention_match = _MENTION_ONLY.match(arg)
        if mention_match or arg.isdigit():
            uid = int(mention_match.group(1)) if mention_match else int(arg)
            member = message.guild.get_member(uid)
            if member is None:
                await usage_error(message, f"{key} @العضو")
                return True
        else:
            return False

    if key == "u":
        await info_user(message, member)
    elif key == "a":
        await info_avatar(message, member)
    else:
        await info_profile(message, member)
    return True


# ============================================================
# 13) نظام AFK — .afk <السبب>
# ============================================================
AFK_MAX_REASON_LENGTH = 200
AFK_COMMAND_PATTERN = re.compile(r"^\.afk(\s|$)", re.IGNORECASE)


def set_afk(guild_id: int, user_id: int, reason: str) -> None:
    data = load_json(AFK_FILE)
    gid, uid = str(guild_id), str(user_id)
    data.setdefault(gid, {})
    data[gid][uid] = {"reason": reason, "since": datetime.now(timezone.utc).isoformat()}
    save_json(AFK_FILE, data)


def get_afk(guild_id: int, user_id: int) -> dict | None:
    data = load_json(AFK_FILE)
    return data.get(str(guild_id), {}).get(str(user_id))


def clear_afk(guild_id: int, user_id: int) -> dict | None:
    data = load_json(AFK_FILE)
    gid, uid = str(guild_id), str(user_id)
    entry = data.get(gid, {}).pop(uid, None)
    if entry is not None:
        save_json(AFK_FILE, data)
    return entry


def _format_afk_duration(since_iso: str) -> str:
    try:
        seconds = int((datetime.now(timezone.utc) - datetime.fromisoformat(since_iso)).total_seconds())
    except (TypeError, ValueError):
        return ""
    if seconds < 60:
        return "أقل من دقيقة"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} دقيقة"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ساعة"
    return f"{hours // 24} يوم"


@bot.command(name="afk")
async def afk_cmd(ctx: commands.Context, *, reason: str = None):
    if ctx.guild is None:
        return
    reason = (reason or "AFK").strip()[:AFK_MAX_REASON_LENGTH] or "AFK"
    set_afk(ctx.guild.id, ctx.author.id, reason)

    embed = discord.Embed(
        title=f"💤 {ctx.author.display_name} في وضع AFK",
        color=discord.Color.blurple(),
    )
    embed.description = f"**الرسالة:** {reason}"
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.set_footer(text="أرسل أي رسالة للعودة تلقائيًا")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def _get_replied_member(message: discord.Message) -> discord.Member | None:
    ref = message.reference
    if ref is None or message.guild is None:
        return None
    replied = ref.resolved if isinstance(ref.resolved, discord.Message) else None
    if replied is None and ref.message_id:
        try:
            replied = await message.channel.fetch_message(ref.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            replied = None
    if replied is None:
        return None
    return message.guild.get_member(replied.author.id)


async def handle_afk_on_message(message: discord.Message) -> None:
    if message.guild is None:
        return

    is_afk_command = bool(AFK_COMMAND_PATTERN.match(message.content.strip()))

    if not is_afk_command:
        entry = clear_afk(message.guild.id, message.author.id)
        if entry is not None:
            duration = _format_afk_duration(entry.get("since", ""))
            embed = discord.Embed(
                title=f"👋 أهلًا بعودتك {message.author.display_name}",
                color=discord.Color.blurple(),
            )
            embed.description = "تم إلغاء وضع AFK ✅"
            embed.set_thumbnail(url=message.author.display_avatar.url)
            if duration:
                embed.set_footer(text=f"كنت AFK لمدة {duration}")
            try:
                await message.channel.send(
                    embed=embed, delete_after=10, allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                pass

    to_check: dict[int, discord.Member] = {m.id: m for m in message.mentions}
    replied_member = await _get_replied_member(message)
    if replied_member is not None:
        to_check.setdefault(replied_member.id, replied_member)

    for member in to_check.values():
        if member.bot or member.id == message.author.id:
            continue
        entry = get_afk(message.guild.id, member.id)
        if entry is None:
            continue
        duration = _format_afk_duration(entry.get("since", ""))
        embed = discord.Embed(
            title=f"💤 {member.display_name} في وضع AFK",
            color=discord.Color.blurple(),
        )
        embed.description = f"**الرسالة:** {entry.get('reason', 'AFK')}"
        embed.set_thumbnail(url=member.display_avatar.url)
        if duration:
            embed.set_footer(text=f"منذ {duration}")
        try:
            await message.channel.send(
                embed=embed, delete_after=15, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass


# ============================================================
# 14) نظام حماية الروابط — أي رابط = مسح الرسالة + تايم يوم كامل
# ============================================================
LINK_TIMEOUT = timedelta(days=1)
LINK_WHITELIST_DOMAINS = {
    "tenor.com", "media.tenor.com", "giphy.com", "media.giphy.com",
    "cdn.discordapp.com", "media.discordapp.net", "images-ext-1.discordapp.net",
    "images-ext-2.discordapp.net",
}
LINK_ALLOWED_CHANNEL_IDS: set[int] = set()

_LINK_TLDS = (
    "com|net|org|gg|io|me|xyz|info|biz|co|tv|cc|ly|to|us|uk|sa|ae|eg|kw|qa|tk|ml|ga|cf|gq|"
    "app|dev|site|online|store|shop|club|live|link|click|fun|top|vip|pro|ru|de|fr|in"
)
LINK_PATTERN = re.compile(
    rf"(?i)(?:https?://|www\.)[^\s<>]+|\b(?:[a-z0-9-]+\.)+(?:{_LINK_TLDS})\b(?:/[^\s<>]*)?"
)


def _link_host(raw: str) -> str:
    host = re.sub(r"(?i)^https?://", "", raw.strip())
    host = re.split(r"[/?#:]", host, maxsplit=1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def message_has_blocked_link(content: str) -> bool:
    for match in LINK_PATTERN.finditer(content):
        host = _link_host(match.group(0))
        allowed = any(host == d or host.endswith("." + d) for d in LINK_WHITELIST_DOMAINS)
        if not allowed:
            return True
    return False


def is_link_exempt(member) -> bool:
    if not isinstance(member, discord.Member):
        return True
    if member.id == member.guild.owner_id or member.guild_permissions.administrator:
        return True
    return has_role(member, TRIAL_ROLES)


async def handle_link_protection(message: discord.Message) -> bool:
    """يرجع True لو الرسالة فيها رابط ممنوع وتم التعامل معها (مسح + تايم يوم)."""
    if message.guild is None or message.author.bot:
        return False
    if message.channel.id in LINK_ALLOWED_CHANNEL_IDS or is_link_exempt(message.author):
        return False
    if not message.content or not message_has_blocked_link(message.content):
        return False

    author = message.author
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    timed_out = True
    try:
        await author.timeout(LINK_TIMEOUT, reason="نظام حماية الروابط: إرسال رابط")
    except (discord.Forbidden, discord.HTTPException):
        timed_out = False

    try:
        if timed_out:
            await message.channel.send(
                f"🚫 {author.mention} ممنوع إرسال الروابط! تم إعطاؤك تايم لمدة **يوم كامل**.",
                delete_after=10)
        else:
            await message.channel.send(
                f"🚫 {author.mention} ممنوع إرسال الروابط! (ما قدرت أعطيك تايم، رتبتي أقل من رتبتك)",
                delete_after=10)
    except (discord.Forbidden, discord.HTTPException):
        pass

    embed = discord.Embed(title="🔗 حماية الروابط: تم معاقبة عضو", color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=author.mention, inline=True)
    embed.add_field(name="الروم", value=message.channel.mention, inline=True)
    embed.add_field(name="العقوبة", value="تايم يوم كامل" if timed_out else "مسح الرسالة فقط (فشل التايم)", inline=True)
    embed.add_field(name="الرسالة", value=message.content[:1000], inline=False)
    embed.set_footer(text=f"معرف العضو: {author.id}")
    await send_log(message.guild, "security", embed)
    return True


# ============================================================
# دوال مساعدة للوقات العامة (روابط دعوة)
# ============================================================
async def log_invite_link(message: discord.Message) -> None:
    """يسجل أي رابط دعوة ديسكورد بروم security-logs."""
    embed = discord.Embed(title="🚨 رابط دعوة ديسكورد", color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=message.author.mention, inline=True)
    embed.add_field(name="الروم", value=message.channel.mention, inline=True)
    embed.add_field(name="الرسالة", value=message.content[:1000], inline=False)
    embed.set_footer(text=f"معرف العضو: {message.author.id}")
    await send_log(message.guild, "security", embed)


# ============================================================
# رد السلام التلقائي (كل صيغ "السلام عليكم")
# ============================================================
SALAM_PATTERN = re.compile(r"(?:^|\s)(?:ال)?سلا+م[ون]?\s*(?:عليكم|عليك|عليكن|علكيم)(?:\s|$)")
SALAM_REPLY = "وعليكم السلام ورحمة الله وبركاته 🌹"


def is_salam_message(content: str) -> bool:
    text = re.sub(r"[^\w\s]", " ", normalize(content))
    text = " ".join(text.split())
    if not text or len(text) > 60:
        return False
    return bool(SALAM_PATTERN.search(text + " "))


# ============================================================
# روم الفخ "ممنوع-الارسال" — أي أحد يرسل فيه يتبند فورًا
# ============================================================
TRAP_CHANNEL_NAME = "ممنوع-الارسال"
TRAP_CHANNEL_ID = 1552574286605197396
TRAP_EXEMPT_STAFF = True
TRAP_DELETE_SECONDS = 3600


def is_trap_channel(channel) -> bool:
    return getattr(channel, "id", None) == TRAP_CHANNEL_ID


async def handle_trap_message(message: discord.Message) -> bool:
    """يبند اللي أرسل برسالة بروم الفخ. يرجع True لو تعامل مع الرسالة."""
    author = message.author
    guild = message.guild
    if TRAP_EXEMPT_STAFF and is_staff_member(author):
        return False

    reason = f"أرسل برسالة بروم {TRAP_CHANNEL_NAME} (بند تلقائي)"
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass

    banned = False
    try:
        try:
            await guild.ban(author, reason=reason, delete_message_seconds=TRAP_DELETE_SECONDS)
        except TypeError:
            await guild.ban(author, reason=reason)
        banned = True
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"[Trap] ما قدرت أبند {author} ({author.id}): {e}")

    title = "🪤 بند تلقائي — روم الفخ" if banned else "⚠️ فشل البند التلقائي — روم الفخ"
    extra = {"الروم": message.channel.mention}
    if not banned:
        extra["السبب"] = "ما عندي صلاحية أبند هذا العضو (رتبته أعلى مني أو ينقصني Ban Members)"
    await log_mod_action(guild, title, guild.me, author, reason, extra)
    return True


# ============================================================
# رياكشن تلقائي على الصور (رومات locket / streaks)
# ============================================================
REACTION_CHANNEL_IDS = {
    1538293753306161192,   # locket
    1540256888761876480,   # streaks
}
REACTION_EMOJIS = ["💥", "🔥", "⛔", "😼"]
LOCKET_CHANNEL_ID = 1538293753306161192
DIVIDER_IMAGE_PATH = "divider.png"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic",
                    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")


def is_reaction_channel(channel) -> bool:
    return getattr(channel, "id", None) in REACTION_CHANNEL_IDS


def message_has_image(message: discord.Message) -> bool:
    for att in message.attachments:
        ctype = att.content_type or ""
        if ctype.startswith("image/") or ctype.startswith("video/"):
            return True
        if att.filename.lower().endswith(IMAGE_EXTENSIONS):
            return True
    for emb in message.embeds:
        if emb.type == "image" or emb.image or emb.thumbnail:
            return True
    return False


async def handle_image_reaction(message: discord.Message) -> None:
    if message.guild is None or not is_reaction_channel(message.channel):
        return
    if not message_has_image(message):
        return
    for emoji in REACTION_EMOJIS:
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException):
            pass
    if message.channel.id == LOCKET_CHANNEL_ID and os.path.exists(DIVIDER_IMAGE_PATH):
        try:
            await message.channel.send(file=discord.File(DIVIDER_IMAGE_PATH))
        except (discord.Forbidden, discord.HTTPException):
            pass


def is_locket_exempt(member) -> bool:
    """الإدارة العليا (Vice Owner / Co-Owner / Owner / founder) ومالك السيرفر يكتبون بروم locket عادي."""
    if not isinstance(member, discord.Member):
        return False
    return member.id == member.guild.owner_id or has_role(member, TOP_ROLES)


async def handle_locket_filter(message: discord.Message) -> bool:
    """يحذف أي رسالة بروم locket ما فيها صورة أو مقطع (إلا لو الكاتب من الإدارة العليا). يرجع True لو انحذفت."""
    if message.guild is None or message.channel.id != LOCKET_CHANNEL_ID:
        return False
    if message_has_image(message) or is_locket_exempt(message.author):
        return False
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass
    return True


@bot.command(name="ارسل")
async def send_divider_cmd(ctx: commands.Context):
    if not os.path.exists(DIVIDER_IMAGE_PATH):
        await ctx.send("⚠️ ملف الفاصل `divider.png` مو موجود.")
        return
    await ctx.send(file=discord.File(DIVIDER_IMAGE_PATH))


# ============================================================
# معالج الرسائل الموحّد
# ============================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # روم الفخ: أول شي قبل أي معالجة ثانية
    if message.guild is not None and is_trap_channel(message.channel):
        if await handle_trap_message(message):
            return

    # روم locket: أي رسالة بدون صورة/مقطع تنحذف (إلا الإدارة العليا)
    if await handle_locket_filter(message):
        return

    # ".قول <نص>": نحذف رسالة صاحب الأمر فورًا
    if message.guild is not None and SAY_COMMAND_PATTERN.match(message.content):
        say_text = message.content.split(None, 1)[1]
        if not (message_has_blocked_link(say_text) and not is_link_exempt(message.author)):
            silent_deleted_ids.add(message.id)
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                silent_deleted_ids.discard(message.id)

    if message.guild is not None:
        if INVITE_LINK_PATTERN.search(message.content):
            await log_invite_link(message)

    # نصفّي المنشنات: الرد على رسالة بدون كتابة @ صريحة ما يعتبر منشن
    message.mentions = filter_explicit_mentions(message)

    # نظام AFK
    await handle_afk_on_message(message)

    # رياكشن على الصور برومات locket / streaks
    await handle_image_reaction(message)

    # رد السلام
    if message.guild is not None and is_salam_message(message.content):
        try:
            await message.reply(SALAM_REPLY, mention_author=False)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # لو أحد كتب نقطة "." لحالها يرد عليه البوت "يمرحبا"
    if message.content.strip() == ".":
        try:
            await message.channel.send("يمرحبا")
        except (discord.Forbidden, discord.HTTPException):
            pass
        return

    if WARN_COMMAND_PATTERN.match(message.content.strip()):
        await handle_warn_command(message)
        return

    if await bank.try_dispatch_bank_admin(message):
        return

    # أوامر p / u / s / r / a (بدون بريفكس)
    if await try_dispatch_info_command(message):
        return

    if await try_dispatch_admin_command(message):
        return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول باسم {bot.user}")
    if bot.get_cog("AntiSwear") is None:
        from anti_swear import AntiSwear
        await bot.add_cog(AntiSwear(bot))
    if not shop_expiry_task.is_running():
        shop_expiry_task.start()
    for guild in bot.guilds:
        embed = discord.Embed(title="✅ البوت اشتغل", color=discord.Color.green(),
                               timestamp=datetime.now(timezone.utc))
        await send_log(guild, "bot", embed)


# أمثلة الاستخدام الصحيح لأوامر النقطة (تظهر لما يكتب العضو الأمر غلط)
PREFIX_USAGE_EXAMPLES = {
    "تحويل": ".تحويل @عضو 100",
    "اصدار": ".اصدار 1000",
    "شراء": ".شراء تاج",
    "لبس": ".لبس تاج",
    "قول": ".قول النص اللي تبيه",
    "رصيد": ".رصيد @عضو",
    "سجلي": ".سجلي @عضو",
}


def _usage_example_for(ctx: commands.Context) -> str:
    name = ctx.command.name if ctx.command else ""
    return PREFIX_USAGE_EXAMPLES.get(name, f".{name} @عضو")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, bank.BankChannelRequired):
        await bank.handle_bank_channel_error(ctx)
    elif isinstance(error, games.GamesRoleRequired):
        await games.handle_games_role_error(ctx)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(f"⚠️ ما لقيت هذا العضو — استخدم الأمر بطريقة صحيحة، مثال:\n`{_usage_example_for(ctx)}`")
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send(f"⚠️ استخدم الأمر بطريقة صحيحة، مثال:\n`{_usage_example_for(ctx)}`")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        print(f"[خطأ غير متوقع] {error}")
        if ctx.guild is not None:
            embed = discord.Embed(title="❌ خطأ غير متوقع بأمر", color=discord.Color.red(),
                                   timestamp=datetime.now(timezone.utc))
            embed.add_field(name="الأمر", value=f".{ctx.command.qualified_name}" if ctx.command else "غير معروف",
                             inline=True)
            embed.add_field(name="بواسطة", value=ctx.author.mention, inline=True)
            embed.add_field(name="الخطأ", value=str(error)[:1000], inline=False)
            await send_log(ctx.guild, "bot", embed)
        await ctx.send("❌ صار خطأ غير متوقع أثناء تنفيذ الأمر.")


@bot.event
async def on_command_completion(ctx: commands.Context):
    """يسجل استخدام كل أمر ناجح بروم bot-logs."""
    if ctx.guild is None:
        return
    embed = discord.Embed(title="🤖 استخدام أمر", color=discord.Color.teal(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الأمر", value=f".{ctx.command.qualified_name}", inline=True)
    embed.add_field(name="بواسطة", value=ctx.author.mention, inline=True)
    embed.add_field(name="الروم", value=ctx.channel.mention, inline=True)
    await send_log(ctx.guild, "bot", embed)


# ---------- لوقات الأعضاء (دخول/خروج) ----------
@bot.event
async def on_member_join(member: discord.Member):
    embed = discord.Embed(title="📥 عضو جديد دخل السيرفر", color=discord.Color.green(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=member.mention, inline=True)
    embed.add_field(name="تاريخ إنشاء الحساب", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"معرف العضو: {member.id}")
    await send_log(member.guild, "member", embed)


@bot.event
async def on_member_remove(member: discord.Member):
    kicker = await get_audit_executor(member.guild, discord.AuditLogAction.kick, member.id, max_age=10)
    title = "👢 تم طرد عضو من السيرفر" if kicker else "📤 عضو خرج من السيرفر"
    embed = discord.Embed(title=title, color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=f"{member} ({member.mention})", inline=True)
    if kicker:
        embed.add_field(name="اللي طرده", value=kicker.mention, inline=True)
    if member.joined_at:
        embed.add_field(name="انضم بتاريخ", value=discord.utils.format_dt(member.joined_at, "R"), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"معرف العضو: {member.id}")
    await send_log(member.guild, "member", embed)


# ---------- لوقات الحظر ----------
@bot.event
async def on_member_ban(guild: discord.Guild, user):
    moderator = None
    reason = None
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=3):
            if entry.target and entry.target.id == user.id:
                moderator, reason = entry.user, entry.reason
                break
    except discord.Forbidden:
        pass
    embed = discord.Embed(title="🔨 تم حظر عضو", color=discord.Color.dark_red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=str(user), inline=True)
    if moderator:
        embed.add_field(name="بواسطة", value=moderator.mention, inline=True)
    if reason:
        embed.add_field(name="السبب", value=reason, inline=False)
    embed.set_footer(text=f"معرف العضو: {user.id}")
    await send_log(guild, "ban", embed)


@bot.event
async def on_member_unban(guild: discord.Guild, user):
    moderator = None
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=3):
            if entry.target and entry.target.id == user.id:
                moderator = entry.user
                break
    except discord.Forbidden:
        pass
    embed = discord.Embed(title="✅ تم فك الحظر عن عضو", color=discord.Color.green(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=str(user), inline=True)
    if moderator:
        embed.add_field(name="بواسطة", value=moderator.mention, inline=True)
    embed.set_footer(text=f"معرف العضو: {user.id}")
    await send_log(guild, "ban", embed)


# ---------- لوقات الرتب ----------
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    guild = after.guild

    # ---- الرتب ----
    added = [r for r in after.roles if r not in before.roles]
    removed = [r for r in before.roles if r not in after.roles]
    if added or removed:
        executor = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
        embed = discord.Embed(title="🎭 تعديل رتب عضو", color=discord.Color.blurple(),
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="العضو", value=after.mention, inline=False)
        if added:
            embed.add_field(name="➕ أضيفت", value="، ".join(r.mention for r in added), inline=False)
            embed.add_field(name="🎁 اللي أعطى الرتبة", value=executor.mention if executor else "غير معروف",
                            inline=True)
        if removed:
            embed.add_field(name="➖ أزيلت", value="، ".join(r.mention for r in removed), inline=False)
            embed.add_field(name="📤 اللي سحب الرتبة", value=executor.mention if executor else "غير معروف",
                            inline=True)
        embed.set_footer(text=f"معرف العضو: {after.id}")
        await send_log(guild, "role", embed)

    # ---- اللقب ----
    if before.nick != after.nick:
        executor = await get_audit_executor(guild, discord.AuditLogAction.member_update, after.id)
        if executor is None or executor.id == after.id:
            who = "العضو نفسه"
        else:
            who = executor.mention
        embed = discord.Embed(title="📝 تغيير لقب عضو", color=discord.Color.blurple(),
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="العضو", value=after.mention, inline=True)
        embed.add_field(name="اللي غيّره", value=who, inline=True)
        embed.add_field(name="قبل", value=before.nick or "(بدون لقب)", inline=False)
        embed.add_field(name="بعد", value=after.nick or "(بدون لقب)", inline=False)
        embed.set_footer(text=f"معرف العضو: {after.id}")
        await send_log(guild, "member", embed)

    # ---- التايم أوت ----
    if before.timed_out_until != after.timed_out_until:
        executor = await get_audit_executor(guild, discord.AuditLogAction.member_update, after.id)
        if after.timed_out_until:
            title, color = "⏱️ تم إعطاء عضو تايم", discord.Color.orange()
        else:
            title, color = "✅ تم فك التايم عن عضو", discord.Color.green()
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="العضو", value=after.mention, inline=True)
        embed.add_field(name="بواسطة", value=executor.mention if executor else "غير معروف", inline=True)
        if after.timed_out_until:
            embed.add_field(name="ينتهي", value=discord.utils.format_dt(after.timed_out_until, "R"), inline=True)
        embed.set_footer(text=f"معرف العضو: {after.id}")
        await send_log(guild, "mod", embed)


@bot.event
async def on_guild_role_create(role: discord.Role):
    executor = await get_audit_executor(role.guild, discord.AuditLogAction.role_create, role.id)
    embed = discord.Embed(title="➕ تم إنشاء رتبة", color=discord.Color.green(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الرتبة", value=role.mention, inline=True)
    embed.add_field(name="الاسم", value=role.name, inline=True)
    embed.add_field(name="اللي سواها", value=executor.mention if executor else "غير معروف", inline=True)
    embed.set_footer(text=f"معرف الرتبة: {role.id}")
    await send_log(role.guild, "role", embed)


@bot.event
async def on_guild_role_delete(role: discord.Role):
    executor = await get_audit_executor(role.guild, discord.AuditLogAction.role_delete, role.id)
    embed = discord.Embed(title="🗑️ تم حذف رتبة", color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الاسم", value=role.name, inline=True)
    embed.add_field(name="اللي حذفها", value=executor.mention if executor else "غير معروف", inline=True)
    embed.set_footer(text=f"معرف الرتبة: {role.id}")
    await send_log(role.guild, "role", embed)


# ---------- لوقات الرومات ----------
@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(title="➕ تم إنشاء روم", color=discord.Color.green(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الروم", value=getattr(channel, "mention", f"#{channel.name}"), inline=True)
    embed.add_field(name="اللي أنشأه",
                    value=await audit_who(channel.guild, discord.AuditLogAction.channel_create, channel.id),
                    inline=True)
    embed.set_footer(text=f"معرف الروم: {channel.id}")
    await send_log(channel.guild, "channel", embed)


@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(title="🗑️ تم حذف روم", color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الروم", value=f"#{channel.name}", inline=True)
    embed.add_field(name="اللي حذفه",
                    value=await audit_who(channel.guild, discord.AuditLogAction.channel_delete, channel.id),
                    inline=True)
    embed.set_footer(text=f"معرف الروم: {channel.id}")
    await send_log(channel.guild, "channel", embed)


@bot.event
async def on_guild_channel_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"الاسم: `{before.name}` ← `{after.name}`")
    if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
        if before.topic != after.topic:
            changes.append("تم تغيير وصف الروم")
        if before.slowmode_delay != after.slowmode_delay:
            changes.append(f"الإبطاء: {before.slowmode_delay}ث ← {after.slowmode_delay}ث")
    if not changes:
        return
    embed = discord.Embed(title="✏️ تعديل روم", color=discord.Color.orange(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الروم", value=getattr(after, "mention", f"#{after.name}"), inline=False)
    embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
    embed.add_field(name="اللي عدّله",
                    value=await audit_who(after.guild, discord.AuditLogAction.channel_update, after.id),
                    inline=True)
    embed.set_footer(text=f"معرف الروم: {after.id}")
    await send_log(after.guild, "channel", embed)


# ---------- لوقات الصوت ----------
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel == after.channel:
        # كتم/صمم سيرفر من إداري (مو من العضو نفسه)
        changes = []
        if before.mute != after.mute:
            changes.append("تم كتمه صوتيًا" if after.mute else "تم فك كتمه الصوتي")
        if before.deaf != after.deaf:
            changes.append("تم تصميمه (ما يسمع)" if after.deaf else "تم فك تصميمه")
        if changes and after.channel is not None:
            executor = await get_audit_executor(member.guild, discord.AuditLogAction.member_update, member.id)
            embed = discord.Embed(title="🎙️ تعديل حالة صوتية", color=discord.Color.orange(),
                                   timestamp=datetime.now(timezone.utc))
            embed.add_field(name="العضو", value=member.mention, inline=True)
            embed.add_field(name="اللي سواها", value=executor.mention if executor else "غير معروف", inline=True)
            embed.add_field(name="الحالة", value="، ".join(changes), inline=False)
            embed.set_footer(text=f"معرف العضو: {member.id}")
            await send_log(member.guild, "voice", embed)
        return
    embed = discord.Embed(color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=f"معرف العضو: {member.id}")
    if before.channel is None and after.channel is not None:
        count_after = len(after.channel.members)
        count_before = max(0, count_after - 1)
        embed.title = "🔊 دخل روم صوتي"
        embed.description = f"{member.mention} دخل {after.channel.mention}"
        embed.add_field(name="عدد الأعضاء بالروم", value=f"{count_before} ← {count_after}", inline=True)
    elif before.channel is not None and after.channel is None:
        count_before = len(before.channel.members) + 1
        count_after = len(before.channel.members)
        embed.title = "🔇 خرج من روم صوتي"
        embed.description = f"{member.mention} خرج من {before.channel.mention}"
        embed.add_field(name="عدد الأعضاء بالروم", value=f"{count_before} ← {count_after}", inline=True)
    else:
        from_count = len(before.channel.members) + 1
        to_count = len(after.channel.members)
        embed.title = "🔀 انتقل بين رومات صوتية"
        embed.description = f"{member.mention}: {before.channel.mention} ← {after.channel.mention}"
        embed.add_field(name=f"عدد أعضاء {before.channel.name} بعد الخروج", value=str(from_count - 1), inline=True)
        embed.add_field(name=f"عدد أعضاء {after.channel.name} بعد الدخول", value=str(to_count), inline=True)
    await send_log(member.guild, "voice", embed)


# ---------- لوقات تعديل الرسائل ----------
@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.content == after.content or before.guild is None:
        return
    embed = discord.Embed(title="✏️ تم تعديل رسالة", color=discord.Color.orange(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الكاتب", value=before.author.mention, inline=True)
    embed.add_field(name="الروم", value=before.channel.mention, inline=True)
    embed.add_field(name="قبل", value=(before.content[:1000] if before.content else "(فاضي)"), inline=False)
    embed.add_field(name="بعد", value=(after.content[:1000] if after.content else "(فاضي)"), inline=False)
    if getattr(after, "jump_url", None):
        embed.add_field(name="الرابط", value=f"[اذهب للرسالة]({after.jump_url})", inline=False)
    embed.set_footer(text=f"معرف العضو: {before.author.id}")
    await send_log(before.guild, "modified_message", embed)


# ---------- لوقات إعدادات السيرفر ----------
@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    changes = []
    if before.name != after.name:
        changes.append(f"الاسم: `{before.name}` ← `{after.name}`")
    if before.icon != after.icon:
        changes.append("تم تغيير شعار السيرفر")
    if before.premium_subscription_count != after.premium_subscription_count:
        changes.append(f"عدد البوستات: {before.premium_subscription_count} ← {after.premium_subscription_count}")
    if not changes:
        return
    embed = discord.Embed(title="⚙️ تعديل إعدادات السيرفر", color=discord.Color.gold(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
    embed.add_field(name="اللي عدّل",
                    value=await audit_who(after, discord.AuditLogAction.guild_update, after.id),
                    inline=True)
    await send_log(after, "server", embed)


@bot.event
async def on_guild_emojis_update(guild, before, after):
    before_ids, after_ids = {e.id for e in before}, {e.id for e in after}
    added = [e for e in after if e.id not in before_ids]
    removed = [e for e in before if e.id not in after_ids]
    embed = discord.Embed(title="😀 تحديث إيموجي السيرفر", color=discord.Color.gold(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="عدد الإيموجي", value=f"{len(before)} ← {len(after)}", inline=False)
    if added:
        embed.add_field(name="➕ أضيف", value="، ".join(f"`{e.name}`" for e in added)[:1000], inline=True)
        embed.add_field(name="اللي أضافه",
                        value=await audit_who(guild, discord.AuditLogAction.emoji_create, added[0].id), inline=True)
    if removed:
        embed.add_field(name="➖ انحذف", value="، ".join(f"`{e.name}`" for e in removed)[:1000], inline=True)
        embed.add_field(name="اللي حذفه",
                        value=await audit_who(guild, discord.AuditLogAction.emoji_delete, removed[0].id), inline=True)
    await send_log(guild, "server", embed)


# ============================================================
# ويب سيرفر صغير (عشان Render يشوف بورت مفتوح ويبقي البوت شغال)
# ============================================================
class SimpleHandler(BaseHTTPRequestHandler):
    def _ok(self, body: bool = True):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(b"Bot is active and running!")

    def do_GET(self):
        self._ok()

    def do_HEAD(self):
        self._ok(body=False)

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        httpd = HTTPServer(("0.0.0.0", port), SimpleHandler)
    except OSError as e:
        print(f"[ويب سيرفر] ❌ فشل فتح البورت {port}: {e}")
        return
    print(f"[ويب سيرفر] ✅ فاتح وشغال على 0.0.0.0:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    web_thread.join(timeout=2)
    if not web_thread.is_alive():
        print("[ويب سيرفر] ⚠️ الثريد وقف بسرعة غير طبيعية — راجع رسالة الخطأ فوق.")
    else:
        print("[ويب سيرفر] الثريد شغال بعد ثانيتين، الأغلب البورت فتح تمام.")

    bot.run(DISCORD_TOKEN)
