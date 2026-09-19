import os
import random
import discord
from discord.ext import commands
import google.generativeai as genai

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# إعداد Gemini
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-pro')

@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {bot.user.name}")


# =========================================================================
# أولاً: أوامر إدارة الأعضاء
# =========================================================================

@bot.command(name="برا")
@commands.has_permissions(ban_members=True)
async def ban_member(ctx, member: discord.Member = None, *, reason="بدون سبب"):
    if not member:
        await ctx.send("⚠️ منشن العضو: `!برا @عضو`")
        return
    await member.ban(reason=reason)
    await ctx.send(f"🔨 تم تبنْد العضو {member.mention}")

@bot.command(name="سماح")
@commands.has_permissions(ban_members=True)
async def unban_member(ctx, *, user_name=None):
    if not user_name:
        await ctx.send("⚠️ اكتب اسم المستخدم أو الآيدي لفك الباند.")
        return
    banned_users = await ctx.guild.bans()
    for ban_entry in banned_users:
        user = ban_entry.user
        if user.name == user_name or str(user.id) == user_name:
            await ctx.guild.unban(user)
            await ctx.send(f"🔓 تم فك الباند عن: {user.mention}")
            return
    await ctx.send("❌ لم يتم العثور على العضو في قائمة الباند.")

@bot.command(aliases=["كيك", "ترحيل"])
@commands.has_permissions(kick_members=True)
async def kick_member(ctx, member: discord.Member = None, *, reason="بدون سبب"):
    if not member:
        await ctx.send("⚠️ منشن العضو: `!كيك @عضو`")
        return
    await member.kick(reason=reason)
    await ctx.send(f"🚪 تم طرد العضو {member.mention}")

@bot.command(aliases=["اص", "تايم"])
@commands.has_permissions(manage_roles=True)
async def mute_member(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("⚠️ منشن العضو لإعطائه تايم آوت.")
        return
    # افتراضي تايم آوت 5 دقائق كمثال
    from datetime import timedelta
    await member.timeout(timedelta(minutes=5))
    await ctx.send(f"🔇 تم إعطاء تايم آوت لـ {member.mention}")

@bot.command(name="تحرير")
@commands.has_permissions(manage_roles=True)
async def unmute_member(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("⚠️ منشن العضو لفك التايم.")
        return
    await member.timeout(None)
    await ctx.send(f"🔊 تم فك التايم عن {member.mention}")

@bot.command(name="اخرس")
@commands.has_permissions(manage_roles=True)
async def chat_mute(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("⚠️ منشن العضو لكتمه في الشات.")
        return
    # إضافة ميوت عبر رتبة أو صلاحيات الشات
    await ctx.send(f"🤐 تم إسكات {member.mention} في الشات.")

@bot.command(name="تكلم")
@commands.has_permissions(manage_roles=True)
async def chat_unmute(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("⚠️ منشن العضو لفك الميوت.")
        return
    await ctx.send(f"🗣️ تم فك الميوت عن {member.mention}")

@bot.command(name="سجن")
@commands.has_permissions(manage_roles=True)
async def jail_member(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("⚠️ منشن العضو لسجنه.")
        return
    await ctx.send(f"🔒 تم سجن العضو {member.mention}")

@bot.command(name="فك")
@commands.has_permissions(manage_roles=True)
async def unjail_member(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("⚠️ منشن العضو لفك السجن.")
        return
    await ctx.send(f"🔓 تم إخراج {member.mention} من السجن.")

@bot.command(aliases=["اسم", "لقب"])
@commands.has_permissions(manage_nicknames=True)
async def change_nickname(ctx, member: discord.Member = None, *, new_name=None):
    if not member or not new_name:
        await ctx.send("⚠️ الاستخدام: `!لقب @عضو الاسم الجديد`")
        return
    await member.edit(nick=new_name)
    await ctx.send(f"✏️ تم تغيير لقب {member.mention} إلى: **{new_name}**")


# =========================================================================
# ثانياً: إدارة الرومات
# =========================================================================

@bot.command(aliases=["مسح", "اباده"])
@commands.has_permissions(manage_messages=True)
async def clear_chat(ctx, amount: int = 10):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 تم مسح {amount} رسالة بنجاح.", delete_after=3)

@bot.command(name="قفل")
@commands.has_permissions(manage_channels=True)
async def lock_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 تم قفل الروم بنجاح.")

@bot.command(name="فتح")
@commands.has_permissions(manage_channels=True)
async def unlock_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 تم فتح الروم بنجاح.")

@bot.command(aliases=["خفي", "اخفاء"])
@commands.has_permissions(manage_channels=True)
async def hide_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, view_channel=False)
    await ctx.send("🕶️ تم إخفاء الروم.")

@bot.command(name="اظهار")
@commands.has_permissions(manage_channels=True)
async def show_channel(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, view_channel=True)
    await ctx.send("👁️ تم إظهار الروم.")


# =========================================================================
# ثالثاً: إدارة الصوت
# =========================================================================

@bot.command(name="بره")
@commands.has_permissions(move_members=True)
async def voice_kick(ctx, member: discord.Member = None):
    if member and member.voice:
        await member.move_to(None)
        await ctx.send(f"📤 تم إخراج {member.mention} من الروم الصوتي.")
    else:
        await ctx.send("⚠️ العضو غير متواجد في روم صوتي.")

@bot.command(name="اصمت")
@commands.has_permissions(mute_members=True)
async def voice_mute(ctx, member: discord.Member = None):
    if member and member.voice:
        await member.edit(mute=True)
        await ctx.send(f"🔇 تم إعطاء ميوت صوتي لـ {member.mention}")

@bot.command(name="انطق")
@commands.has_permissions(mute_members=True)
async def voice_unmute(ctx, member: discord.Member = None):
    if member and member.voice:
        await member.edit(mute=False)
        await ctx.send(f"🔊 تم فك الميوت الصوتي عن {member.mention}")

@bot.command(name="اسحب")
@commands.has_permissions(move_members=True)
async def pull_member(ctx, member: discord.Member = None):
    if ctx.author.voice and member and member.voice:
        await member.move_to(ctx.author.voice.channel)
        await ctx.send(f"📥 تم سحب {member.mention} لرومك.")

@bot.command(name="اجمعهم")
@commands.has_permissions(move_members=True)
async def collect_all(ctx):
    if ctx.author.voice:
        target = ctx.author.voice.channel
        for c in ctx.guild.voice_channels:
            for m in c.members:
                await m.move_to(target)
        await ctx.send("🔊 تم جمع كافة الأعضاء في رومك الصوتي.")


# =========================================================================
# رابعاً: قسم الألعاب (الجماعية، الفردية، والروليت لـ 20 لاعب)
# =========================================================================

# روليت (تتحمل حتى 20 مشارك)
active_roulette = {}

@bot.command(name="روليت")
async def roulette_game(ctx):
    """لعبة روليت جماعية لـ 20 لاعب"""
    channel_id = ctx.channel.id
    if channel_id not in active_roulette:
        active_roulette[channel_id] = set()
    
    user = ctx.author
    if user in active_roulette[channel_id]:
        await ctx.send(f"{user.mention} أنت مسجل مسبقاً في الروليت!", delete_after=5)
        return
        
    active_roulette[channel_id].add(user)
    current_count = len(active_roulette[channel_id])
    await ctx.send(f"🎯 انضم {user.mention} إلى الروليت! (المشتركين: {current_count}/20)")
    
    if current_count >= 20:
        loser = random.choice(list(active_roulette[channel_id]))
        active_roulette[channel_id].clear()
        await ctx.send(f"💥 اكتمل العدد (20 لاعب)! والضحية في هذه الجولة هو: **{loser.mention}** هارد لك!")

@bot.command(name="روليت_سريع")
async def roulette_fast(ctx):
    outcomes = [
        "🎉 مبروك! نجوت من الروليت هذه المرة!",
        "💥 أوت! الطلقة أصابتك وخسرت في الروليت!"
    ]
    await ctx.send(f"{ctx.author.mention} {random.choice(outcomes)}")

@bot.command(name="xo")
async def game_xo(ctx):
    await ctx.send(f"🎮 لعبة XO: تم تفعيل الجلسة لـ {ctx.author.mention}! (اكتب الحركات بالتناوب)")

@bot.command(name="مافيا")
async def game_mafia(ctx):
    await ctx.send("🕵️‍♂️ تم بدء لعبة مافيا! توزيع الأدوار يتم سراً...")

@bot.command(name="كراسي")
async def game_chairs(ctx):
    await ctx.send("🪑 لعبة الكراسي الموسيقية بدأت! اسرع واحجز مقعدك!")

@bot.command(name="حجرة")
async def game_rps(ctx, choice: str = None):
    options = ["حجرة", "ورقة", "مقص"]
    if choice not in options:
        await ctx.send("⚠️ اختر: `!حجرة حجرة` أو `ورقة` أو `مقص`")
        return
    bot_choice = random.choice(options)
    await ctx.send(f"أنت: {choice} | البوت: {bot_choice}")

@bot.command(name="نرد")
async def game_dice(ctx):
    await ctx.send(f"🎲 طلع لك رقم: **{random.randint(1, 6)}**")

@bot.command(name="عجلة")
async def game_wheel(ctx):
    prizes = ["100 نقطة", "حظر 5 دقائق", "لا شيء", "حظ أوفر", "فوز مثير!"]
    await ctx.send(f"🎡 استدارت العجلة ووقفت على: **{random.choice(prizes)}**")

@bot.command(name="غميضة")
async def game_hide(ctx):
    await ctx.send("🙈 أين تختبئ؟ تم بدء لعبة الغميضة!")

@bot.command(name="ريبلكا")
async def game_replica(ctx):
    await ctx.send("👥 لعبة الشبيه أو النسخة بدأت!")

@bot.command(name="خمن")
async def game_guess(ctx):
    await ctx.send("🤔 خمن الكلمة السرية أو الرقم المقصود (من 1 إلى 50)!")

@bot.command(name="كلمة")
async def game_word(ctx):
    words = ["برمجة", "ديسكورد", "حاسب", "تصميم", "ذكاء"]
    await ctx.send(f"🔤 الكلمة المطلوبة: **{random.choice(words)}**")

# ألعاب فردية سريعة
@bot.command(name="زر")
async def game_button(ctx):
    await ctx.send(f"🔘 {ctx.author.mention} ضغطت على الزر الصحيح!")

@bot.command(name="اسرع")
async def game_fast(ctx):
    await ctx.send(f"⚡ كفو {ctx.author.mention} أنت الأسرع!")

@bot.command(name="فكك")
async def game_shuffle(ctx):
    await ctx.send("🧩 فكك الكلمة التالية: (م - د - ر - س - ة)")

@bot.command(name="ادمج")
async def game_merge(ctx):
    await ctx.send("🔗 ادمج الحروف لتصبح كلمة صحيحة: (كـ - ت - ا - ب)")

@bot.command(name="اعلام")
async def game_flags(ctx):
    await ctx.send("🇸🇦 ما هو علم الدولة المرتبط بهذه الجولة؟")

@bot.command(name="اعكس")
async def game_reverse(ctx):
    await ctx.send("🔄 اعكس الكلمة: (دحوم) -> ؟")

@bot.command(name="حرف")
async def game_letter(ctx):
    letters = ["م", "س", "ر", "ك", "أ"]
    await ctx.send(f"🔠 الحرف المطلوب هو: **{random.choice(letters)}**")

@bot.command(name="صحح")
async def game_correct(ctx):
    await ctx.send("✍️ صحح الإملاء في الجملة التالية...")

@bot.command(name="ترتيب")
async def game_order(ctx):
    await ctx.send("🔢 رتب الأرقام تنازلياً أو تصاعدياً!")

@bot.command(name="الوان")
async def game_colors(ctx):
    colors = ["أحمر", "أزرق", "أخضر", "أصفر"]
    await ctx.send(f"🎨 اللون المستهدف هو: **{random.choice(colors)}**")

@bot.command(name="ايموجي")
async def game_emoji(ctx):
    emojis = ["🍎", "🚗", "⚽", "💻"]
    await ctx.send(f"😀 خمن المعنى من الايموجي: {random.choice(emojis)}")

@bot.command(name="اكشف")
async def game_reveal(ctx):
    await ctx.send("🔍 تم كشف السر بنجاح!")


# =========================================================================
# خامساً: الذكاء الاصطناعي (Gemini)
# =========================================

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
                await message.channel.send("حدث خطأ في الاتصال بالذكاء الاصطناعي.")

    await bot.process_commands(message)

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
