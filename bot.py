"""
بوت ديسكورد شامل — نسخة كاملة مدموجة ومنظمة مع خادم الويب لمنصة Render
=====================================================================
"""

import discord
from discord.ext import commands
import aiohttp
import json
import os
import re
import random
import asyncio
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
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
# خادم الويب الوهمي الخاص بمنصة Render (لإبقاء البوت أونلاين)
# ============================================================
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


@bot.command(name="تنبيه")
async def warn_prefix_cmd(ctx: commands.Context, member: discord.Member = None, *, reason: str = "لم يُذكر سبب"):
    if not isinstance(ctx.author, discord.Member) or not getattr(ctx.author.guild_permissions, REQUIRED_WARN_PERMISSION, False):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} ❌ ليس لديك صلاحية.", delete_after=6)
        return
    if not member:
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} ⚠️ الصيغة: `!تنبيه @العضو السبب`", delete_after=6)
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    warn_number = add_warn(ctx.guild.id, member.id, reason, ctx.author.id)
    await send_warn_log(member, ctx.author, reason, warn_number, ctx.channel.name)
    await ctx.send(f"✅ تسجل تنبيه رقم **#{warn_number}** بحق {member.mention}", delete_after=6)


@bot.command(name="تنبيهاته", aliases=["warns"])
async def show_warns(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    count = get_warn_count(ctx.guild.id, member.id)
    await ctx.send(f"📋 لدى {member.mention} **{count}** تنبيه/تنبيهات مسجلة.")


# ============================================================
# 2) نظام الاقتصاد والنقاط
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


@bot.command(name="رصيد", aliases=["نقاطي"])
async def balance_cmd(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    bal = get_balance(ctx.guild.id, member.id)
    await ctx.send(f"💰 رصيد (نقاط) {member.mention}: **{bal}** نقطة")


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
    await ctx.send(f"🎁 {ctx.author.mention} أخذت **{reward}** نقطة يومية!")


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
# 3) مركز الألعاب الشامل
# ============================================================

@bot.command(name="العاب", aliases=["ألعاب", "مركز_الالعاب"])
async def games_center_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="🎮 مركز الألعاب",
        description="اختر اللعبة واستخدم أمرها بحرف `!` قبل كل لعبة.\n*الألعاب الجماعية تبدأ بلوبي تفاعلي مدته 30 ثانية.*\n",
        color=0x3498DB
    )
    embed.add_field(
        name="👥 ألعاب جماعية",
        value="`.روليت` | `.xo` | `.مافيا`\n`.كراسي` | `.حجرة` | `.نرد`\n`.عجلة` | `.غميضة` | `.ريبلكا`\n`.خمن` | `.كلمة`",
        inline=False
    )
    embed.add_field(
        name="👤 ألعاب فردية",
        value="`.زر` | `.اسرع` | `.فكك`\n`.ادمج` | `.اعلام` | `.اعكس`\n`.حرف` | `.صحح` | `.ترتيب`\n`.الوان` | `.ايموجي` | `.اكشف`",
        inline=False
    )
    embed.set_footer(text="اكسب النقاط وارفع رصيدك عبر الفوز بالألعاب!")
    await ctx.send(embed=embed)


# --- ألعاب XO ---
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
async def xo_cmd(ctx: commands.Context, opponent: discord.Member = None):
    if not opponent or opponent.bot or opponent == ctx.author:
        await ctx.send("⚠️ الصيغة الصحيحة: `!xo @العضو` (اختر خصمًا حقيقيًا غيرك).")
        return
    view = TicTacToeView(ctx.author, opponent)
    await ctx.send(f"🎮 **XO**: {ctx.author.mention} (X) ضد {opponent.mention} (O)\n🎯 دور {ctx.author.mention}", view=view)


# --- حجرة ورقة مقص ---
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
async def rps_cmd(ctx: commands.Context, opponent: discord.Member = None):
    if not opponent or opponent.bot or opponent == ctx.author:
        await ctx.send("⚠️ الصيغة الصحيحة: `!حجرة @العضو`")
        return
    view = RPSView(ctx.author, opponent)
    await ctx.send(f"✂️ **حجرة ورقة مقص**: {ctx.author.mention} ضد {opponent.mention}\nكل واحد يضغط بالخفاء 👇", view=view)


# --- لوبي ألعاب جماعية موحد (30 ثانية) ---
class GenericLobbyView(discord.ui.View):
    def __init__(self, host: discord.Member, game_name: str, reward: int):
        super().__init__(timeout=30)
        self.host = host
        self.game_name = game_name
        self.reward = reward
        self.players = [host]
        self.message = None

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                if len(self.players) >= 2:
                    winner = random.choice(self.players)
                    add_balance(self.message.guild.id, winner.id, self.reward)
                    await self.message.edit(content=f"🎮 **انتهى وقت اللوبي لـ ({self.game_name})!**\n🏆 الفائز عشوائياً: {winner.mention} (+{self.reward} نقطة)", view=self)
                else:
                    await self.message.edit(content=f"❌ تم إلغاء لعبة ({self.game_name}) لعدم اكتمال اللاعبين.", view=self)
            except Exception:
                pass

    @discord.ui.button(label="🎮 انضمام للوبي (30 ثانية)", style=discord.ButtonStyle.success)
    async def join_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.bot:
            await interaction.response.send_message("⚠️ البوتات لا تلعب.", ephemeral=True)
            return
        if interaction.user in self.players:
            await interaction.response.send_message("✅ أنت منضم مسبقاً للوبي.", ephemeral=True)
            return
        self.players.append(interaction.user)
        names = "، ".join(m.mention for m in self.players)
        await interaction.response.edit_content(content=f"🎮 **لعبة ({self.game_name}) — جاري الانتظار (30 ثانية)**\nالمنضمين ({len(self.players)}): {names}")


async def start_group_lobby(ctx: commands.Context, game_name: str, reward: int = 40):
    view = GenericLobbyView(ctx.author, game_name, reward)
    msg = await ctx.send(f"🎮 **لعبة ({game_name}) — بدأ اللوبي!**\nاضغط الزر أدناه للانضمام (الوقت 30 ثانية):\nالمنضمين (1): {ctx.author.mention}", view=view)
    view.message = msg


@bot.command(name="روليت")
async def roulette_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "روليت الحظ", 100)

@bot.command(name="مافيا")
async def mafia_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "لعبة مافيا", 80)

@bot.command(name="كراسي")
async def chairs_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "لعبة الكراسي الموسيقية", 60)

@bot.command(name="نرد")
async def dice_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "سباق النرد", 50)

@bot.command(name="عجلة")
async def wheel_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "عجلة الحظ", 70)

@bot.command(name="غميضة")
async def hide_seek_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "لعبة الغميضة", 60)

@bot.command(name="ريبلكا")
async def replica_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "لعبة ريبلكا", 50)

@bot.command(name="كلمة")
async def word_game_cmd(ctx: commands.Context):
    await start_group_lobby(ctx, "تحدي الكلمات الجماعي", 60)


# --- ألعاب تخمين ورقمية (تلقائية عبر الشات) ---
active_guess_games: dict[int, dict] = {}

@bot.command(name="خمن")
async def guess_start(ctx: commands.Context, max_number: int = 100):
    if ctx.channel.id in active_guess_games:
        await ctx.send("⚠️ فيه لعبة تخمين شغالة هنا حالياً.")
        return
    if max_number < 10:
        max_number = 100
    number = random.randint(1, max_number)
    active_guess_games[ctx.channel.id] = {"number": number, "max": max_number}
    await ctx.send(f"🔢 اخترت رقم سري بين **1** و **{max_number}**! اكتبوا تخمينكم بالشات مباشرة.")


# --- الألعاب الفردية السريعة ---
@bot.command(name="زر")
async def game_button_fast(ctx: commands.Context):
    class FastBtn(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=15)
        @discord.ui.button(label="اضغط بسرعة للحصول على النقاط!", style=discord.ButtonStyle.danger)
        async def click(self, interaction: discord.Interaction, button: discord.ui.Button):
            for c in self.children:
                c.disabled = True
            reward = 40
            add_balance(interaction.guild.id, interaction.user.id, reward)
            await interaction.response.edit_message(content=f"⚡ فاز بالسرعة {interaction.user.mention} وحصل على **{reward}** نقطة!", view=self)
            self.stop()
    await ctx.send("⚡ **أسرع زر**: أول شخص يضغط الزر يفوز!", view=FastBtn())

@bot.command(name="اسرع")
async def game_fastest(ctx: commands.Context):
    words = ["تفاحة", "سحاب", "برمجة", "ديسكورد", "صاروخ"]
    target = random.choice(words)
    await ctx.send(f"🏃 أسرع شخص يكتب هذه الكلمة بالشات: **`{target}`**")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() == target
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 35)
        await ctx.send(f"🏆 فاز {msg.author.mention} وأخذ 35 نقطة!")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت ولم يكتبها أحد!")

@bot.command(name="فكك")
async def game_fakik(ctx: commands.Context):
    data = {"البرمجة": "ا ل ب ر م ج ة", "مملكة": "م م ل ك ه", "سلطان": "س ل ط ا ن"}
    word, letters = random.choice(list(data.items()))
    await ctx.send(f"🧩 فكك الكلمة التالية: **`{letters}`**")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() == word
    try:
        msg = await bot.wait_for('message', timeout=25.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 40)
        await ctx.send(f"🎉 صح عليك يا {msg.author.mention} (+40 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send(f"⏰ انتهى الوقت! الكلمة الصحيحة هي: **{word}**")

@bot.command(name="ادمج")
async def game_merge(ctx: commands.Context):
    await ctx.send("🔗 **دمج**: ادمج الحروف التالية لكلمة صحيحة: `ح ا س و ب` (الإجابة: حاسوب)")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() == "حاسوب"
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 30)
        await ctx.send(f"🎉 فاز {msg.author.mention} (+30 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت!")

@bot.command(name="اعلام")
async def game_flags(ctx: commands.Context):
    flags = {"السعودية": "🇸🇦", "الكويت": "🇰🇼", "الإمارات": "🇦🇪", "مصر": "🇪🇬"}
    name, flag = random.choice(list(flags.items()))
    await ctx.send(f"🏳️ ما هي الدولة صاحبة هذا العلم؟ {flag}")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() == name
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 35)
        await ctx.send(f"🏆 صح يا {msg.author.mention} (+35 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send(f"⏰ انتهى الوقت! الدولة هي: **{name}**")

@bot.command(name="اعكس")
async def game_reverse(ctx: commands.Context):
    await ctx.send("🔄 اعكس الكلمة: `ةراسي` (السيارة بالعكس)")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() in ("سيارة", "السيارة")
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 30)
        await ctx.send(f"🎉 فاز {msg.author.mention} (+30 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت!")

@bot.command(name="حرف")
async def game_letter(ctx: commands.Context):
    letter = random.choice(["م", "ب", "س", "أ", "د"])
    await ctx.send(f"🔤 اعطني اسم جماد بحرف: **{letter}**")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 25)
        await ctx.send(f"✅ أحسنت {msg.author.mention} (+25 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت!")

@bot.command(name="صحح")
async def game_correct(ctx: commands.Context):
    await ctx.send("✍️ صحح الكلمة الخطأ التالية: `محهندس`")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() in ("مهندس", "المهندس")
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 30)
        await ctx.send(f"🎉 ممتاز {msg.author.mention} (+30 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت!")

@bot.command(name="ترتيب")
async def game_order(ctx: commands.Context):
    await ctx.send(" ترتيب الحروف لتكوين كلمة: `م ش م س` (شمس)")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and m.content.strip() == "شمس"
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 30)
        await ctx.send(f"🎉 فاز {msg.author.mention} (+30 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت!")

@bot.command(name="الوان")
async def game_colors(ctx: commands.Context):
    await ctx.send("🎨 ما هو لون مزج (الأصفر + الأزرق)؟")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and (m.content.strip() == "اخضر" or m.content.strip() == "أخضر")
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 30)
        await ctx.send(f"🎉 صح يا {msg.author.mention} (+30 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت! الإجابة هي: أخضر")

@bot.command(name="ايموجي")
async def game_emoji(ctx: commands.Context):
    await ctx.send("😀 ما هو معنى هذا الايموجي: 🦁 ؟")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and "اسد" in m.content.strip()
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 25)
        await ctx.send(f"🎉 صح يا {msg.author.mention} (+25 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت! أسد.")

@bot.command(name="اكشف")
async def game_reveal(ctx: commands.Context):
    await ctx.send("🕵️ خمن الحيوان الخفي: يملك سنامين ويعيش بالصحراء؟")
    def check(m):
        return m.channel == ctx.channel and not m.author.bot and "جمل" in m.content.strip()
    try:
        msg = await bot.wait_for('message', timeout=20.0, check=check)
        add_balance(ctx.guild.id, msg.author.id, 35)
        await ctx.send(f"🎉 كفو {msg.author.mention} (+35 نقطة)")
    except asyncio.TimeoutError:
        await ctx.send("⏰ انتهى الوقت! الجمل.")


# ============================================================
# 4) نظام الإدارة الكامل — بالبريفكس (!) وحسب الرتب
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


def parse_duration(text: str) -> timedelta:
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


# --- أوامر الإدارة بالبريفكس ! ---
@bot.command(name="برا")
async def admin_ban(ctx: commands.Context, member: discord.Member = None, *, reason: str = "لم يُذكر سبب"):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!برا @العضو السبب`")
        return
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 تم حظر {member.mention} — السبب: {reason}")
    except discord.Forbidden:
        await ctx.send("❌ صلاحياتي أقل من هذا العضو.")

@bot.command(name="سماح")
async def admin_unban(ctx: commands.Context, user_id: str = None):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not user_id or not user_id.isdigit():
        await ctx.send("⚠️ الصيغة: `!سماح <آيدي_العضو>`")
        return
    try:
        user = discord.Object(id=int(user_id))
        await ctx.guild.unban(user, reason=f"بواسطة {ctx.author}")
        await ctx.send(f"✅ تم فك الحظر عن الآيدي `{user_id}`")
    except Exception:
        await ctx.send("❌ لم أجد حظراً بهذا الآيدي.")

@bot.command(name="ترحيل", aliases=["كيك"])
async def admin_kick(ctx: commands.Context, member: discord.Member = None, *, reason: str = "لم يُذكر سبب"):
    if not has_role(ctx.author, JR_MOD_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!ترحيل @العضو السبب`")
        return
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 تم طرد {member.mention}")
    except Exception:
        await ctx.send("❌ لا يمكنني طرد هذا العضو.")

@bot.command(name="تايم", aliases=["اص"])
async def admin_timeout(ctx: commands.Context, member: discord.Member = None, time_str: str = "10m", *, reason: str = "لم يُذكر سبب"):
    if not has_role(ctx.author, HELPER_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!تايم @العضو 10m السبب`")
        return
    duration = parse_duration(time_str)
    try:
        await member.timeout(discord.utils.utcnow() + duration, reason=reason)
        await ctx.send(f"⏱️ تم إعطاء {member.mention} تايم لمدة {duration}")
    except Exception:
        await ctx.send("❌ لا يمكنني إعطاء تايم لهذا العضو.")

@bot.command(name="تحرير")
async def admin_untimeout(ctx: commands.Context, member: discord.Member = None):
    if not has_role(ctx.author, HELPER_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!تحرير @العضو`")
        return
    await member.timeout(None, reason=f"بواسطة {ctx.author}")
    await ctx.send(f"✅ تم فك التايم عن {member.mention}")

@bot.command(name="اخرس")
async def admin_textmute(ctx: commands.Context, member: discord.Member = None):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!اخرس @العضو`")
        return
    role = await ensure_role(ctx.guild, MUTE_ROLE_NAME)
    await member.add_roles(role, reason=f"بواسطة {ctx.author}")
    await ctx.send(f"🔇 تم إسكات {member.mention} بالشات.")

@bot.command(name="تكلم")
async def admin_textunmute(ctx: commands.Context, member: discord.Member = None):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!تكلم @العضو`")
        return
    role = discord.utils.get(ctx.guild.roles, name=MUTE_ROLE_NAME)
    if role and role in member.roles:
        await member.remove_roles(role)
    await ctx.send(f"🔊 تم فك الإسكات عن {member.mention}")

@bot.command(name="سجن")
async def admin_jail(ctx: commands.Context, member: discord.Member = None):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!سجن @العضو`")
        return
    jail_role = await ensure_role(ctx.guild, JAIL_ROLE_NAME)
    keep_roles = [r for r in member.roles if r.name != "@everyone"]
    data = load_json(JAIL_FILE)
    gid, mid = str(ctx.guild.id), str(member.id)
    data.setdefault(gid, {})[mid] = [r.id for r in keep_roles]
    save_json(JAIL_FILE, data)
    await member.remove_roles(*keep_roles)
    await member.add_roles(jail_role)
    await ctx.send(f"🔒 تم سجن {member.mention}")

@bot.command(name="فك")
async def admin_unjail(ctx: commands.Context, member: discord.Member = None):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    if not member:
        await ctx.send("⚠️ الصيغة: `!فك @العضو`")
        return
    data = load_json(JAIL_FILE)
    gid, mid = str(ctx.guild.id), str(member.id)
    saved_ids = data.get(gid, {}).get(mid, [])
    roles = [ctx.guild.get_role(rid) for rid in saved_ids if ctx.guild.get_role(rid)]
    jail_role = discord.utils.get(ctx.guild.roles, name=JAIL_ROLE_NAME)
    if jail_role and jail_role in member.roles:
        await member.remove_roles(jail_role)
    if roles:
        await member.add_roles(*roles)
        data[gid].pop(mid, None)
        save_json(JAIL_FILE, data)
    await ctx.send(f"🔓 تم فك السجن عن {member.mention}")

@bot.command(name="مسح", aliases=["اباده"])
async def admin_purge(ctx: commands.Context, amount: int = 50):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    amount = min(amount, 100)
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"🧹 تم حذف {len(deleted)} رسالة.", delete_after=5)

@bot.command(name="قفل")
async def admin_lock(ctx: commands.Context):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("🔒 تم قفل الروم.")

@bot.command(name="فتح")
async def admin_unlock(ctx: commands.Context):
    if not has_role(ctx.author, ADMIN_ROLES):
        await ctx.send("❌ ليس لديك صلاحية.")
        return
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("🔓 تم فتح الروم.")


# ============================================================
# المعالجات العامة والأحداث وتشغيل السيرفر والبوت معاَ
# ============================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # معالجة لعبة التخمين الشاتية التفاعلية
    game = active_guess_games.get(message.channel.id)
    if game and message.content.strip().lstrip("-").isdigit():
        guess = int(message.content.strip())
        if guess == game["number"]:
            reward = random.randint(50, 150)
            add_balance(message.guild.id, message.author.id, reward)
            await message.channel.send(f"🎉 {message.author.mention} عرف الرقم السري **{game['number']}**! (+{reward} نقطة)")
            del active_guess_games[message.channel.id]
        elif 0 < guess < game["number"]:
            await message.add_reaction("⬆️")
        elif guess > game["number"]:
            await message.add_reaction("⬇️")

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول بنجاح باسم {bot.user}")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ تنبيه: رمز البوت DISCORD_TOKEN غير موجود في ملف البيئة .env!")
    else:
        # تشغيل خادم الويب الوهمي في الخلفية ليوافق منصة Render
        t = threading.Thread(target=run_web_server)
        t.daemon = True
        t.start()
        
        # تشغيل بوت ديسكورد
        bot.run(DISCORD_TOKEN)
