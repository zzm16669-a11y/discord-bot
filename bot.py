import os
import random
import asyncio
import datetime
import discord
from discord.ext import commands
import google.generativeai as genai

# ==========================================
# إعدادات البوت والانتنتس
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="", intents=intents)

# عداد التنبيهات للسيرفر
warn_counter = 0

# تهيئة الذكاء الاصطناعي (Gemini)
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")

# ==========================================
# 1. قسم الألعاب الواجهة التفاعلية والأزرار
# ==========================================

class RPSButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="حجرة 🪨", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "حجرة")

    @discord.ui.button(label="ورقة 📄", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "ورقة")

    @discord.ui.button(label="مقص ✂️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "مقص")

    async def play(self, interaction: discord.Interaction, user_choice: str):
        choices = ["حجرة", "ورقة", "مقص"]
        bot_choice = random.choice(choices)

        if user_choice == bot_choice:
            result = "تعادل! 🤝"
        elif (user_choice == "حجرة" and bot_choice == "مقص") or \
             (user_choice == "ورقة" and bot_choice == "حجرة") or \
             (user_choice == "مقص" and bot_choice == "ورقة"):
            result = f"مبروك الفوز يا {interaction.user.mention}! 🎉"
        else:
            result = "للأسف البوت فاز عليك! 🤖"

        embed = discord.Embed(title="🎮 نتيجة حجرة ورقة مقص", color=discord.Color.gold())
        embed.add_field(name="اختيارك", value=user_choice, inline=True)
        embed.add_field(name="اختيار البوت", value=bot_choice, inline=True)
        embed.add_field(name="النتيجة", value=result, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

class MainGameMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="حجرة ورقة مقص ✂️", style=discord.ButtonStyle.success)
    async def rps_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🎮 لعبة حجرة ورقة مقص", description="اختر إما حجرة أو ورقة أو مقص من الأزرار التالية:", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=RPSButtons(), ephemeral=True)

    @discord.ui.button(label="لعبة التخمين 🎯", style=discord.ButtonStyle.secondary)
    async def guess_game_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("لتشغيل لعبة التخمين، اكتب الأمر `تخمين` في الشات مباشر!", ephemeral=True)

@bot.command(aliases=["العاب", "ألعاب"])
async def games_menu(ctx):
    embed = discord.Embed(title="🎯 قائمة الألعاب التفاعلية", description="اختر اللعبة التي تريدها من الأزرار بالأسفل:", color=discord.Color.purple())
    await ctx.send(embed=embed, view=MainGameMenu())

@bot.command(name="حجرة_ورقة_مقص")
async def rps_cmd(ctx):
    embed = discord.Embed(title="🎮 لعبة حجرة ورقة مقص", description="اختر إما حجرة أو ورقة أو مقص:", color=discord.Color.blue())
    await ctx.send(embed=embed, view=RPSButtons())

@bot.command(name="تخمين")
async def guess_game(ctx):
    number = random.randint(1, 10)
    await ctx.send("🎯 خمنت رقماً بين 1 و 10! اكتب إجابتك في الشات خلال 15 ثانية:")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

    try:
        msg = await bot.wait_for('message', check=check, timeout=15.0)
        if int(msg.content) == number:
            await ctx.send(f"🎉 مبروك يا {ctx.author.mention}! إجابتك صحيحة (الرقم هو {number}).")
        else:
            await ctx.send(f"❌ للأسف خطأ، الرقم الصحيح كان {number}.")
    except asyncio.TimeoutError:
        await ctx.send(f"⏰ انتهى الوقت! الرقم الصحيح كان {number}.")


# ==========================================
# 2. إدارة الأعضاء (نظام التنبيه واللوق)
# ==========================================

@bot.command(name="تنبيه")
@commands.has_permissions(manage_messages=True)
async def warn_member(ctx, member: discord.Member, *, reason="مدري بس يستاهل"):
    global warn_counter
    warn_counter += 1

    # رسالة تأكيد بسيطة في الشات
    await ctx.send(f"تم إعطاء تنبيه لـ {member.mention} بنجاح.", delete_after=5)

    # إنشاء إمبيد اللوق بأسلوب الصورة بالضبط
    embed = discord.Embed(
        title="⚠️ تم تسجيل تنبيه رسمي",
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="رقم التنبيه", value=f"#{warn_counter}", inline=True)
    embed.add_field(name="بواسطة", value=ctx.author.mention, inline=True)
    embed.add_field(name="العضو", value=member.mention, inline=True)
    embed.add_field(name="السبب", value=reason, inline=False)
    embed.add_field(name="القناة", value=ctx.channel.mention, inline=False)
    embed.set_footer(text=f"معرف العضو: {member.id}")

    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)

    # البحث عن روم warn-log لإرسال اللوق فيها
    log_channel = discord.utils.get(ctx.guild.text_channels, name="warn-log")
    if log_channel:
        await log_channel.send(embed=embed)
    else:
        await ctx.send(embed=embed)

@bot.command(aliases=["برا", "باند"])
@commands.has_permissions(ban_members=True)
async def ban_member(ctx, member: discord.Member, *, reason="بدون سبب"):
    await member.ban(reason=reason)
    await ctx.send(f"🚫 تم حظر العضو {member.mention} بنجاح.")

@bot.command(name="سماح")
@commands.has_permissions(ban_members=True)
async def unban_member(ctx, user_id: int):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user)
    await ctx.send(f"✅ تم فك الحظر عن {user.name}.")

@bot.command(aliases=["ترحيل", "كيك"])
@commands.has_permissions(kick_members=True)
async def kick_member(ctx, member: discord.Member, *, reason="بدون سبب"):
    await member.kick(reason=reason)
    await ctx.send(f"👞 تم طرد العضو {member.mention} من السيرفر.")

@bot.command(aliases=["تايم", "اص"])
@commands.has_permissions(moderate_members=True)
async def timeout_member(ctx, member: discord.Member, minutes: int = 10, *, reason="بدون سبب"):
    duration = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(f"⏱️ تم إعطاء {member.mention} تايم لمدة {minutes} دقائق.")

@bot.command(name="تحرير")
@commands.has_permissions(moderate_members=True)
async def untimeout_member(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"🔓 تم فك التايم عن {member.mention}.")

@bot.command(name="اخرس")
@commands.has_permissions(manage_roles=True)
async def mute_chat(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(role, send_messages=False)
    await member.add_roles(role)
    await ctx.send(f"🔇 تم إسكات {member.mention} كتابياً.")

@bot.command(name="تكلم")
@commands.has_permissions(manage_roles=True)
async def unmute_chat(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if role and role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f"🔊 تم فك الميوت عن {member.mention}.")

@bot.command(aliases=["لقب", "اسم"])
@commands.has_permissions(manage_nicknames=True)
async def change_nick(ctx, member: discord.Member, *, new_name: str):
    await member.edit(nick=new_name)
    await ctx.send(f"✏️ تم تغيير لقب {member.mention} إلى `{new_name}`.")


# ==========================================
# 3. إدارة الرومات (مسح، قفل، فتح، إخفاء...)
# ==========================================

@bot.command(aliases=["اباده", "مسح"])
@commands.has_permissions(manage_messages=True)
async def clear_messages(ctx, amount: int = 100):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 تم مسح {amount} رسالة.", delete_after=3)

@bot.command(name="قفل")
@commands.has_permissions(manage_channels=True)
async def lock_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 تم قفل الروم.")

@bot.command(name="فتح")
@commands.has_permissions(manage_channels=True)
async def unlock_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 تم فتح الروم.")

@bot.command(aliases=["اخفاء", "خفي"])
@commands.has_permissions(manage_channels=True)
async def hide_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, view_channel=False)
    await ctx.send("👻 تم إخفاء الروم.")

@bot.command(name="اظهار")
@commands.has_permissions(manage_channels=True)
async def show_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, view_channel=True)
    await ctx.send("👁️ تم إظهار الروم.")


# ==========================================
# 4. إدارة الصوتيات (بره، اصمت، انطق، اسحب...)
# ==========================================

@bot.command(name="بره")
@commands.has_permissions(move_members=True)
async def voice_kick(ctx, member: discord.Member):
    if member.voice:
        await member.move_to(None)
        await ctx.send(f"🚪 تم طرد {member.mention} من الروم الصوتي.")

@bot.command(name="اصمت")
@commands.has_permissions(mute_members=True)
async def voice_mute(ctx, member: discord.Member):
    if member.voice:
        await member.edit(mute=True)
        await ctx.send(f"🔇 تم كتم {member.mention} صوتياً.")

@bot.command(name="انطق")
@commands.has_permissions(mute_members=True)
async def voice_unmute(ctx, member: discord.Member):
    if member.voice:
        await member.edit(mute=False)
        await ctx.send(f"🔊 تم فك الكتم الصوتي عن {member.mention}.")

@bot.command(name="اسحب")
@commands.has_permissions(move_members=True)
async def move_member(ctx, member: discord.Member):
    if ctx.author.voice and member.voice:
        await member.move_to(ctx.author.voice.channel)
        await ctx.send(f"📥 تم سحب {member.mention} إلى رومك الصوتي.")

@bot.command(aliases=["تعال", "كم هير بيبي"])
@commands.has_permissions(move_members=True)
async def goto_member(ctx, member: discord.Member):
    if ctx.author.voice and member.voice:
        await ctx.author.move_to(member.voice.channel)

@bot.command(name="اجمعهم")
@commands.has_permissions(move_members=True)
async def move_all(ctx):
    if ctx.author.voice:
        target_channel = ctx.author.voice.channel
        for channel in ctx.guild.voice_channels:
            for member in channel.members:
                await member.move_to(target_channel)
        await ctx.send("👥 تم جمع جميع الأعضاء المتواجدين بالصوت في رومك.")


# ==========================================
# 5. الرد التلقائي بالذكاء الاصطناعي (Gemini)
# ==========================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user.mentioned_in(message):
        content = message.content.replace(f'<@{bot.user.id}>', '').strip()
        if content and GEMINI_KEY:
            try:
                response = model.generate_content(content)
                await message.channel.send(response.text)
            except Exception:
                await message.channel.send("حدث خطأ أثناء الاتصال بالذكاء الاصطناعي.")

    await bot.process_commands(message)


# تشغيل البوت
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
