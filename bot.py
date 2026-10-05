"""
بوت ديسكورد شامل — نسخة كاملة مدموجة (مع مركز الألعاب الموسّع)
=====================================================================
الأقسام:
  1) نظام التحذيرات (تحذير + أزرار أسباب)
  2) نظام الاقتصاد / النقاط (رصيد / نقاطي / يومي / تحويل)
  3) نظام الجولات العام (لألعاب "أول من يجاوب يفوز")
  4) مركز الألعاب:
       - ألعاب جماعية (تبدأ بلوبي 30 ثانية، فيها زر انضمام وزر خروج، حتى 20 لاعب)
       - ألعاب فردية / تحدي مباشر
  5) نظام الإدارة الكامل (أعضاء / رومات / صوت) — بدون بريفكس، حسب الرتب
  6) .العاب و .شرح <اسم اللعبة> و .اوامر

ملاحظات مهمة قبل التشغيل:
  - كل أوامر النقاط والألعاب تبدأ بعلامة "." (مثال: .روليت ، .نقاطي ، .العاب ، .اوامر).
  - أوامر الإدارة تبقى بدون بريفكس زي ما كانت (تحذير ، برا ، سجن ... إلخ).
  - غيّر أسماء الرتب بالأسفل (ROLE NAMES) إذا كانت أسماء رتبك بالسيرفر
    مختلفة شوي عن الأسماء المكتوبة هنا (لازم تطابق بالضبط حرف بحرف).
  - لازم تسوي رتبتين يدويًا بالسيرفر عشان "سجن" و"اخرس" يشتغلوا صح:
        * رتبة اسمها بالضبط: Jailed  (احجب عنها كل الرومات إلا روم السجن)
        * رتبة اسمها بالضبط: Muted   (احجب عنها إرسال الرسائل بكل الرومات)
    لو ما كانت موجودة، البوت بينشئها تلقائيًا لكن بدون صلاحيات محجوبة —
    لازم تظبط صلاحياتها يدويًا من إعدادات السيرفر أول مرة.

  - بعض الألعاب (مثل "ادمج" و"ريبلكا") فيها تفسير مبسّط مني لأسمائها —
    لو تقصد شكل مختلف قولي وأعدلها.

  (ملاحظة: كود الألعاب انفصل عن هذا الملف وصار بملف لحاله: games_bot.py)
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
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
WARN_LOG_WEBHOOK_URL = os.environ.get("WARN_WEBHOOK_URL", "")

WARNS_FILE = "warns.json"
ECONOMY_FILE = "economy.json"
JAIL_FILE = "jail_data.json"
ROLES_REMOVED_FILE = "removed_roles.json"
GAME_STATS_FILE = "game_stats.json"
SHOP_ACTIVE_FILE = "shop_active.json"
AFK_FILE = "afk.json"

JAIL_ROLE_NAME = "Jailed"
MUTE_ROLE_NAME = "Muted"
WARN_LOG_CHANNEL_NAMES = ["warn-log", "توثيق-التنبيهات", "سجل-التنبيهات", "تنبيهات-اللوق", "log-تنبيهات"]

# ============================================================
# 0) نظام اللوقات العام (روومات تسجيل منفصلة لكل نوع حدث)
# ============================================================
# كل مفتاح تحته أسماء الروم اللي يدور عليها البوت بالسيرفر (بالاسم، يتحمل حروف كبيرة/صغيرة وشرطات/سفلات).
# روم "ticket-logs" ما ضفناه لأنه مخصص لبوت ثاني حسب كلامك، وروم "moderator-only" مخصص لتواصل الإدارة
# يدويًا وما يحتاج البوت يرسل فيه شي تلقائي.
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
    """يدور على روم لوق معيّن بالاسم (يتحمل حروف كبيرة/صغيرة وشرطات/سفلات)."""
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
# ============================================================
# فلتر المنشن الصريح (يمنع إن مجرد "الرد" على رسالة حد يعتبر منشن له)
# ============================================================
# ديسكورد لما ترد على رسالة وتسوي "Reply" مع تفعيل التنبيه، يحط صاحب الرسالة
# جوا message.mentions حتى لو ما كتبت @اسمه صراحة بالنص. هذا يخلي أوامر زي "تايم"
# أو "برا" ممكن تنفذ غلط على شخص انت بس رادّ عليه بدون ما تقصد تنفذ فيه أمر.
# الحل: نصفّي القائمة ونخلي فيها بس الأعضاء اللي فعليًا مكتوب @هم بنص الرسالة.
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
    """يدور على روم مخصص للوق التحذيرات بالاسم (يتحمل حروف كبيرة/صغيرة ومسافات/شرطات)."""
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
        print("[WarnSystem] ⚠️ ما قدرت أوصل لوق التحذير — لا الويب هوك اشتغل ولا لقيت روم اسمه warn-log.")


# ---------- قائمة الأسباب (منيو منسدلة — تستخدم لأمر تحذير ولكل أوامر العقوبات) ----------
# عدّل القائمة زي ما تبي. الايموجي اختياري (None = بدون ايموجي).
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
    """رسالة فيها أزرار أسباب (مثل أزرار الروليت)، بس الإداري اللي كتب الأمر يقدر يضغط."""

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
                                       footer="⏳ انتهى الوقت — ما تم تنفيذ شي"),
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
    if not is_staff_member(author):
        await message.channel.send(f"{author.mention} ❌ ما عندك صلاحية لهذا الأمر.")
        return

    if not message.mentions:
        await message.channel.send(f"{author.mention} ⚠️ الصيغة: `تحذير @العضو` (وبعدها تختار السبب من الأزرار)")
        return

    target = message.mentions[0]
    if target.bot or target.id == author.id:
        await message.channel.send(f"{author.mention} ⚠️ ما تقدر تحذر نفسك أو بوت.")
        return

    typed = strip_mentions(message.content.strip()[len("تحذير"):], message.mentions)
    reason = typed or await ask_reason(message, target, "تحذير", "⚠️")
    if reason is None:
        return

    warn_number = add_warn(message.guild.id, target.id, reason, author.id)
    await send_warn_log(message.guild, target, author, reason, warn_number, message.channel.name)
    await message.channel.send(f"✅ تم تسجيل تحذير رقم **#{warn_number}** بحق {target.mention} — السبب: {reason}")


@bot.command(name="تحذيراته", aliases=["تنبيهاته", "warns"])
async def show_warns(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    count = get_warn_count(ctx.guild.id, member.id)
    await ctx.send(f"📋 لدى {member.mention} **{count}** تحذير/تحذيرات مسجلة.")


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


@bot.command(name="توب", aliases=["ليدربورد"])
async def leaderboard_cmd(ctx: commands.Context):
    data = load_json(ECONOMY_FILE)
    guild_data = data.get(str(ctx.guild.id), {})
    # نستبعد المفاتيح المساعدة (تواريخ اليومي/سقف الألعاب) ونخلي أرقام اليوزرات بس
    scores = []
    for key, value in guild_data.items():
        if key.isdigit() and isinstance(value, int):
            scores.append((int(key), value))
    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:10]
    if not top:
        await ctx.send("📉 ما فيه أي نقاط مسجلة بهذا السيرفر لين الحين.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 **توب 10 — أعلى النقاط بالسيرفر**\n"]
    for i, (uid, pts) in enumerate(top):
        member = ctx.guild.get_member(uid)
        name = member.mention if member else f"عضو غادر (`{uid}`)"
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{rank} {name} — **{pts}** نقطة")
    await ctx.send("\n".join(lines))


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
    """يضيف نقاط من العدم لرصيد صاحب الأمر — بس لصاحب رول Owner أو مالك السيرفر."""
    has_owner_role = isinstance(ctx.author, discord.Member) and has_role(ctx.author, [OWNER])
    is_guild_owner = ctx.guild is not None and ctx.author.id == ctx.guild.owner_id
    if not (has_owner_role or is_guild_owner):
        await ctx.send(f"{ctx.author.mention} ❌ ما عندك الصلاحية.")
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
        embed.set_footer(text=f"معرف العضو: {cached.author.id}")
        await send_log(cached.guild, "delete", embed)


# ============================================================
# 10) .اوامر
# ============================================================
# قائمة الأوامر: Embed بنفس قالب الـ AFK + أزرار أقسام. الرد يطلع مخفي (ephemeral) لمن يضغط الزر،
# وقسم الإدارة ما يشوفه إلا اللي معه رتبة إدارة (Trial Moderator وفوق) أو مالك السيرفر.
HELP_PUBLIC_SECTIONS = {
    "points": ("⭐ النقاط والاقتصاد", [
        "`.رصيد [@عضو]` — تشوف رصيدك أو رصيد عضو ثاني.",
        "`.نقاطي` — تشوف رصيد نقاطك.",
        "`.يومي` — تاخذ جائزتك اليومية (مرة كل 24 ساعة).",
        "`.تحويل @عضو المبلغ` — تحول نقاط لعضو ثاني.",
        "`.توب` — لوحة الصدارة، أعلى 10 لاعبين بالنقاط.",
        "`.سجلي [@عضو]` — عدد مرات الفوز والخسارة بالألعاب.",
        "`.متجر` — تشوف الأشياء المتوفرة بالمتجر.",
        "`.شراء <العنصر>` — تشتري شي من المتجر بنقاطك.",
    ]),
    "games": ("🎮 الألعاب", [
        "`.العاب` — قائمة كل الألعاب (الجماعية والفردية).",
        "`.شرح اسم_اللعبة` — شرح أي لعبة بالتفصيل.",
    ]),
    "info": ("🔎 معلومات", [
        "`.u [@عضو]` — معلومات الحساب.",
        "`.s` — معلومات السيرفر.",
        "`.r` — رتب السيرفر.",
        "`.a [@عضو]` — صورة الحساب (الافتار).",
    ]),
    "general": ("ℹ️ عام", [
        "`.تحذيراته [@عضو]` — تشوف عدد التحذيرات المسجلة على عضو (أو عليك).",
        "`.قول <النص>` — يحذف رسالتك والبوت يكتب النص عنك.",
        "`.اوامر` — تعرض هذي القائمة.",
    ]),
}

# (المفتاح, النص, الايموجي, لون الزر)
HELP_BUTTONS = [
    ("points", "النقاط", "⭐", discord.ButtonStyle.secondary),
    ("games", "الألعاب", "🎮", discord.ButtonStyle.secondary),
    ("info", "معلومات", "🔎", discord.ButtonStyle.secondary),
    ("general", "عام", "ℹ️", discord.ButtonStyle.secondary),
    ("admin", "الإدارة", "🛡️", discord.ButtonStyle.danger),
]


def _help_embed(title: str, description: str, user) -> discord.Embed:
    """نفس قالب رسالة AFK: عنوان + وصف + صورة جنب + فوتر."""
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
        "أوامر الأعضاء كلها تبدأ بـ `.`\n"
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
        await ctx.send("⚠️ الصيغة: `.قول النص اللي تبيه`")
        return
    # عشان ما أحد يستغل البوت يتجاوز حماية الروابط
    if ctx.guild is not None and message_has_blocked_link(text) and not is_link_exempt(ctx.author):
        await ctx.send(f"{ctx.author.mention} ❌ ما أقدر أرسل روابط.")
        return
    # (حذف رسالة صاحب الأمر يتم بأول on_message عشان يختفي بأسرع وقت)
    # بدون منشنات (ما يمشي @everyone ولا @here ولا منشن رتب/أعضاء)
    await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())


# ============================================================
# 11) نظام الإدارة الكامل — بدون بريفكس، حسب الرتب
# ============================================================
OWNER = "Owner"
CO_OWNER = "Co-Owner"
VICE_OWNER = "Vice Owner"
ADMIN = "Admin"
MANAGEMENT = "Management"
HEAD_MOD = "Head Moderator"
MODERATOR = "Moderator"
TRIAL_MOD = "Trial Moderator"

TOP_ROLES = [VICE_OWNER, CO_OWNER, OWNER]
ADMIN_ROLES = [ADMIN] + TOP_ROLES
MANAGEMENT_ROLES = [MANAGEMENT] + ADMIN_ROLES
HEAD_MOD_ROLES = [HEAD_MOD] + MANAGEMENT_ROLES
MOD_ROLES = [MODERATOR] + HEAD_MOD_ROLES
TRIAL_ROLES = [TRIAL_MOD] + MOD_ROLES


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
    await message.channel.send(text)


# ---------- إدارة الأعضاء ----------
# ملاحظة: أوامر العقوبات (برا / ترحيل / تايم / اخرس / سجن / تنزيل / اصمت / بره / اطلع)
# لو ما كتبت فيها سبب، البوت يطلع لك أزرار أسباب تختار منها (ولو كتبت السبب ينفذ مباشرة).
async def cmd_ban(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `برا @العضو السبب`")
        return
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "حظر", "🔨")
    if reason is None:
        return
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
    reason = await get_reason(message, args, target, "طرد", "👢")
    if reason is None:
        return
    try:
        await target.kick(reason=reason)
        await reply(message, f"👢 تم طرد {target.mention} — السبب: {reason}")
        await log_mod_action(message.guild, "👢 طرد عضو", message.author, target, reason)
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أطرد هذا العضو.")

async def cmd_timeout(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تايم @العضو 10m السبب` (افتراضي 10 دقائق)")
        return
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
        return
    try:
        await target.timeout(discord.utils.utcnow() + duration, reason=reason)
        await reply(message, f"⏱️ تم إعطاء {target.mention} تايم لمدة {duration} — السبب: {reason}")
        await log_mod_action(message.guild, "⏱️ تايم (كتم مؤقت)", message.author, target, reason,
                              {"المدة": str(duration)})
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أعطي هذا العضو تايم.")


async def cmd_untimeout(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تحرير @العضو`")
        return
    target = message.mentions[0]
    await target.timeout(None, reason=f"بواسطة {message.author}")
    await reply(message, f"✅ تم فك التايم عن {target.mention}")
    await log_mod_action(message.guild, "✅ فك تايم", message.author, target)


async def cmd_textmute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `اخرس @العضو`")
        return
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "إسكات بالشات", "🔇")
    if reason is None:
        return
    role = await ensure_role(message.guild, MUTE_ROLE_NAME)
    await target.add_roles(role, reason=f"بواسطة {message.author} — {reason}")
    await reply(message, f"🔇 تم إسكات {target.mention} بالشات — السبب: {reason}")
    await log_mod_action(message.guild, "🔇 إسكات بالشات", message.author, target, reason)


async def cmd_textunmute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تكلم @العضو`")
        return
    target = message.mentions[0]
    role = discord.utils.get(message.guild.roles, name=MUTE_ROLE_NAME)
    if role and role in target.roles:
        await target.remove_roles(role, reason=f"بواسطة {message.author}")
    await reply(message, f"🔊 تم فك الإسكات عن {target.mention}")
    await log_mod_action(message.guild, "🔊 فك إسكات بالشات", message.author, target)


async def cmd_jail(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `سجن @العضو`")
        return
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "سجن", "🔒")
    if reason is None:
        return
    jail_role = await ensure_role(message.guild, JAIL_ROLE_NAME)

    keep_roles = [r for r in target.roles if r.name != "@everyone"]
    data = load_json(JAIL_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    data.setdefault(gid, {})
    data[gid][mid] = [r.id for r in keep_roles]
    save_json(JAIL_FILE, data)

    try:
        await target.remove_roles(*keep_roles, reason="سجن")
        await target.add_roles(jail_role, reason=f"سجن بواسطة {message.author} — {reason}")
        await reply(message, f"🔒 تم سجن {target.mention} — السبب: {reason}")
        await log_mod_action(message.guild, "🔒 سجن عضو", message.author, target, reason)
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أسجن هذا العضو.")


async def cmd_unjail(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `فك @العضو`")
        return
    target = message.mentions[0]
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
        await reply(message, "⚠️ الصيغة: `لقب @العضو [الاسم_الجديد]` (بدون اسم يرجع اسمه الأصلي)")
        return
    target = message.mentions[0]
    new_nick = strip_mentions(args, message.mentions)
    if not new_nick:
        # بدون اسم جديد: نشيل اللقب ويرجع اسمه الأصلي
        try:
            await target.edit(nick=None, reason=f"بواسطة {message.author} — إرجاع الاسم الأصلي")
            await reply(message, f"✏️ تم إرجاع اسم {target.mention} الأصلي.")
        except discord.Forbidden:
            await reply(message, "❌ ما أقدر أغيّر لقب هذا العضو.")
        return
    try:
        await target.edit(nick=new_nick, reason=f"بواسطة {message.author}")
        await reply(message, f"✏️ تم تغيير لقب {target.mention} إلى **{new_nick}**")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أغيّر لقب هذا العضو.")


async def cmd_remove_role(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `تنزيل @العضو اسم الرتبة` (اكتب اسم الرتبة بدون @ عشان ما ينزعج أصحابها)")
        return
    target = message.mentions[0]
    if message.role_mentions:
        role = message.role_mentions[0]
    else:
        role_text = strip_mentions(args, message.mentions)
        role = find_role_from_text(message.guild, role_text)
        if role is None:
            await reply(message, "⚠️ ما لقيت رتبة بهذا الاسم — اكتب اسمها بالضبط أو الآيدي.")
            return
    if role not in target.roles:
        await reply(message, f"⚠️ {target.mention} أصلًا ما عنده رتبة {role.name}")
        return
    # اسم الرتبة ياخذ نص الأمر كله، فالسبب دايمًا من الأزرار
    reason = await ask_reason(message, target, f"سحب رتبة {role.name}", "📤")
    if reason is None:
        return
    await target.remove_roles(role, reason=f"بواسطة {message.author} — {reason}")
    data = load_json(ROLES_REMOVED_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    data.setdefault(gid, {})
    data[gid][mid] = role.id
    save_json(ROLES_REMOVED_FILE, data)
    await reply(message, f"📤 تم سحب رتبة {role.name} من {target.mention} — السبب: {reason}")
    await log_mod_action(message.guild, "📤 سحب رتبة", message.author, target, reason, {"الرتبة": role.name})


async def cmd_restore_role(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `رجع @العضو`")
        return
    target = message.mentions[0]
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


async def cmd_give_role(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `رول @العضو اسم الرتبة` (اكتب اسم الرتبة بدون @ عشان ما ينزعج أصحابها)")
        return
    target = message.mentions[0]
    if message.role_mentions:
        role = message.role_mentions[0]
    else:
        role_text = strip_mentions(args, message.mentions)
        role = find_role_from_text(message.guild, role_text)
        if role is None:
            await reply(message, "⚠️ ما لقيت رتبة بهذا الاسم — اكتب اسمها بالضبط أو الآيدي.")
            return
    author = message.author
    if role.is_default():
        await reply(message, "❌ هذي الرتبة ما تنعطى.")
        return
    if role in target.roles:
        await reply(message, f"⚠️ {target.mention} عنده رتبة {role.name} أصلًا")
        return
    # ما أحد يعطي رتبة أعلى من رتبته أو مساوية لها (إلا مالك السيرفر)
    if author.id != message.guild.owner_id and role >= author.top_role:
        await reply(message, "❌ ما تقدر تعطي رتبة أعلى من رتبتك أو مساوية لها.")
        return
    try:
        await target.add_roles(role, reason=f"بواسطة {author}")
        await reply(message, f"📥 تم إعطاء {target.mention} رتبة {role.name}")
    except discord.Forbidden:
        await reply(message, "❌ ما أقدر أعطي هذي الرتبة (رتبتي أقل منها).")


# ---------- إدارة الرومات ----------
async def cmd_purge(message: discord.Message, args: str):
    amount_text = args.strip().split()[0] if args.strip() else "50"
    amount = int(amount_text) if amount_text.isdigit() else 50
    amount = min(amount, 200)
    try:
        await message.delete()  # يحذف رسالة الأمر نفسها
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass
    deleted = await message.channel.purge(limit=amount, before=message)
    await message.channel.send(f"🧹 تم حذف {len(deleted)} رسالة.", delete_after=7)
    await log_mod_action(message.guild, "🧹 مسح جماعي", message.author, None, None,
                          {"العدد": str(len(deleted)), "الروم": message.channel.mention})


async def cmd_lock(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.send_messages = False
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("🔒 تم قفل الروم.")


async def cmd_unlock(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.send_messages = None
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("🔓 تم فتح الروم.")


async def cmd_hide(message: discord.Message, args: str):
    overwrite = message.channel.overwrites_for(message.guild.default_role)
    overwrite.view_channel = False
    await message.channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await message.channel.send("🙈 تم إخفاء الروم.")


async def cmd_show(message: discord.Message, args: str):
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
    if target.voice and target.voice.channel:
        reason = await get_reason(message, args, target, "إخراج من الروم الصوتي", "👋")
        if reason is None:
            return
        await target.move_to(None, reason=f"بواسطة {message.author} — {reason}")
        await reply(message, f"👋 تم إخراج {target.mention} من الروم الصوتي — السبب: {reason}")
        await log_mod_action(message.guild, "👋 إخراج من الروم الصوتي", message.author, target, reason)
    else:
        await reply(message, "⚠️ العضو مو بروم صوتي.")


async def cmd_vc_mute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `اصمت @العضو`")
        return
    target = message.mentions[0]
    reason = await get_reason(message, args, target, "إسكات صوتي", "🔇")
    if reason is None:
        return
    await target.edit(mute=True, reason=f"بواسطة {message.author} — {reason}")
    await reply(message, f"🔇 تم إسكات {target.mention} صوتيًا — السبب: {reason}")
    await log_mod_action(message.guild, "🔇 إسكات صوتي", message.author, target, reason)


async def cmd_vc_unmute(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `انطق @العضو`")
        return
    target = message.mentions[0]
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
    if not (target.voice and target.voice.channel):
        await reply(message, "⚠️ العضو مو داخل روم صوتي.")
        return
    channel = target.voice.channel
    reason = await get_reason(message, args, target, "طرد من الصوت وقفل الروم", "🚫")
    if reason is None:
        return
    await target.move_to(None, reason=f"بواسطة {message.author} — {reason}")
    overwrite = channel.overwrites_for(message.guild.default_role)
    overwrite.connect = False
    await channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await reply(message, f"🚫 تم طرد {target.mention} وقفل روم {channel.name} — السبب: {reason}")
    await log_mod_action(message.guild, "🚫 طرد من الصوت وقفل الروم", message.author, target, reason,
                          {"الروم": channel.name})


async def cmd_vc_open(message: discord.Message, args: str):
    """فتح_صوتي ← يفتح الروم الصوتي اللي أنت فيه (يشيل القفل اللي حطه أمر اطلع)."""
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل الروم الصوتي عشان تفتحه.")
        return
    channel = message.author.voice.channel
    overwrite = channel.overwrites_for(message.guild.default_role)
    overwrite.connect = None  # يرجع للوضع الافتراضي (يشيل المنع)
    await channel.set_permissions(message.guild.default_role, overwrite=overwrite)
    await reply(message, f"🔓 تم فتح روم {channel.name} للكل.")
    await log_mod_action(message.guild, "🔓 فتح روم صوتي", message.author, None, None,
                          {"الروم": channel.name})


async def cmd_vc_allow(message: discord.Message, args: str):
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `مسموح @العضو` (وأنت داخل الروم الصوتي)")
        return
    if not (message.author.voice and message.author.voice.channel):
        await reply(message, "⚠️ لازم تكون داخل الروم الصوتي المقفول عشان تسمح لأحد.")
        return
    target = message.mentions[0]
    channel = message.author.voice.channel
    overwrite = channel.overwrites_for(target)
    overwrite.connect = True
    await channel.set_permissions(target, overwrite=overwrite)
    await reply(message, f"✅ تم السماح لـ {target.mention} بدخول {channel.name}")


async def cmd_remove_warn(message: discord.Message, args: str):
    """شيل تحذير @عضو  ← يشيل آخر تحذير | شيل تحذير @عضو الكل  ← يشيل كل تحذيراته."""
    if not message.mentions:
        await reply(message, "⚠️ الصيغة: `شيل تحذير @العضو` (يشيل آخر تحذير) أو `شيل تحذير @العضو الكل`")
        return
    target = message.mentions[0]
    if target.id == message.author.id:
        await reply(message, f"{message.author.mention} ⚠️ ما تقدر تشيل تحذير عن نفسك.")
        return
    remove_all = strip_mentions(args, message.mentions).strip() in ("الكل", "كل", "all")

    data = load_json(WARNS_FILE)
    gid, mid = str(message.guild.id), str(target.id)
    user_warns = data.get(gid, {}).get(mid, [])
    if not user_warns:
        await reply(message, f"⚠️ {target.mention} ما عليه أي تحذير.")
        return

    if remove_all:
        removed_count = len(user_warns)
        data[gid][mid] = []
        text = f"✅ تم حذف كل تحذيرات {target.mention} (**{removed_count}**)."
    else:
        removed = user_warns.pop()
        data[gid][mid] = user_warns
        text = (f"✅ تم حذف التحذير رقم **#{removed.get('number', len(user_warns) + 1)}** عن {target.mention}"
                f" — باقي عليه **{len(user_warns)}** تحذير.")
    save_json(WARNS_FILE, data)
    await reply(message, text)
    await log_mod_action(message.guild, "🧹 إزالة تحذير", message.author, target,
                         extra={"المحذوف": "الكل" if remove_all else "آخر تحذير",
                                "المتبقي": len(data[gid][mid])})


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

# رتّب المفاتيح الأطول أولًا (عشان "كم هير بيبي" ما تتعارض مع كلمة مفردة)
SORTED_TRIGGERS = sorted(ADMIN_COMMANDS.keys(), key=len, reverse=True)


async def try_dispatch_admin_command(message: discord.Message) -> bool:
    content = message.content.strip()
    for trigger in SORTED_TRIGGERS:
        if content == trigger or content.startswith(trigger + " "):
            allowed_roles, handler = ADMIN_COMMANDS[trigger]
            if not isinstance(message.author, discord.Member) or not has_role(message.author, allowed_roles):
                await reply(message, f"{message.author.mention} ❌ ما عندك صلاحية لهذا الأمر.")
                return True
            args = content[len(trigger):].strip()
            await handler(message, args)
            return True
    return False


# ---------- .اوامر اداريه: قائمة الأوامر الإدارية مع الرتب المسموح لها ----------
# كل عنصر: (المفاتيح بجدول ADMIN_COMMANDS, طريقة الكتابة, الوصف, نص الرتبة أو None لو تنحسب تلقائيًا)
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
        (["رجع"], "رجع @عضو", "إرجاع آخر رتبة انسحبت من العضو.", None),
        (["رول"], "رول @عضو اسم_الرتبة", "إعطاء رتبة لعضو (بشرط تكون أقل من رتبتك).", None),
        (["تحذير"], "تحذير @عضو [السبب]", "تسجيل تحذير رسمي على عضو، وتطلع لك أزرار أسباب تختار منها.",
         f"أي إداري (**{TRIAL_MOD}** وأعلى)"),
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
    hierarchy = " ➜ ".join(TRIAL_ROLES)
    embeds = [discord.Embed(
        title="📋 الأوامر الإدارية",
        description=(
            "الأوامر الإدارية تنكتب **بدون نقطة** (مثال: `تايم @عضو 10m`).\n"
            "الرتبة المكتوبة تحت كل أمر هي **أقل رتبة** تقدر تستخدمه، وكل الرتب الأعلى منها تقدر تستخدمه بعد.\n"
            "لو ما كتبت سبب بأوامر العقوبات، يطلع لك البوت أزرار أسباب تختار منها.\n\n"
            f"**ترتيب الرتب من الأدنى للأعلى:**\n{hierarchy}"
        ),
        color=discord.Color.blurple(),
    )]
    for title, entries in ADMIN_HELP_SECTIONS:
        lines = []
        for triggers, usage, desc, roles_text in entries:
            if roles_text is None:
                roles_text = f"**{ADMIN_COMMANDS[triggers[0]][0][0]}** وأعلى"
            lines.append(f"`{usage}`\n{desc}\n🔑 الرتبة: {roles_text}\n")
        embeds.append(discord.Embed(title=title, description="\n".join(lines), color=discord.Color.blurple()))
    return embeds


@bot.command(name="اوامر_اداريه")
async def send_admin_commands_help(ctx: commands.Context):
    author = ctx.author
    is_guild_owner = ctx.guild is not None and author.id == ctx.guild.owner_id
    if not (isinstance(author, discord.Member) and (is_guild_owner or has_role(author, TRIAL_ROLES))):
        await ctx.send(f"{author.mention} ❌ ما عندك الصلاحية.")
        return

    await ctx.send(embeds=build_admin_help_embeds())


# ============================================================
# 12) المتجر — شراء أشياء بالنقاط
# ============================================================
# ألوان جاهزة للرتب المؤقتة اللي يشتريها اللاعبين. غيّر الأسماء أو الألوان زي ما تبي.
# ملاحظة: عشان اللون يبان فعليًا بقائمة الأعضاء، لازم ترفع هذي الرتب (بعد ما البوت ينشئها أول مرة)
# لمكان أعلى من رتب الأعضاء العادية بترتيب رتب السيرفر يدويًا.
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

SHOP_ITEMS_TEXT = (
    "🛍️ **المتجر**\n\n"
    f"🎭 **لقب مؤقت** — {SHOP_TITLE_PRICE} نقطة ({SHOP_TITLE_DURATION_HOURS} ساعة)\n"
    "الشراء: `.شراء لقب النص_اللي_تبيه`\n\n"
    f"🎨 **لون رول مؤقت** — {SHOP_COLOR_PRICE} نقطة ({SHOP_COLOR_DURATION_HOURS} ساعة)\n"
    f"الألوان المتوفرة: {'، '.join(SHOP_COLOR_ROLES)}\n"
    "الشراء: `.شراء لون اسم_اللون`\n\n"
    f"🧹 **حذف تنبيه** — {SHOP_WARN_CLEAR_PRICE} نقطة\n"
    "يشيل أقدم تنبيه مسجل عليك.\n"
    "الشراء: `.شراء تنظيف`"
)


@bot.command(name="متجر")
async def shop_cmd(ctx: commands.Context):
    await ctx.send(SHOP_ITEMS_TEXT)


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


@bot.command(name="شراء")
async def buy_cmd(ctx: commands.Context, item: str = None, *, extra_text: str = None):
    if not item:
        await ctx.send("⚠️ اكتب `.متجر` عشان تشوف الأشياء المتوفرة، وبعدها `.شراء <العنصر>`")
        return
    item = item.strip()
    author = ctx.author
    balance = get_balance(ctx.guild.id, author.id)

    if item == "لقب":
        price = SHOP_TITLE_PRICE
        if not extra_text or not extra_text.strip():
            await ctx.send("⚠️ الصيغة: `.شراء لقب النص_اللي_تبيه`")
            return
        title_text = extra_text.strip()
        if balance < price:
            await ctx.send(f"❌ رصيدك ما يكفي (تحتاج {price} نقطة).")
            return
        old_entry = _shop_clear_active(ctx.guild.id, author.id)
        original_nick = (old_entry.get("original_nick")
                         if (old_entry and old_entry.get("type") == "title") else author.nick)
        new_nick = f"{original_nick or author.name} | {title_text}"[:32]
        try:
            await author.edit(nick=new_nick, reason="شراء لقب مؤقت من المتجر")
        except discord.Forbidden:
            await ctx.send("❌ ما أقدر أغيّر لقبك (رتبتك أعلى من رتبتي أو ناقصني صلاحية).")
            return
        add_balance(ctx.guild.id, author.id, -price)
        _shop_set_active(ctx.guild.id, author.id, "title", SHOP_TITLE_DURATION_HOURS,
                          {"original_nick": original_nick})
        await ctx.send(f"✅ تم! لقبك الحين **{new_nick}** لمدة {SHOP_TITLE_DURATION_HOURS} ساعة.")

    elif item == "لون":
        price = SHOP_COLOR_PRICE
        color_name = (extra_text or "").strip()
        if color_name not in SHOP_COLOR_ROLES:
            options = "، ".join(SHOP_COLOR_ROLES)
            await ctx.send(f"⚠️ الصيغة: `.شراء لون اسم_اللون`\nالألوان المتوفرة: {options}")
            return
        if balance < price:
            await ctx.send(f"❌ رصيدك ما يكفي (تحتاج {price} نقطة).")
            return
        for name in SHOP_COLOR_ROLES:
            old_role = discord.utils.get(ctx.guild.roles, name=f"🎨 {name}")
            if old_role and old_role in author.roles:
                await author.remove_roles(old_role, reason="تبديل لون المتجر")
        role_name = f"🎨 {color_name}"
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role is None:
            role = await ctx.guild.create_role(
                name=role_name, color=discord.Color(SHOP_COLOR_ROLES[color_name]),
                reason="رتبة لون من المتجر - إنشاء تلقائي")
        try:
            await author.add_roles(role, reason="شراء لون من المتجر")
        except discord.Forbidden:
            await ctx.send("❌ ما أقدر أعطيك هذي الرتبة (رتبتها أعلى من رتبة البوت — رتّبها بإعدادات السيرفر).")
            return
        add_balance(ctx.guild.id, author.id, -price)
        _shop_set_active(ctx.guild.id, author.id, "color", SHOP_COLOR_DURATION_HOURS, {"role_id": role.id})
        await ctx.send(f"✅ تم! صار لونك **{color_name}** لمدة {SHOP_COLOR_DURATION_HOURS} ساعة.")

    elif item == "تنظيف":
        price = SHOP_WARN_CLEAR_PRICE
        warns_data = load_json(WARNS_FILE)
        gid, uid = str(ctx.guild.id), str(author.id)
        user_warns = warns_data.get(gid, {}).get(uid, [])
        if not user_warns:
            await ctx.send("⚠️ ما عندك أي تنبيه تحذفه.")
            return
        if balance < price:
            await ctx.send(f"❌ رصيدك ما يكفي (تحتاج {price} نقطة).")
            return
        user_warns.pop(0)
        warns_data[gid][uid] = user_warns
        save_json(WARNS_FILE, warns_data)
        add_balance(ctx.guild.id, author.id, -price)
        await ctx.send(f"✅ تم حذف أقدم تنبيه عندك. باقي عندك **{len(user_warns)}** تنبيه.")

    else:
        await ctx.send("⚠️ ما لقيت هذا العنصر، اكتب `.متجر` عشان تشوف الأشياء المتوفرة.")


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
# 12.5) أوامر المعلومات السريعة — .u (يوزر) / .s (سيرفر) / .r (رتب) / .a (افتار)
# ============================================================
VERIFICATION_NAMES_AR = {"none": "بدون", "low": "منخفض", "medium": "متوسط", "high": "عالي", "highest": "أعلى مستوى"}


def _ts(dt: datetime, style: str = "F") -> str:
    """يحول وقت لتنسيق ديسكورد (يتحول تلقائيًا لتوقيت اللي يشوفه)."""
    return f"<t:{int(dt.timestamp())}:{style}>"


def _join_limited(items: list[str], limit: int = 1000, sep: str = " ") -> str:
    """يجمع عناصر بنص واحد ما يتعدى limit حرف، وإذا زاد يقطع ويكتب كم عنصر انحذف."""
    out, used = [], 0
    for i, item in enumerate(items):
        extra = len(item) + (len(sep) if out else 0)
        if used + extra > limit - 20:
            out.append(f"... و{len(items) - i} أخرى")
            break
        out.append(item)
        used += extra
    return sep.join(out)


@bot.command(name="u")
async def user_info_cmd(ctx: commands.Context, member: discord.Member = None):
    """.u [@عضو] — معلومات الحساب."""
    if ctx.guild is None:
        return
    member = member or ctx.author
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
    roles = [r for r in reversed(member.roles) if r != ctx.guild.default_role]
    embed.add_field(name="أعلى رتبة", value=roles[0].mention if roles else "لا يوجد", inline=True)
    embed.add_field(name=f"الرتب ({len(roles)})",
                    value=_join_limited([r.mention for r in roles]) if roles else "لا يوجد", inline=False)
    embed.set_footer(text=f"طلب بواسطة {ctx.author.display_name}")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="s")
async def server_info_cmd(ctx: commands.Context):
    """.s — معلومات السيرفر."""
    guild = ctx.guild
    if guild is None:
        return
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
    embed.set_footer(text=f"طلب بواسطة {ctx.author.display_name}")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="r")
async def roles_info_cmd(ctx: commands.Context):
    """.r — كل رتب السيرفر (من الأعلى للأدنى) مع عدد أعضاء كل رتبة."""
    guild = ctx.guild
    if guild is None:
        return
    roles = [r for r in reversed(guild.roles) if r != guild.default_role]
    if not roles:
        await ctx.send("⚠️ ما فيه رتب بهذا السيرفر.")
        return
    lines = [f"{r.mention} — **{len(r.members)}**" for r in roles]
    embed = discord.Embed(title=f"🎭 رتب السيرفر ({len(roles)})", color=discord.Color.blurple(),
                          description=_join_limited(lines, limit=4000, sep="\n"))
    embed.set_footer(text="الرقم = عدد الأعضاء بالرتبة")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="a")
async def avatar_cmd(ctx: commands.Context, member: discord.Member = None):
    """.a [@عضو] — صورة الحساب بحجم كبير."""
    if ctx.guild is None:
        return
    member = member or ctx.author
    avatar = member.display_avatar
    formats = ["png", "jpg", "webp"] + (["gif"] if avatar.is_animated() else [])
    links = " • ".join(f"[{f.upper()}]({avatar.with_format(f).with_size(1024).url})" for f in formats)
    embed = discord.Embed(title=f"🖼️ صورة {member.display_name}", description=links, color=discord.Color.blurple())
    embed.set_image(url=avatar.with_size(1024).url)
    if member.guild_avatar:
        embed.set_footer(text="هذي صورته الخاصة بالسيرفر")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


# ============================================================
# 13) نظام AFK — .afk <السبب>
# ============================================================
# لما العضو يكتب .afk نايم يتسجل AFK بالسبب، ولما يرسل أي رسالة ثانية يرجع تلقائيًا.
# ولو أحد منشنه وهو AFK، البوت يعلمه إنه AFK ويعرض السبب.
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


async def handle_afk_on_message(message: discord.Message) -> None:
    """لو صاحب الرسالة AFK نرجّعه، ولو منشن أحد AFK نعلمه. ما يتدخل بأمر .afk نفسه."""
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

    for member in message.mentions:
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
# المعفيين: مالك السيرفر، أصحاب صلاحية Administrator، وأي أحد معه رتبة من Trial Moderator وفوق.
# الدومينات المسموحة (ما ينعاقب عليها): روابط الصور/الملفات الداخلية بديسكورد وروابط الـGIF.
# تقدر تزيد أو تشيل منها. وتقدر تحط آيديات رومات مسموح فيها الروابط بـ LINK_ALLOWED_CHANNEL_IDS.
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
# يلقط: السلام عليكم / سلام عليكم / السلام عليك / سلامو عليكم / السلام عليكم ورحمة الله / ...ورحمة الله وبركاته
# ويتجاهل "وعليكم السلام" عشان ما يرد على الردود.
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
# الروم: أي روم اسمه فيه "ممنوع-الارسال" (يتحمل الهمزة والمسافات والشرطات، مثل: 🚫｜ممنوع_الإرسال).
# الإداريين (Trial Moderator وفوق) ومالك السيرفر وأصحاب Administrator ما يتبندون لو كتبوا فيه (احتياط من الغلط).
# لو تبي حتى الإداريين يتبندون غيّر TRAP_EXEMPT_STAFF إلى False (والبوت أصلًا ما يقدر يبند رتبة أعلى منه).
TRAP_CHANNEL_NAME = "ممنوع-الارسال"
TRAP_EXEMPT_STAFF = True
TRAP_DELETE_SECONDS = 3600   # يمسح رسائل العضو من آخر ساعة (يفيد لو الحساب مخترق وينشر سبام)


def is_trap_channel(channel) -> bool:
    name = getattr(channel, "name", "") or ""
    cleaned = normalize(name.replace("_", "-").replace(" ", "-"))
    return normalize(TRAP_CHANNEL_NAME) in cleaned


async def handle_trap_message(message: discord.Message) -> bool:
    """يبند اللي أرسل برسالة بروم الفخ. يرجع True لو تعامل مع الرسالة (يعني ما نكمل بقية المعالجة)."""
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
            await guild.ban(author, reason=reason)  # نسخة discord.py قديمة ما تدعم delete_message_seconds
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
# أي رسالة فيها صورة بهذي الرومات يحط عليها البوت رياكشن (بدون رد).
# الرسائل اللي بدون صور يتجاهلها.
# غيّر الإيموجيات من REACTION_EMOJIS (تقدر تحط أكثر من واحد).
REACTION_CHANNEL_NAMES = ["locket", "streaks"]
REACTION_EMOJIS = ["💥", "🔥", "⛔", "😼"]
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic")


def is_reaction_channel(channel) -> bool:
    name = (getattr(channel, "name", "") or "").lower().replace("_", "-")
    return any(target in name for target in REACTION_CHANNEL_NAMES)


def message_has_image(message: discord.Message) -> bool:
    for att in message.attachments:
        if (att.content_type or "").startswith("image/"):
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

    # ".قول <نص>": نحذف رسالة صاحب الأمر فورًا (قبل أي معالجة ثانية) عشان ما أحد يلحق يشوفها.
    # نفس شروط say_cmd: لازم يكون فيه نص، وما نحذف لو النص فيه رابط ممنوع (البوت بيرفض الإرسال).
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

    # نصفّي المنشنات: لو المستخدم بس رادّ (Reply) على حد بدون ما يكتب @اسمه صراحة،
    # ما نعتبره منشن — عشان "تايم"/"برا"/... ما تنفذ غلط بمجرد الرد على رسالة الشخص.
    message.mentions = filter_explicit_mentions(message)

    # نظام AFK: رجوع تلقائي لصاحب الرسالة + تنبيه لو منشنوا أحد AFK
    await handle_afk_on_message(message)

    # رياكشن على الصور برومات locket / streaks
    await handle_image_reaction(message)

    # رد السلام
    if message.guild is not None and is_salam_message(message.content):
        try:
            await message.reply(SALAM_REPLY, mention_author=False)
        except (discord.Forbidden, discord.HTTPException):
            pass

    if WARN_COMMAND_PATTERN.match(message.content.strip()):
        await handle_warn_command(message)
        return

    if await try_dispatch_admin_command(message):
        return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول باسم {bot.user}")
    if not shop_expiry_task.is_running():
        shop_expiry_task.start()
    for guild in bot.guilds:
        embed = discord.Embed(title="✅ البوت اشتغل", color=discord.Color.green(),
                               timestamp=datetime.now(timezone.utc))
        await send_log(guild, "bot", embed)


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


# ============================================================
# ترحيب الأعضاء الجدد — صورة الترحيب (افتار العضو داخل الدائرة) + المنشن + الرسالة + عدد الأعضاء
# ============================================================
# يرسل بروم اسمه فيه "welcome" أو "ترحيب" (وإذا ما لقاه يستخدم روم رسائل النظام بالسيرفر لو موجود).
# ملف الصورة welcome.png لازم يكون بجنب ملف البوت (نفس مكان مجلد game_images).
WELCOME_CHANNEL_NAMES = ["welcome", "ترحيب"]
WELCOME_IMAGE_PATH = "welcome.png"
WELCOME_CIRCLE_CENTER = (1342, 422)   # مركز الدائرة الفاضية بالصورة (بالبكسل)
WELCOME_CIRCLE_RADIUS = 153           # نصف قطر الافتار (أصغر شوي من إطار الدائرة عشان الإطار يبقى ظاهر)
WELCOME_RULES_CHANNEL_ID = 1538291493779935333   # القوانين
WELCOME_NEWS_CHANNEL_ID = 1550669151339683862    # الأخبار
WELCOME_MAP_CHANNEL_ID = 1541934638883143831     # الخريطة


def find_welcome_channel(guild: discord.Guild) -> discord.TextChannel | None:
    for ch in guild.text_channels:
        name = ch.name.lower().replace("_", "-")
        if any(target in name for target in WELCOME_CHANNEL_NAMES):
            return ch
    return guild.system_channel


def build_welcome_image(avatar_bytes: bytes) -> BytesIO:
    """يلصق افتار العضو (دائري) داخل الدائرة الفاضية بصورة الترحيب ويرجع الصورة النهائية PNG."""
    resample = getattr(Image, "Resampling", Image).LANCZOS
    base = Image.open(WELCOME_IMAGE_PATH).convert("RGBA")
    cx, cy = WELCOME_CIRCLE_CENTER
    radius = WELCOME_CIRCLE_RADIUS
    size = radius * 2
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), resample)
    # نحط الافتار فوق خلفية غامقة عشان لو فيه شفافية ما تبان غلط
    backdrop = Image.new("RGBA", (size, size), (28, 30, 40, 255))
    backdrop.alpha_composite(avatar)
    avatar = backdrop
    # قناع دائري بحواف ناعمة (نرسمه أكبر ونصغره)
    scale = 4
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=255)
    mask = mask.resize((size, size), resample)
    base.paste(avatar, (cx - radius, cy - radius), mask)
    out = BytesIO()
    base.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


@bot.listen("on_member_join")
async def welcome_new_member(member: discord.Member):
    if member.bot:
        return
    channel = find_welcome_channel(member.guild)
    if channel is None:
        return

    lines = [
        "• نورت السيرفر !",
        f"• لتجنب العقوبات، توجه إلى روم: ⟸ <#{WELCOME_RULES_CHANNEL_ID}>",
        f"• للاطلاع على آخر الأخبار، توجه إلى روم: ⟸ <#{WELCOME_NEWS_CHANNEL_ID}>",
        f"• لمعرفة أقسام السيرفر، توجه إلى روم: ⟸ <#{WELCOME_MAP_CHANNEL_ID}>",
        "",
        f"👥 عدد الأشخاص بالسيرفر: **{member.guild.member_count}**",
    ]
    embed = discord.Embed(description="\n".join(lines), color=discord.Color.from_rgb(139, 125, 190))

    file = None
    if PIL_AVAILABLE and os.path.exists(WELCOME_IMAGE_PATH):
        try:
            avatar_bytes = await member.display_avatar.replace(size=512, format="png").read()
            buf = await asyncio.to_thread(build_welcome_image, avatar_bytes)
            file = discord.File(buf, filename="welcome.png")
            embed.set_image(url="attachment://welcome.png")
        except Exception as e:
            print(f"[Welcome] ما قدرت أسوي صورة الترحيب: {e}")
            file = None
    if file is None:
        embed.set_thumbnail(url=member.display_avatar.url)  # بديل لو الصورة ما اشتغلت

    try:
        await channel.send(content=member.mention, embed=embed, file=file,
                           allowed_mentions=discord.AllowedMentions(users=[member]))
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"[Welcome] ما قدرت أرسل الترحيب بروم {channel.name}: {e}")


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
    embed = discord.Embed(title="📤 عضو خرج من السيرفر", color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=f"{member} ({member.mention})", inline=True)
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
    embed = discord.Embed(title="✅ تم فك حظر عن عضو", color=discord.Color.green(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=str(user), inline=True)
    if moderator:
        embed.add_field(name="بواسطة", value=moderator.mention, inline=True)
    embed.set_footer(text=f"معرف العضو: {user.id}")
    await send_log(guild, "ban", embed)


# ---------- لوقات الرتب ----------
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles == after.roles:
        return
    added = [r for r in after.roles if r not in before.roles]
    removed = [r for r in before.roles if r not in after.roles]
    if not added and not removed:
        return
    embed = discord.Embed(title="🎭 تعديل رتب عضو", color=discord.Color.blurple(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="العضو", value=after.mention, inline=False)
    if added:
        embed.add_field(name="➕ أضيفت", value="، ".join(r.mention for r in added), inline=False)
    if removed:
        embed.add_field(name="➖ أزيلت", value="، ".join(r.mention for r in removed), inline=False)
    embed.set_footer(text=f"معرف العضو: {after.id}")
    await send_log(after.guild, "role", embed)


# ---------- لوقات الرومات ----------
@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(title="➕ تم إنشاء روم", color=discord.Color.green(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الروم", value=getattr(channel, "mention", f"#{channel.name}"), inline=True)
    embed.set_footer(text=f"معرف الروم: {channel.id}")
    await send_log(channel.guild, "channel", embed)


@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(title="🗑️ تم حذف روم", color=discord.Color.red(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="الروم", value=f"#{channel.name}", inline=True)
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
    embed.set_footer(text=f"معرف الروم: {after.id}")
    await send_log(after.guild, "channel", embed)


# ---------- لوقات الصوت ----------
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel == after.channel:
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
    await send_log(after, "server", embed)


@bot.event
async def on_guild_emojis_update(guild, before, after):
    embed = discord.Embed(title="😀 تحديث إيموجيات السيرفر", color=discord.Color.gold(),
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="عدد الإيموجيات", value=f"{len(before)} ← {len(after)}")
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

    def do_HEAD(self):  # بعض مواقع المراقبة (زي UptimeRobot) تستخدم HEAD
        self._ok(body=False)

    def log_message(self, format, *args):  # يمنع سبام اللوق مع كل بينق
        return


def run_web_server():
    port = int(os.environ.get("PORT", 10000))  # Render يعطيك البورت بمتغير PORT
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
    web_thread.join(timeout=2)  # نعطيه فرصة يبدأ ويطبع حالته قبل لا نكمل
    if not web_thread.is_alive():
        print("[ويب سيرفر] ⚠️ الثريد وقف بسرعة غير طبيعية — راجع رسالة الخطأ فوق.")
    else:
        print("[ويب سيرفر] الثريد شغال بعد ثانيتين، الأغلب البورت فتح تمام.")

    bot.run(DISCORD_TOKEN)
