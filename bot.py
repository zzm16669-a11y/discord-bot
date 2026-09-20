import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()
  """
بوت ديسكورد شامل — نسخة كاملة مدموجة
=====================================================================
الأقسام:
  1) نظام التنبيهات (تنبيه)
  2) نظام الاقتصاد (رصيد / يومي / تحويل)
  3) الألعاب (اكسو، حجرة ورقة مقص، تخمين، روليت)
  4) نظام الإدارة الكامل (أعضاء / رومات / صوت) — بدون بريفكس، حسب الرتب

ملاحظات مهمة قبل التشغيل:
  - غيّر أسماء الرتب بالأسفل (ROLE NAMES) إذا كانت أسماء رتبك بالسيرفر
    مختلفة شوي عن الأسماء المكتوبة هنا (لازم تطابق بالضبط حرف بحرف).
  - لازم تسوي رتبتين يدويًا بالسيرفر عشان "سجن" و"اخرس" يشتغلوا صح:
        * رتبة اسمها بالضبط: Jailed  (احجب عنها كل الرومات إلا روم السجن)
        * رتبة اسمها بالضبط: Muted   (احجب عنها إرسال الرسائل بكل الرومات)
    لو ما كانت موجودة، البوت بينشئها تلقائيًا لكن بدون صلاحيات محجوبة —
    لازم تظبط صلاحياتها يدويًا من إعدادات السيرفر أول مرة.
"""

import discord
from discord.ext import commands
import aiohttp
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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


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


async def send_warn_log(target, moderator, reason, warn_number, channel_name):
    if not WARN_LOG_WEBHOOK_URL:
        return
    embed = {
        "title": "⚠️ تم تسجيل تنبيه رسمي",
        "color": 0xE67E22,
        "fields": [
            {"name": "العضو", "value": target.mention, "inline": True},
            {"name": "بواسطة", "value": moderator.mention, "inline": True},
            {"name": "رقم التنبيه", "value": f"#{warn_number}", "inline": True},
            {"name": "السبب", "value": reason or "لم يُذكر سبب", "inline": False},
            {"name": "القناة", "value": f"#{channel_name}", "inline": True},
        ],
        "footer": {"text": f"معرف العضو: {target.id}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if target.display_avatar:
        embed["thumbnail"] = {"url": target.display_avatar.url}
    payload = {"username": "نظام التنبيهات", "embeds": [embed]}
    async with aiohttp.ClientSession() as session:
        async with session.post(WARN_LOG_WEBHOOK_URL, json=payload) as resp:
            if resp.status not in (200, 204):
                print(f"[WarnSystem] فشل إرسال الويب هوك: {resp.status}")


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
    await send_warn_log(target, author, reason, warn_number, message.channel.name)
    await message.channel.send(f"✅ تسجل تنبيه رقم **#{warn_number}** بحق {target.mention}", delete_after=6)


@bot.command(name="تنبيهاته", aliases=["warns"])
async def show_warns(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    count = get_warn_count(ctx.guild.id, member.id)
    await ctx.send(f"📋 لدى {member.mention} **{count}** تنبيه/تنبيهات مسجلة.")


# ============================================================
# 2) نظام الاقتصاد
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
# 3) الألعاب
# ============================================================
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
    view = TicTacToeView(ctx.author, opponent)
    await ctx.send(f"🎮 **XO**: {ctx.author.mention} (X) ضد {opponent.mention} (O)\n🎯 دور {ctx.author.mention}", view=view)


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
    view = RPSView(ctx.author, opponent)
    await ctx.send(f"✂️ **حجرة ورقة مقص**: {ctx.author.mention} ضد {opponent.mention}\nكل واحد يضغط بالخفاء 👇", view=view)


active_guess_games: dict[int, dict] = {}


@bot.command(name="تخمين")
async def guess_start(ctx: commands.Context, max_number: int = 100):
    if ctx.channel.id in active_guess_games:
        await ctx.send("⚠️ فيه لعبة تخمين شغالة هنا.")
        return
    if max_number < 10:
        await ctx.send("⚠️ اختر رقم أقصى 10 أو أكثر.")
        return
    number = random.randint(1, max_number)
    active_guess_games[ctx.channel.id] = {"number": number, "max": max_number}
    await ctx.send(f"🔢 اخترت رقم سري بين **1** و **{max_number}**! اكتبوا تخمينكم.")


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


class RouletteLobbyView(discord.ui.View):
    """غرفة انتظار: أعضاء ينضمون بزر، والمضيف يبدأ اللعبة بزر."""

    def __init__(self, host: discord.Member):
        super().__init__(timeout=120)
        self.host = host
        self.players: list[discord.Member] = [host]

    def _status_text(self) -> str:
        names = "، ".join(m.mention for m in self.players)
        return (
            f"🎡 **لعبة الروليت — بانتظار اللاعبين**\n"
            f"منضمين ({len(self.players)}): {names}\n\n"
            f"اضغط 🎮 **انضمام** للدخول — أو المضيف {self.host.mention} يضغط ▶️ **بدء اللعبة** (لازم 3 لاعبين فأكثر)"
        )

    @discord.ui.button(label="🎮 انضمام", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.bot:
            await interaction.response.send_message("⚠️ البوتات ما تنلعب.", ephemeral=True)
            return
        if interaction.user in self.players:
            await interaction.response.send_message("✅ أنت منضم مسبقًا.", ephemeral=True)
            return
        self.players.append(interaction.user)
        await interaction.response.edit_message(content=self._status_text(), view=self)

    @discord.ui.button(label="▶️ بدء اللعبة", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.host:
            await interaction.response.send_message("⚠️ بس المضيف يقدر يبدأ اللعبة.", ephemeral=True)
            return
        if len(self.players) < 3:
            await interaction.response.send_message("⚠️ لازم 3 لاعبين على الأقل قبل البدء.", ephemeral=True)
            return

        game_view = RouletteView(self.players)
        game_view.chosen = random.choice(self.players)
        game_view._build_buttons()
        names = "، ".join(m.mention for m in self.players)
        await interaction.response.edit_message(
            content=f"🎡 **بدأت اللعبة!**\n{names}\n\n🎯 دور {game_view.chosen.mention} يختار وحد يطلعه!",
            view=game_view,
        )
        self.stop()


@bot.command(name="روليت")
async def roulette_cmd(ctx: commands.Context):
    if ctx.author.bot:
        return
    view = RouletteLobbyView(ctx.author)
    await ctx.send(view._status_text(), view=view)


# ============================================================
# 4) نظام الإدارة الكامل — بدون بريفكس، حسب الرتب
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

    game = active_guess_games.get(message.channel.id)
    if game and message.content.strip().lstrip("-").isdigit():
        guess = int(message.content.strip())
        if guess == game["number"]:
            reward = random.randint(50, 150)
            add_balance(message.guild.id, message.author.id, reward)
            await message.channel.send(f"🎉 {message.author.mention} عرف الرقم **{game['number']}**! (+{reward} نقطة)")
            del active_guess_games[message.channel.id]
        elif 0 < guess < game["number"]:
            await message.add_reaction("⬆️")
        elif guess > game["number"]:
            await message.add_reaction("⬇️")

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول باسم {bot.user}")
    if not every_five_minutes.is_running():
        every_five_minutes.start()

if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
