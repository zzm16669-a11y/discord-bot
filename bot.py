import os
import random
import discord
from discord.ext import commands
import google.generativeai as genai

# إعدادات البوت
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# إعداد Gemnai API
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-pro')

@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول باسم: {bot.user.name}")

# ==========================================
# 1. أوامر الإدارة والصوت
# ==========================================

@bot.command(name="تجميع")
@commands.has_permissions(move_members=True)
async def move_all(ctx):
    if ctx.author.voice:
        target_channel = ctx.author.voice.channel
        for channel in ctx.guild.voice_channels:
            for member in channel.members:
                await member.move_to(target_channel)
        await ctx.send("🔊 تم جمع جميع الأعضاء المتواجدين بالصوت في رومك.")

# ==========================================
# 2. قسم الألعاب (Games Section)
# ==========================================

# لعبة الروليت
@bot.command(name="روليت")
async def roulette(ctx):
    """طريقة اللعب: اكتب !روليت لتجربة حظك بالنجاة من الطلقة"""
    outcomes = [
        "🎉 مبروك! نجوت من الروليت هذه المرة!",
        "💥 أوت! الطلقة أصابتك وخسرت في الروليت!"
    ]
    await ctx.send(f"{ctx.author.mention} {random.choice(outcomes)}")

# لعبة رمي العملة (طرة أو نقش)
@bot.command(name="فليب")
async def flip(ctx):
    """طريقة اللعب: اكتب !فليب لرمي العملة واكتشاف النتيجة"""
    results = ["🪙 ملك (طرة)", "🦅 كتابة (نقش)"]
    await ctx.send(f"النتيجة هي: **{random.choice(results)}**")

# لعبة النرد
@bot.command(name="نرد")
async def roll_dice(ctx):
    """طريقة اللعب: اكتب !نرد لرمي النرد والحصول على رقم عشوائي من 1 إلى 6"""
    number = random.randint(1, 6)
    await ctx.send(f"🎲 ظهر لك الرقم: **{number}**")

# لعبة حجرة ورقة مقص
@bot.command(name="rps")
async def rps(ctx, choice: str = None):
    """طريقة اللعب: اكتب !rps متبوعة بـ (حجرة أو ورقة أو مقص) مثل: !rps حجرة"""
    options = ["حجرة", "ورقة", "مقص"]
    if not choice or choice not in options:
        await ctx.send("⚠️ طريقة اللعب الصحيحة: اكتب `!rps` متبوعة بـ (حجرة، ورقة، أو مقص).\nمثال: `!rps حجرة`")
        return

    bot_choice = random.choice(options)
    
    if choice == bot_choice:
        result = "🤝 تعادل!"
    elif (choice == "حجرة" and bot_choice == "مقص") or \
         (choice == "ورقة" and bot_choice == "حجرة") or \
         (choice == "مقص" and bot_choice == "ورقة"):
        result = "🎉 فزت علي!"
    else:
        result = "😈 أنا فزت عليك!"

    await ctx.send(f"أنت اخترت: **{choice}** | أنا اخترت: **{bot_choice}**\n{result}")

# لعبة نسبة الحب/التوافق
@bot.command(name="نسبة")
async def love_percentage(ctx, member: discord.Member = None):
    """طريقة اللعب: اكتب !نسبة واعمل منشن لشخص لمعرفة نسبة التوافق بينكما"""
    if not member:
        await ctx.send("⚠️ طريقة اللعب: اكتب `!نسبة` ثم قم بعمل منشن للشخص.\nمثال: `!نسبة @user`")
        return
    
    percentage = random.randint(0, 100)
    await ctx.send(f"💖 نسبة التوافق بين {ctx.author.mention} و {member.mention} هي: **{percentage}%**")

# أمر عرض قائمة الألعاب وطريقة لعبها
@bot.command(name="الألعاب")
async def games_help(ctx):
    help_text = (
        "🎮 **قائمة الألعاب وطريقة لعبها:**\n\n"
        "1️⃣ **!روليت** — لعبة حظ لتجربة النجاة من الطلقة.\n"
        "2️⃣ **!فليب** — رمي العملة (ملك أو كتابة).\n"
        "3️⃣ **!نرد** — رمي النرد والحصول على رقم من 1 إلى 6.\n"
        "4️⃣ **!rps [اختيارك]** — حجرة ورقة مقص (مثال: `!rps حجرة`).\n"
        "5️⃣ **!نسبة [@عضو]** — قياس نسبة التوافق مع عضو (مثال: `!نسبة @user`).\n"
    )
    await ctx.send(help_text)

# ==========================================
# 3. الرد التلقائي بالذكاء الاصطناعي (Gemini)
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
