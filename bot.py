import discord
from discord.ext import commands
import aiohttp
import json
import os
import random
import asyncio
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
WARN_LOG_WEBHOOK_URL = os.environ.get("WARN_LOG_WEBHOOK_URL", "")
WARNS_FILE = "warns.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ==========================================
# دالة تحميل وحفظ التحذيرات (Warns)
# ==========================================
def load_warns():
    if not os.path.exists(WARNS_FILE):
        return {}
    try:
        with open(WARNS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_warns(warns):
    with open(WARNS_FILE, "w", encoding="utf-8") as f:
        json.dump(warns, f, ensure_ascii=False, indent=4)


async def send_webhook_log(title: str, description: str, color: int):
    if not WARN_LOG_WEBHOOK_URL:
        return
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    payload = {"embeds": [embed]}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(WARN_LOG_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Webhook Error: {e}")


@bot.event
async def on_ready():
    print(f"✅ البوت شغال بنجاح باسم: {bot.user}")


# ==========================================
# 1. لعبة الروليت (20 رقم بالأزرار)
# ==========================================
class NumberButton(discord.ui.Button):
    def __init__(self, number: int):
        super().__init__(
            label=str(number),
            style=discord.ButtonStyle.primary,
            custom_id=f"num_{number}",
            row=(number - 1) // 5
        )
        self.number = number

    async def callback(self, interaction: discord.Interaction):
        view: RouletteView = self.view
        user = interaction.user

        if user in view.players:
            await interaction.response.send_message("❌ أنت منضم للعبة بالفعل!", ephemeral=True)
            return

        if self.number in view.chosen_numbers:
            await interaction.response.send_message("❌ هذا الرقم محجوز بالفعل!", ephemeral=True)
            return

        view.players[user] = self.number
        view.chosen_numbers.add(self.number)
        self.disabled = True
        self.style = discord.ButtonStyle.secondary

        await interaction.response.edit_message(embed=view.create_embed(view.current_time_left), view=view)


class RouletteView(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__(timeout=30)
        self.host = host
        self.players = {}
        self.max_players = 20
        self.chosen_numbers = set()
        self.current_time_left = 30

        for i in range(1, 21):
            self.add_item(NumberButton(i))

    def create_embed(self, time_left: int = 30):
        self.current_time_left = time_left
        embed = discord.Embed(title="🎯 روليت", color=0xF1C40F)
        description = (
            "**طريقة اللعب:**\n"
            "**1-** اختر الرقم الذي سيمثلك في اللعبة\n"
            "**2-** ستبدأ الجولة الأولى وسيتم تدوير العجلة واختيار لاعب عشوائي\n"
            "**3-** إذا كنت اللاعب المختار، فستختار لاعباً من اختيارك ليتم طرده من اللعبة\n"
            "**4-** يُطرد اللاعب وتبدأ جولة جديدة\n\n"
            f"**أرقام اللاعبين:** ({len(self.players)}/{self.max_players})\n"
        )
        if self.players:
            for p, num in self.players.items():
                description += f"{p.mention} : **{num}**\n"
        else:
            description += "*لا يوجد لاعبين منضمين حتى الآن*\n"

        description += f"\n*ستبدأ اللعبة بعد {time_left} ثانية*"
        embed.description = description
        return embed


# ==========================================
# 2. لعبة XO التفاعلية بالأزرار
# ==========================================
class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=" ", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user != view.current_player:
            await interaction.response.send_message("❌ ليس دورك الآن!", ephemeral=True)
            return

        if view.board[self.y][self.x] != 0:
            await interaction.response.send_message("❌ هذه الخانة مأخوذة بالفعل!", ephemeral=True)
            return

        if view.current_player == view.player1:
            self.label = "❌"
            self.style = discord.ButtonStyle.danger
            view.board[self.y][self.x] = 1
            view.current_player = view.player2
        else:
            self.label = "⭕"
            self.style = discord.ButtonStyle.primary
            view.board[self.y][self.x] = 2
            view.current_player = view.player1

        self.disabled = True
        winner = view.check_winner()

        if winner:
            for child in view.children:
                child.disabled = True
            if winner == "Draw":
                embed = discord.Embed(title="🎮 XO", description="🤝 **تعادل! انتهت اللعبة بدون فائز.**", color=0x95A5A6)
            else:
                win_user = view.player1 if winner == 1 else view.player2
                embed = discord.Embed(title="🎮 XO", description=f"🎉 **مبروك الفوز يا {win_user.mention}!**", color=0x2ECC71)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            embed = discord.Embed(
                title="🎮 لعبة XO",
                description=f"❌ {view.player1.mention} **ضد** ⭕ {view.player2.mention}\n\n👉 الدور الآن على: {view.current_player.mention}",
                color=0x3498DB
            )
            await interaction.response.edit_message(embed=embed, view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=60)
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_winner(self):
        b = self.board
        for i in range(3):
            if b[i][0] == b[i][1] == b[i][2] != 0: return b[i][0]
            if b[0][i] == b[1][i] == b[2][i] != 0: return b[0][i]
        if b[0][0] == b[1][1] == b[2][2] != 0: return b[0][0]
        if b[0][2] == b[1][1] == b[2][0] != 0: return b[0][0]

        if all(cell != 0 for row in b for cell in row):
            return "Draw"
        return None


# ==========================================
# 3. لعبة حجرة ورقة مقص بالأزرار
# ==========================================
class RPSView(discord.ui.View):
    def __init__(self, player: discord.Member):
        super().__init__(timeout=30)
        self.player = player

    @discord.ui.button(label="حجرة 🪨", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "حجرة 🪨")

    @discord.ui.button(label="ورقة 📄", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "ورقة 📄")

    @discord.ui.button(label="مقص ✂️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "مقص ✂️")

    async def play(self, interaction: discord.Interaction, user_choice: str):
        if interaction.user != self.player:
            await interaction.response.send_message("❌ هذه اللعبة ليست لك!", ephemeral=True)
            return

        bot_choice = random.choice(["حجرة 🪨", "ورقة 📄", "مقص ✂️"])
        result = ""

        if user_choice == bot_choice:
            result = "🤝 تعادل!"
        elif (user_choice == "حجرة 🪨" and bot_choice == "مقص ✂️") or \
             (user_choice == "ورقة 📄" and bot_choice == "حجرة 🪨") or \
             (user_choice == "مقص ✂️" and bot_choice == "ورقة 📄"):
            result = f"🎉 مبروك الفوز يا {self.player.mention}!"
        else:
            result = "💥 للأسف البوت فاز عليك!"

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(title="✊ حجرة ورقة مقص", color=0x9B59B6)
        embed.add_field(name="اختيارك", value=user_choice, inline=True)
        embed.add_field(name="اختيار البوت", value=bot_choice, inline=True)
        embed.add_field(name="النتيجة", value=f"**{result}**", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)


# ==========================================
# معالجة جميع الأوامر
# ==========================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    parts = content.split()
    command_name = parts[0] if parts else ""

    # 🛠️ أمر المساعدة الشامل
    if command_name in ["!اوامر", "اوامر", "!الأوامر", "الأوامر", "!help"]:
        embed = discord.Embed(title="📜 قائمة الأوامر الشاملة", color=0x3498DB)
        embed.add_field(
            name="🎮 ألعاب وسلية",
            value="`!العاب` : تعرض جميع الألعاب (روليت، XO، حجرة ورقة مقص، أسرع واحد، صراحة، نرد، حب)",
            inline=False
        )
        embed.add_field(
            name="🔊 أوامر الروم الصوتي",
            value="`برا @العضو` : طرد عضو من الروم الصوتي الحالي.",
            inline=False
        )
        embed.add_field(
            name="🛡️ أوامر الإدارة والتحذيرات",
            value=(
                "`!تحذير @العضو السبب` : إعطاء تحذير لعضو.\n"
                "`!التحذيرات @العضو` : عرض تحذيرات عضو معين.\n"
                "`!مسح_تحذير @العضو رقم_التحذير` : مسح تحذير محدد."
            ),
            inline=False
        )
        await message.channel.send(embed=embed)
        return

    # 🚪 أمر الطرد الصوتي (برا)
    if command_name in ["!برا", "برا", "!براا", "براا"]:
        target_member = None
        if message.mentions:
            target_member = message.mentions[0]
        elif message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                target_member = ref_msg.author
            except Exception:
                pass

        if not target_member:
            await message.channel.send("⚠️ يرجى منشن العضو أو الرد على رسالته! مثال: `برا @العضو`", delete_after=5)
            return

        if target_member.voice and target_member.voice.channel:
            try:
                await target_member.move_to(None)
                await message.channel.send(f"🚪 تم طرد {target_member.mention} من الروم الصوتي بنجاح!")
            except discord.Forbidden:
                await message.channel.send("❌ البوت لا يمتلك صلاحية طرد الأعضاء من الروم الصوتي (Move Members).")
            except Exception as e:
                await message.channel.send(f"❌ حدث خطأ: {e}")
        else:
            await message.channel.send(f"❌ العضو {target_member.mention} غير موجود في أي روم صوتي حالياً!")
        return

    # ⚠️ أمر إعطاء تحذير (!تحذير)
    if command_name in ["!تحذير", "تحذير"]:
        if not message.author.guild_permissions.manage_messages:
            await message.channel.send("❌ ليس لديك صلاحية استخدام هذا الأمر (Manage Messages).", delete_after=5)
            return
        if not message.mentions:
            await message.channel.send("⚠️ يرجى منشن العضو وكتابة السبب! مثال: `!تحذير @العضو السببية`", delete_after=5)
            return

        target = message.mentions[0]
        reason = " ".join(parts[2:]) if len(parts) > 2 else "لم يتم ذكر سبب"

        warns = load_warns()
        guild_id = str(message.guild.id)
        user_id = str(target.id)

        if guild_id not in warns:
            warns[guild_id] = {}
        if user_id not in warns[guild_id]:
            warns[guild_id][user_id] = []

        warn_data = {
            "reason": reason,
            "moderator": str(message.author),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        warns[guild_id][user_id].append(warn_data)
        save_warns(warns)

        total_warns = len(warns[guild_id][user_id])
        await message.channel.send(f"⚠️ تم تحذير {target.mention} | السبب: **{reason}** (إجمالي التحذيرات: **{total_warns}**)")
        await send_webhook_log(
            "⚠️ تحذير جديد",
            f"**المُحَذَّر:** {target.mention} (`{target.id}`)\n**المشرف:** {message.author.mention}\n**السبب:** {reason}\n**عدد التحذيرات:** {total_warns}",
            0xE74C3C
        )
        return

    # 📋 أمر عرض التحذيرات (!التحذيرات)
    if command_name in ["!التحذيرات", "التحذيرات", "!سجل_التحذيرات"]:
        target = message.mentions[0] if message.mentions else message.author
        warns = load_warns()
        guild_id = str(message.guild.id)
        user_id = str(target.id)

        user_warns = warns.get(guild_id, {}).get(user_id, [])
        if not user_warns:
            await message.channel.send(f"✅ لا يوجد أي تحذيرات مسجلة على {target.mention}.")
            return

        embed = discord.Embed(title=f"📋 سجل تحذيرات {target.display_name}", color=0xF1C40F)
        for i, w in enumerate(user_warns, 1):
            embed.add_field(
                name=f"تحذير #{i}",
                value=f"**السبب:** {w['reason']}\n**المشرف:** {w['moderator']}\n**التاريخ:** {w['date']}",
                inline=False
            )
        await message.channel.send(embed=embed)
        return

    # 🎮 قائمة الألعاب
    if command_name in ["!العاب", "العاب", "!الألعاب", "الألعاب"]:
        embed = discord.Embed(
            title="🎮 قائمة الألعاب المتاحة",
            description="اختر اللعبة واكتب الأمر الخاص بها لبدء اللعب:",
            color=0x9B59B6
        )
        embed.add_field(name="🎯 !روليت (أو روليت)", value="لعبة روليت جماعية تفاعلية بالأزرار (حتى 20 لاعب).", inline=False)
        embed.add_field(name="❌ !xo @العضو (أو xo)", value="تحدي لعبة X-O مع صديقك بالأزرار التفاعلية.", inline=False)
        embed.add_field(name="✊ !حجرة (أو حجرة)", value="لعبة حجرة ورقة مقص ضد البوت بالأزرار.", inline=False)
        embed.add_field(name="⚡ !اسرع (أو اسرع)", value="تحدي كتابة الكلمة الأسرع بين الأعضاء.", inline=False)
        embed.add_field(name="💬 !صراحة (أو صراحة)", value="سؤال صراحة عشوائي.", inline=False)
        embed.add_field(name="🎲 !نرد (أو نرد)", value="رمي النرد لعرض رقم عشوائي.", inline=False)
        embed.add_field(name="❤️ !حب (أو حب)", value="قياس نسبة التوافق والحب العشوائية.", inline=False)
        await message.channel.send(embed=embed)
        return

    # 🎯 أمر الروليت
    if command_name in ["!روليت", "روليت"]:
        view = RouletteView(host=message.author)
        embed = view.create_embed(time_left=30)
        game_msg = await message.channel.send(embed=embed, view=view)

        for time_left in range(25, -1, -5):
            await asyncio.sleep(5)
            try:
                await game_msg.edit(embed=view.create_embed(time_left=time_left), view=view)
            except Exception:
                break

        for child in view.children:
            child.disabled = True

        if len(view.players) < 3:
            embed = discord.Embed(
                title="🎯 روليت",
                description=f"❌ **تم إيقاف اللعبة!**\nعدد اللاعبين الحالي (**{len(view.players)}**) غير كافٍ. يلزم دخول **3 لاعبين على الأقل** لبدء اللعبة.",
                color=0xE74C3C
            )
            await game_msg.edit(embed=embed, view=view)
            return

        embed = discord.Embed(title="🎰 بدأت اللعبة! جاري تدوير العجلة...", color=0x3498DB)
        await game_msg.edit(embed=embed, view=view)
        await asyncio.sleep(3)

        chosen_player = random.choice(list(view.players.keys()))
        embed = discord.Embed(
            title="🎉 نتيجة تدوير العجلة!",
            description=f"👑 العجلة اختارت اللاعب: {chosen_player.mention} (رقم **{view.players[chosen_player]}**)\n\n👉 **دورك الآن لاختيار لاعب لطرد من اللعبة!**",
            color=0x2ECC71
        )
        await message.channel.send(embed=embed)
        return

    # ❌ أمر XO
    if command_name in ["!xo", "xo"]:
        if not message.mentions:
            await message.channel.send("⚠️ يرجى منشن الشخص الذي تريد التحدي معه! مثال: `xo @العضو`", delete_after=6)
            return
        opponent = message.mentions[0]
        if opponent.bot or opponent == message.author:
            await message.channel.send("❌ لا يمكنك تحدي نفسك أو البوت!", delete_after=5)
            return

        view = TicTacToeView(player1=message.author, player2=opponent)
        embed = discord.Embed(
            title="🎮 لعبة XO",
            description=f"❌ {message.author.mention} **ضد** ⭕ {opponent.mention}\n\n👉 الدور الآن على: {message.author.mention}",
            color=0x3498DB
        )
        await message.channel.send(embed=embed, view=view)
        return

    # ✊ أمر حجرة ورقة مقص
    if command_name in ["!حجرة", "حجرة"]:
        view = RPSView(player=message.author)
        embed = discord.Embed(
            title="✊ حجرة ورقة مقص",
            description=f"مرحباً {message.author.mention}! اختر ضربتك من الأزرار التالية:",
            color=0x3498DB
        )
        await message.channel.send(embed=embed, view=view)
        return

    # ⚡ أمر أسرع واحد
    if command_name in ["!اسرع", "اسرع"]:
        words = ["سريع", "دسكورد", "سيرفر", "روليت", "مكالمة", "حاسوب"]
        target_word = random.choice(words)
        await message.channel.send(f"⚡ **أسرع واحد يكتب الكلمة التالية:**\n`{target_word}`")

        def check(m):
            return m.channel == message.channel and m.content == target_word and not m.author.bot

        try:
            winner = await bot.wait_for("message", check=check, timeout=15.0)
            await message.channel.send(f"🎉 **كفو! {winner.author.mention} هو الفائز بكتابة الكلمة أولاً!**")
        except asyncio.TimeoutError:
            await message.channel.send("⏱️ **انتهى الوقت ولم يكتب أحد الكلمة!**")
        return

    # 💬 أمر صراحة
    if command_name in ["!صراحة", "صراحة"]:
        questions = [
            "ما هو أكثر موقف محرج حصل لك؟",
            "لو ملكت العالم ليوم واحد، وش أول شيء بتسويه؟",
            "مين أكثر شخص تثق فيه في السيرفر؟"
        ]
        await message.channel.send(f"💬 سؤال صراحة: **{random.choice(questions)}**")
        return

    # 🎲 أمر نرد
    if command_name in ["!نرد", "نرد"]:
        await message.channel.send(f"🎲 رمي النرد أظهر الرقم: **{random.randint(1, 6)}**")
        return

    # ❤️ أمر حب
    if command_name in ["!حب", "حب"]:
        score = random.randint(0, 100)
        await message.channel.send(f"❤️ نسبة التوافق والحب: **{score}%** ✨")
        return

    await bot.process_commands(message)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)