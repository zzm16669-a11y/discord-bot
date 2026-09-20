import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import random
import time

# =========================================================
# الإعدادات
# =========================================================
import os

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None
)

# =========================================================
# الرتب المسموحة
# =========================================================

ADMIN = [
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]

MOD = [
    "Moderator",
    "Senior Moderator",
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]

TIMEOUT = [
    "Helper",
    "Support",
    "Junior Moderator",
    "Moderator",
    "Senior Moderator",
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]

VOICE = [
    "Moderator",
    "Senior Moderator",
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]

# =========================================================
# فحص الرتب
# =========================================================

def has_role(member, roles):
    return any(role.name in roles for role in member.roles)


async def deny(message):
    await message.reply("❌ ما عندك صلاحية تستخدم هذا الأمر.")


def can_target(author, target):
    if author == target:
        return False

    if target == author.guild.owner:
        return False

    if target.top_role >= author.top_role:
        return False

    return True


# =========================================================
# أدوات الإدارة
# =========================================================

async def admin_command(message):

    if message.author.bot:
        return False

    content = message.content.strip()

    # -----------------------------------------------------
    # برا
    # -----------------------------------------------------

    if content.startswith("برا "):
        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `برا @العضو`")
            return True

        if not can_target(message.author, target):
            await message.reply("❌ ما تقدر تستخدم الأمر على هذا العضو.")
            return True

        try:
            await target.ban(reason=f"بواسطة {message.author}")
            await message.reply(f"🔨 تم تبنيد {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ البوت ما يقدر يتبند هذا العضو بسبب ترتيب الرتب.")
        return True

    # -----------------------------------------------------
    # سماح
    # -----------------------------------------------------

    if content.startswith("سماح"):
        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        parts = content.split()

        if len(parts) < 2:
            await message.reply("استخدم: `سماح ID`")
            return True

        try:
            user_id = int(parts[1])
            user = await bot.fetch_user(user_id)
            await message.guild.unban(user)
            await message.reply(f"✅ تم فك الباند عن **{user}**.")
        except Exception:
            await message.reply("❌ ما قدرت أفك الباند. تأكد من الـ ID.")
        return True

    # -----------------------------------------------------
    # ترحيل / كيك
    # -----------------------------------------------------

    if content.startswith("ترحيل ") or content.startswith("كيك "):

        if not has_role(message.author, MOD):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `ترحيل @العضو`")
            return True

        if not can_target(message.author, target):
            await message.reply("❌ ما تقدر تطرد هذا العضو.")
            return True

        try:
            await target.kick(reason=f"بواسطة {message.author}")
            await message.reply(f"👢 تم طرد {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أطرد هذا العضو.")
        return True

    # -----------------------------------------------------
    # تايم / اص
    # -----------------------------------------------------

    if content.startswith("تايم ") or content.startswith("اص "):

        if not has_role(message.author, TIMEOUT):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `تايم @العضو`")
            return True

        if not can_target(message.author, target):
            await message.reply("❌ ما تقدر تعطي هذا العضو تايم.")
            return True

        try:
            await target.timeout(
                discord.utils.utcnow() + discord.timedelta(minutes=10),
                reason=f"تايم بواسطة {message.author}"
            )
            await message.reply(f"⏳ تم إعطاء {target.mention} تايم لمدة 10 دقائق.")
        except Exception:
            # بديل في حال discord.timedelta غير موجود
            from datetime import timedelta
            try:
                await target.timeout(
                    discord.utils.utcnow() + timedelta(minutes=10),
                    reason=f"تايم بواسطة {message.author}"
                )
                await message.reply(f"⏳ تم إعطاء {target.mention} تايم لمدة 10 دقائق.")
            except discord.Forbidden:
                await message.reply("❌ ما أقدر أعطيه تايم.")
        return True

    # -----------------------------------------------------
    # تحرير
    # -----------------------------------------------------

    if content.startswith("تحرير "):

        if not has_role(message.author, TIMEOUT):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `تحرير @العضو`")
            return True

        try:
            await target.timeout(None)
            await message.reply(f"🔓 تم فك التايم عن {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أفك التايم.")
        return True

    # -----------------------------------------------------
    # ميوت شات
    # -----------------------------------------------------

    if content.startswith("اخرس "):

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `اخرس @العضو`")
            return True

        if not can_target(message.author, target):
            await message.reply("❌ ما تقدر تسكت هذا العضو.")
            return True

        role = discord.utils.get(message.guild.roles, name="ميوت")

        if not role:
            try:
                role = await message.guild.create_role(name="ميوت")
            except discord.Forbidden:
                await message.reply("❌ ما عندي صلاحية إنشاء رتبة.")
                return True

        for channel in message.guild.text_channels:
            try:
                await channel.set_permissions(
                    role,
                    send_messages=False
                )
            except:
                pass

        try:
            await target.add_roles(role)
            await message.reply(f"🔇 تم إسكات {target.mention} في الشات.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أعطيه رتبة الميوت.")
        return True

    # -----------------------------------------------------
    # تكلم
    # -----------------------------------------------------

    if content.startswith("تكلم "):

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `تكلم @العضو`")
            return True

        role = discord.utils.get(message.guild.roles, name="ميوت")

        if role:
            try:
                await target.remove_roles(role)
                await message.reply(f"🔊 تم فك الميوت عن {target.mention}.")
            except discord.Forbidden:
                await message.reply("❌ ما أقدر أشيل رتبة الميوت.")
        else:
            await message.reply("❌ رتبة الميوت غير موجودة.")

        return True

    # -----------------------------------------------------
    # سجن
    # -----------------------------------------------------

    if content.startswith("سجن "):

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `سجن @العضو`")
            return True

        role = discord.utils.get(message.guild.roles, name="سجين")

        if not role:
            role = await message.guild.create_role(name="سجين")

        try:
            await target.add_roles(role)
            await message.reply(f"🔒 تم سجن {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أعطيه رتبة السجين.")

        return True

    # -----------------------------------------------------
    # فك
    # -----------------------------------------------------

    if content.startswith("فك "):

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `فك @العضو`")
            return True

        role = discord.utils.get(message.guild.roles, name="سجين")

        if role:
            try:
                await target.remove_roles(role)
                await message.reply(f"🔓 تم فك سجن {target.mention}.")
            except discord.Forbidden:
                await message.reply("❌ ما أقدر أشيل رتبة السجين.")
        return True

    # -----------------------------------------------------
    # لقب / اسم
    # -----------------------------------------------------

    if content.startswith("لقب ") or content.startswith("اسم "):

        if not has_role(message.author, MOD):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `لقب @العضو الاسم الجديد`")
            return True

        parts = content.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply("اكتب الاسم الجديد.")
            return True

        nickname = parts[2]

        try:
            await target.edit(nick=nickname)
            await message.reply(f"🏷️ تم تغيير لقب {target.mention} إلى **{nickname}**.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أغير لقبه.")
        return True

    # -----------------------------------------------------
    # تنزيل
    # -----------------------------------------------------

    if content.startswith("تنزيل "):

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `تنزيل @العضو`")
            return True

        roles = [
            r for r in target.roles
            if r != message.guild.default_role
            and not r.managed
            and r < message.guild.me.top_role
        ]

        if not roles:
            await message.reply("❌ ما عنده رتبة قابلة للإزالة.")
            return True

        role = max(roles, key=lambda r: r.position)

        try:
            await target.remove_roles(role)
            await message.reply(f"📉 تمت إزالة رتبة **{role.name}** من {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أشيل الرتبة.")
        return True

    # -----------------------------------------------------
    # رجع
    # -----------------------------------------------------

    if content.startswith("رجع "):

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `رجع @العضو اسم الرتبة`")
            return True

        parts = content.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply("اكتب اسم الرتبة.")
            return True

        role_name = parts[2]
        role = discord.utils.find(
            lambda r: r.name.lower() == role_name.lower(),
            message.guild.roles
        )

        if not role:
            await message.reply("❌ الرتبة غير موجودة.")
            return True

        try:
            await target.add_roles(role)
            await message.reply(f"📈 تمت إعادة رتبة **{role.name}** إلى {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أعطيه الرتبة.")

        return True

    # =====================================================
    # إدارة الرومات
    # =====================================================

    if content in ["اباده", "مسح"]:

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        try:
            await message.channel.purge(limit=100)
            msg = await message.channel.send("🧹 تم مسح الرسائل.")
            await asyncio.sleep(3)
            await msg.delete()
        except discord.Forbidden:
            await message.channel.send("❌ ما عندي صلاحية حذف الرسائل.")

        return True

    if content == "قفل":

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        await message.channel.set_permissions(
            message.guild.default_role,
            send_messages=False
        )

        await message.channel.send("🔒 تم قفل الروم.")
        return True

    if content == "فتح":

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        await message.channel.set_permissions(
            message.guild.default_role,
            send_messages=None
        )

        await message.channel.send("🔓 تم فتح الروم.")
        return True

    if content in ["اخفاء", "خفي"]:

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        await message.channel.set_permissions(
            message.guild.default_role,
            view_channel=False
        )

        await message.channel.send("👁️ تم إخفاء الروم.")
        return True

    if content == "اظهار":

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        await message.channel.set_permissions(
            message.guild.default_role,
            view_channel=True
        )

        await message.channel.send("👁️ تم إظهار الروم.")
        return True

    # =====================================================
    # إدارة الصوت
    # =====================================================

    if content.startswith("بره "):

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target or not target.voice:
            await message.reply("❌ العضو مو داخل روم صوتي.")
            return True

        try:
            await target.move_to(None)
            await message.reply(f"👢 طلعت {target.mention} من الصوت.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أطلعه من الصوت.")

        return True

    if content.startswith("اصمت "):

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target or not target.voice:
            await message.reply("❌ العضو مو داخل صوت.")
            return True

        try:
            await target.edit(mute=True)
            await message.reply(f"🔇 تم إسكات {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أسكته.")

        return True

    if content.startswith("انطق "):

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target or not target.voice:
            await message.reply("❌ العضو مو داخل صوت.")
            return True

        try:
            await target.edit(mute=False)
            await message.reply(f"🔊 تم إلغاء إسكات {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أفك إسكات العضو.")

        return True

    if content.startswith("اسحب "):

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target or not target.voice:
            await message.reply("❌ العضو مو داخل صوت.")
            return True

        if not message.author.voice:
            await message.reply("❌ ادخل روم صوتي أول.")
            return True

        try:
            await target.move_to(message.author.voice.channel)
            await message.reply(f"📥 تم سحب {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أسحبه.")

        return True

    if content.startswith("تعال ") or content.startswith("كم هير بيبي "):

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if not target or not target.voice:
            await message.reply("❌ العضو مو داخل صوت.")
            return True

        try:
            await message.author.move_to(target.voice.channel)
            await message.reply(f"📍 رحت عند {target.mention}.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أنقلك.")

        return True

    if content == "اجمعهم":

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        if not message.author.voice:
            await message.reply("❌ ادخل روم صوتي أول.")
            return True

        destination = message.author.voice.channel
        moved = 0

        for vc in message.guild.voice_channels:
            for member in list(vc.members):
                if member != message.author:
                    try:
                        await member.move_to(destination)
                        moved += 1
                    except:
                        pass

        await message.reply(f"📥 تم جمع **{moved}** عضو.")
        return True

    if content == "اطلع":

        if not has_role(message.author, ADMIN):
            await deny(message)
            return True

        if not message.author.voice:
            await message.reply("❌ ادخل الروم الصوتي أول.")
            return True

        channel = message.author.voice.channel

        for member in list(channel.members):
            if member != message.author:
                try:
                    await member.move_to(None)
                except:
                    pass

        try:
            await channel.set_permissions(
                message.guild.default_role,
                connect=False
            )
            await message.reply("🚪 تم إخراج الموجودين وقفل دخول الروم.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أقفل الروم.")

        return True

    if content.startswith("مسموح "):

        if not has_role(message.author, VOICE):
            await deny(message)
            return True

        if not message.author.voice:
            await message.reply("❌ ادخل الروم الصوتي أول.")
            return True

        target = message.mentions[0] if message.mentions else None

        if not target:
            await message.reply("استخدم: `مسموح @العضو`")
            return True

        try:
            await message.author.voice.channel.set_permissions(
                target,
                connect=True
            )
            await message.reply(f"✅ سمحت لـ {target.mention} يدخل الروم.")
        except discord.Forbidden:
            await message.reply("❌ ما أقدر أغير صلاحيات الروم.")

        return True

    return False


# =========================================================
# نظام الألعاب
# =========================================================

games = [
    "🎰 روليت",
    "❌⭕ XO",
    "🔪 مافيا",
    "🪑 كراسي",
    "✊ حجرة",
    "🎲 نرد",
    "🎡 عجلة",
    "🙈 غميضة",
    "⚡ ريبلكا",
    "🔢 خمن",
    "🔤 كلمة",
    "🔘 زر",
    "⚡ اسرع",
    "🧩 فكك",
    "🔗 ادمج",
    "🏳️ اعلام",
    "🔄 اعكس",
    "🔤 حرف",
    "✏️ صحح",
    "🔢 ترتيب",
    "🎨 الوان",
    "😀 ايموجي",
    "🔎 اكشف"
]


@bot.command(name="العاب")
async def games_list(ctx):

    embed = discord.Embed(
        title="🎮 مركز الألعاب",
        description="اختر اللعبة واستخدم أمرها من القائمة:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎮 ألعاب جماعية",
        value=(
            "`.روليت`  `.xo`  `.مافيا`\n"
            "`.كراسي`  `.حجرة`  `.نرد`\n"
            "`.عجلة`  `.غميضة`  `.ريبلكا`\n"
            "`.خمن`  `.كلمة`"
        ),
        inline=False
    )

    embed.add_field(
        name="🧠 ألعاب فردية",
        value=(
            "`.زر`  `.اسرع`  `.فكك`\n"
            "`.ادمج`  `.اعلام`  `.اعكس`\n"
            "`.حرف`  `.صحح`  `.ترتيب`\n"
            "`.الوان`  `.ايموجي`  `.اكشف`"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# Lobby
# =========================================================

class LobbyView(View):

    def __init__(self, ctx, game_name, max_players=20, min_players=2):
        super().__init__(timeout=None)

        self.ctx = ctx
        self.game_name = game_name
        self.max_players = max_players
        self.min_players = min_players
        self.players = []
        self.message = None
        self.started = False

        self.task = asyncio.create_task(self.auto_start())

    async def auto_start(self):

        await asyncio.sleep(30)

        if self.started:
            return

        self.started = True

        for item in self.children:
            item.disabled = True

        if self.message:
            try:
                await self.message.edit(
                    content=f"🎮 **{self.game_name}**\nانتهى وقت الدخول.",
                    view=self
                )
            except:
                pass

        if len(self.players) < self.min_players:

            if self.message:
                await self.message.edit(
                    content=(
                        f"❌ انتهى الوقت.\n"
                        f"احتجنا على الأقل **{self.min_players} لاعبين**."
                    ),
                    view=self
                )

            self.stop()
            return

        await self.start_game()

    @discord.ui.button(
        label="دخول",
        style=discord.ButtonStyle.green,
        emoji="🎮"
    )
    async def join(self, interaction: discord.Interaction, button: Button):

        if self.started:
            await interaction.response.send_message(
                "❌ اللعبة بدأت.",
                ephemeral=True
            )
            return

        if interaction.user in self.players:
            await interaction.response.send_message(
                "⚠️ أنت داخل اللعبة أصلًا.",
                ephemeral=True
            )
            return

        if len(self.players) >= self.max_players:
            await interaction.response.send_message(
                "❌ اللعبة ممتلئة.",
                ephemeral=True
            )
            return

        self.players.append(interaction.user)

        names = "\n".join(
            f"{i+1}. {user.mention}"
            for i, user in enumerate(self.players)
        )

        embed = discord.Embed(
            title=f"🎮 {self.game_name}",
            description=(
                "اضغط **دخول** للمشاركة.\n"
                "⏱️ تبدأ اللعبة تلقائيًا بعد **30 ثانية**.\n\n"
                f"**اللاعبون ({len(self.players)}/{self.max_players})**\n"
                f"{names}"
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.edit_message(embed=embed)

    async def start_game(self):
        pass


# =========================================================
# روليت
# =========================================================

class RouletteView(LobbyView):

    async def start_game(self):

        winner = random.choice(self.players)

        embed = discord.Embed(
            title="🎰 الروليت",
            description=(
                f"عدد اللاعبين: **{len(self.players)}**\n\n"
                f"💥 خرجت الرصاصة على:\n"
                f"## {winner.mention}"
            ),
            color=discord.Color.red()
        )

        await self.message.edit(embed=embed, view=self)
        self.stop()


@bot.command(name="روليت")
async def roulette(ctx):

    view = RouletteView(ctx, "🎰 الروليت", max_players=20)

    embed = discord.Embed(
        title="🎰 الروليت",
        description=(
            "اضغط **دخول** للمشاركة.\n"
            "⏱️ عند انتهاء الـ30 ثانية تبدأ اللعبة تلقائيًا.\n\n"
            "👥 الحد الأقصى: **20 لاعب**"
        ),
        color=discord.Color.red()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# نرد
# =========================================================

class DiceView(LobbyView):

    async def start_game(self):

        rolls = []

        for player in self.players:
            number = random.randint(1, 6)
            rolls.append((player, number))

        rolls.sort(key=lambda x: x[1], reverse=True)

        text = "\n".join(
            f"🎲 {player.mention} — **{number}**"
            for player, number in rolls
        )

        winner = rolls[0][0]

        embed = discord.Embed(
            title="🎲 النرد",
            description=(
                f"{text}\n\n"
                f"🏆 الفائز: {winner.mention}"
            ),
            color=discord.Color.gold()
        )

        await self.message.edit(embed=embed, view=self)
        self.stop()


@bot.command(name="نرد")
async def dice(ctx):

    view = DiceView(ctx, "🎲 النرد")

    embed = discord.Embed(
        title="🎲 النرد",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.gold()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# عجلة
# =========================================================

class WheelView(LobbyView):

    async def start_game(self):

        await self.message.edit(
            content="🎡 جاري تدوير العجلة...",
            embed=None,
            view=None
        )

        await asyncio.sleep(2)

        winner = random.choice(self.players)

        embed = discord.Embed(
            title="🎡 العجلة",
            description=f"🎉 الفائز هو {winner.mention}!",
            color=discord.Color.green()
        )

        await self.message.edit(content=None, embed=embed)
        self.stop()


@bot.command(name="عجلة")
async def wheel(ctx):

    view = WheelView(ctx, "🎡 العجلة")

    embed = discord.Embed(
        title="🎡 العجلة",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.green()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# كراسي
# =========================================================

class ChairsView(LobbyView):

    async def start_game(self):

        players = self.players.copy()

        while len(players) > 1:

            await asyncio.sleep(1)

            eliminated = random.choice(players)
            players.remove(eliminated)

            embed = discord.Embed(
                title="🪑 لعبة الكراسي",
                description=(
                    f"💺 انتهت الجولة!\n"
                    f"❌ خرج {eliminated.mention}\n\n"
                    f"👥 المتبقين: **{len(players)}**"
                ),
                color=discord.Color.orange()
            )

            await self.message.edit(embed=embed)

        winner = players[0]

        embed = discord.Embed(
            title="🪑 لعبة الكراسي",
            description=f"🏆 آخر شخص بقي هو {winner.mention}!",
            color=discord.Color.green()
        )

        await self.message.edit(embed=embed, view=self)
        self.stop()


@bot.command(name="كراسي")
async def chairs(ctx):

    view = ChairsView(ctx, "🪑 الكراسي")

    embed = discord.Embed(
        title="🪑 لعبة الكراسي",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.orange()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# حجرة
# =========================================================

class RPSView(LobbyView):

    async def start_game(self):

        choices = ["✊ حجر", "📄 ورقة", "✂️ مقص"]

        results = []

        for player in self.players:
            choice = random.choice(choices)
            results.append((player, choice))

        text = "\n".join(
            f"{player.mention} → **{choice}**"
            for player, choice in results
        )

        winner = random.choice(self.players)

        embed = discord.Embed(
            title="✊ حجرة ورقة مقص",
            description=(
                f"{text}\n\n"
                f"🏆 الفائز: {winner.mention}"
            ),
            color=discord.Color.blurple()
        )

        await self.message.edit(embed=embed, view=self)
        self.stop()


@bot.command(name="حجرة")
async def rps(ctx):

    view = RPSView(ctx, "✊ حجرة ورقة مقص")

    embed = discord.Embed(
        title="✊ حجرة ورقة مقص",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.blurple()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# XO
# =========================================================

class XOBoard(View):

    def __init__(self, message, players):
        super().__init__(timeout=120)

        self.message = message
        self.players = players
        self.board = [""] * 9
        self.turn = 0
        self.symbols = {
            players[0]: "❌",
            players[1]: "⭕"
        }

        for i in range(9):
            self.add_item(XOButton(i, self))

    def check_winner(self):

        wins = [
            (0,1,2),(3,4,5),(6,7,8),
            (0,3,6),(1,4,7),(2,5,8),
            (0,4,8),(2,4,6)
        ]

        for a,b,c in wins:
            if (
                self.board[a]
                and self.board[a] == self.board[b]
                and self.board[a] == self.board[c]
            ):
                return self.board[a]

        if all(self.board):
            return "draw"

        return None


class XOButton(Button):

    def __init__(self, index, game):
        super().__init__(
            label="ㅤ",
            style=discord.ButtonStyle.secondary,
            row=index // 3
        )

        self.index = index
        self.game = game

    async def callback(self, interaction):

        game = self.game

        current_player = game.players[game.turn]

        if interaction.user != current_player:
            await interaction.response.send_message(
                "⏳ مو دورك.",
                ephemeral=True
            )
            return

        if game.board[self.index]:
            await interaction.response.send_message(
                "❌ هذا المكان مأخوذ.",
                ephemeral=True
            )
            return

        symbol = game.symbols[interaction.user]

        game.board[self.index] = symbol
        self.label = symbol
        self.disabled = True

        winner = game.check_winner()

        if winner:

            if winner == "draw":
                text = "🤝 تعادل!"
            else:
                winner_user = next(
                    user for user in game.players
                    if game.symbols[user] == winner
                )
                text = f"🏆 الفائز: {winner_user.mention}"

            for child in game.children:
                child.disabled = True

            await interaction.response.edit_message(
                content=text,
                view=game
            )

            game.stop()
            return

        game.turn = 1 - game.turn

        await interaction.response.edit_message(
            content=(
                f"❌ {game.players[0].mention}\n"
                f"⭕ {game.players[1].mention}\n\n"
                f"🎯 الدور: {game.players[game.turn].mention}"
            ),
            view=game
        )


class XOLobby(LobbyView):

    async def start_game(self):

        board = XOBoard(
            self.message,
            self.players
        )

        await self.message.edit(
            content=(
                f"❌ {self.players[0].mention}\n"
                f"⭕ {self.players[1].mention}\n\n"
                f"🎯 الدور: {self.players[0].mention}"
            ),
            view=board
        )


@bot.command(name="xo")
async def xo(ctx):

    view = XOLobby(
        ctx,
        "❌⭕ XO",
        max_players=2,
        min_players=2
    )

    embed = discord.Embed(
        title="❌⭕ XO",
        description=(
            "لاعبين فقط.\n"
            "اضغط **دخول** للمشاركة.\n"
            "⏱️ تبدأ اللعبة بعد 30 ثانية."
        ),
        color=discord.Color.blurple()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# ألعاب جماعية بسيطة
# =========================================================

class SimpleRandomGame(LobbyView):

    def __init__(self, ctx, game_name, emoji, color):
        super().__init__(ctx, game_name)
        self.emoji = emoji
        self.color = color

    async def start_game(self):

        winner = random.choice(self.players)

        embed = discord.Embed(
            title=f"{self.emoji} {self.game_name}",
            description=(
                f"👥 المشاركون: **{len(self.players)}**\n\n"
                f"🏆 الفائز العشوائي:\n"
                f"## {winner.mention}"
            ),
            color=self.color
        )

        await self.message.edit(embed=embed, view=self)
        self.stop()


@bot.command(name="مافيا")
async def mafia(ctx):

    if ctx.guild is None:
        return

    view = SimpleRandomGame(
        ctx,
        "مافيا",
        "🔪",
        discord.Color.dark_red()
    )

    embed = discord.Embed(
        title="🔪 المافيا",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.dark_red()
    )

    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name="غميضة")
async def hide_seek(ctx):

    view = SimpleRandomGame(
        ctx,
        "غميضة",
        "🙈",
        discord.Color.green()
    )

    embed = discord.Embed(
        title="🙈 غميضة",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.green()
    )

    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name="ريبلكا")
async def replica(ctx):

    view = SimpleRandomGame(
        ctx,
        "ريبلكا",
        "⚡",
        discord.Color.purple()
    )

    embed = discord.Embed(
        title="⚡ ريبلكا",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.purple()
    )

    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name="خمن")
async def guess(ctx):

    view = SimpleRandomGame(
        ctx,
        "خمن",
        "🔢",
        discord.Color.blue()
    )

    embed = discord.Embed(
        title="🔢 خمن",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.blue()
    )

    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name="كلمة")
async def word(ctx):

    view = SimpleRandomGame(
        ctx,
        "كلمة",
        "🔤",
        discord.Color.orange()
    )

    embed = discord.Embed(
        title="🔤 كلمة",
        description="اضغط **دخول** للمشاركة.\n⏱️ تبدأ بعد 30 ثانية.",
        color=discord.Color.orange()
    )

    view.message = await ctx.send(embed=embed, view=view)


# =========================================================
# الألعاب الفردية
# =========================================================

@bot.command(name="زر")
async def button_game(ctx):

    embed = discord.Embed(
        title="🔘 اضغط الزر",
        description="اضغط الزر بأسرع ما تقدر!",
        color=discord.Color.green()
    )

    view = View(timeout=30)

    button = Button(
        label="اضغط!",
        style=discord.ButtonStyle.green
    )

    async def callback(interaction):

        button.disabled = True

        await interaction.response.edit_message(
            content=f"⚡ {interaction.user.mention} ضغط الزر!",
            embed=embed,
            view=view
        )

        view.stop()

    button.callback = callback
    view.add_item(button)

    await ctx.send(embed=embed, view=view)


@bot.command(name="اسرع")
async def fastest(ctx):

    answer = random.choice([
        "تفاحة",
        "سيارة",
        "مطر",
        "قمر",
        "نجم",
        "بحر"
    ])

    await ctx.send(
        f"⚡ أول شخص يكتب:\n"
        f"**{answer}**\n"
        f"هو الفائز!"
    )

    def check(m):
        return (
            m.channel == ctx.channel
            and not m.author.bot
            and m.content.strip() == answer
        )

    try:
        winner = await bot.wait_for(
            "message",
            timeout=15,
            check=check
        )

        await ctx.send(
            f"🏆 أسرع واحد: {winner.author.mention}"
        )

    except asyncio.TimeoutError:
        await ctx.send("⌛ انتهى الوقت.")


@bot.command(name="فكك")
async def decompose(ctx):

    word = random.choice([
        "ديسكورد",
        "كمبيوتر",
        "سيارة",
        "مملكة",
        "امبراطورية"
    ])

    spaced = " ".join(word)

    await ctx.send(
        f"🧩 فكك الكلمة:\n\n"
        f"**{spaced}**"
    )


@bot.command(name="ادمج")
async def merge(ctx):

    words = random.sample(
        ["قمر", "بحر", "ليل", "ملك", "ذهب", "نار"],
        2
    )

    await ctx.send(
        f"🔗 ادمج الكلمتين:\n"
        f"**{words[0]} + {words[1]}**"
    )


@bot.command(name="اعلام")
async def flags(ctx):

    flags = [
        "🇸🇦 السعودية",
        "🇰🇼 الكويت",
        "🇦🇪 الإمارات",
        "🇶🇦 قطر",
        "🇴🇲 عمان",
        "🇧🇭 البحرين"
    ]

    await ctx.send(
        f"🏳️ العلم:\n\n"
        f"**{random.choice(flags)}**"
    )


@bot.command(name="اعكس")
async def reverse(ctx):

    word = random.choice([
        "ديسكورد",
        "مازن",
        "امبراطورية",
        "سيرفر"
    ])

    await ctx.send(
        f"🔄 اعكس الكلمة:\n"
        f"**{word}**"
    )


@bot.command(name="حرف")
async def letter(ctx):

    letter = random.choice(list("ابتثجحخدذرزسشصضطظعغفقكلمنهوي"))

    await ctx.send(
        f"🔤 حرفك هو:\n## {letter}"
    )


@bot.command(name="صحح")
async def correct(ctx):

    text = random.choice([
        "انا ذهبت المدرسه",
        "هو يلعب لعبه",
        "نحن ذهبنا الى البيت"
    ])

    await ctx.send(
        f"✏️ صحح الجملة:\n\n"
        f"**{text}**"
    )


@bot.command(name="ترتيب")
async def order(ctx):

    numbers = random.sample(range(1, 6), 5)

    await ctx.send(
        f"🔢 رتب الأرقام من الأصغر للأكبر:\n\n"
        f"**{' - '.join(map(str, numbers))}**"
    )


@bot.command(name="الوان")
async def colors(ctx):

    colors = [
        "🔴 أحمر",
        "🔵 أزرق",
        "🟢 أخضر",
        "🟡 أصفر",
        "🟣 بنفسجي",
        "🟠 برتقالي"
    ]

    await ctx.send(
        f"🎨 اللون المختار:\n\n"
        f"## {random.choice(colors)}"
    )


@bot.command(name="ايموجي")
async def emoji_game(ctx):

    emojis = [
        "😀", "😂", "🔥", "👑",
        "🎮", "⚡", "🐺", "🦅"
    ]

    await ctx.send(
        f"😀 إيموجيك:\n\n"
        f"## {random.choice(emojis)}"
    )


@bot.command(name="اكشف")
async def reveal(ctx):

    things = [
        "🎁 جائزة سرية",
        "💎 ألماسة",
        "👑 تاج",
        "💰 كنز",
        "⚔️ سلاح أسطوري"
    ]

    await ctx.send(
        f"🔎 فتحت الصندوق...\n\n"
        f"## {random.choice(things)}"
    )


# =========================================================
# تشغيل الأوامر الإدارية بدون نقطة
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    handled = await admin_command(message)

    if not handled:
        await bot.process_commands(message)


# =========================================================
# تشغيل البوت
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"تم تشغيل البوت: {bot.user}")
    print(f"ID: {bot.user.id}")
    print("=" * 50)


bot.run(TOKEN)
