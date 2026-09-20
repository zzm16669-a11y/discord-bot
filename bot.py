import os
import asyncio
import random
from datetime import timedelta

import discord
from discord.ext import commands
from discord.ui import View, Button


# =========================================================
# إعدادات البوت
# =========================================================

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

ADMIN_ROLES = [
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]

MOD_ROLES = [
    "Moderator",
    "Senior Moderator",
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]

TIMEOUT_ROLES = [
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

VOICE_ROLES = [
    "Moderator",
    "Senior Moderator",
    "Administrator",
    "Executive",
    "Co-Owner",
    "Owner"
]


# =========================================================
# أدوات مساعدة
# =========================================================

def has_role(member, allowed_roles):
    return any(role.name in allowed_roles for role in member.roles)


async def no_permission(message):
    await message.reply("❌ ما عندك صلاحية تستخدم هذا الأمر.")


def can_target(author, target):
    if author.id == target.id:
        return False

    if target.guild.owner_id == target.id:
        return False

    if target.top_role >= author.top_role:
        return False

    return True


# =========================================================
# أوامر الإدارة بدون نقطة
# =========================================================

async def admin_command(message):

    if message.author.bot:
        return False

    content = message.content.strip()

    # =====================================================
    # إدارة الأعضاء
    # =====================================================

    # برا
    if content.startswith("برا "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply("استخدم: `برا @العضو`")
            return True

        if not can_target(message.author, target):
            await message.reply("❌ ما تقدر تستخدم الأمر على هذا العضو.")
            return True

        try:
            await target.ban(
                reason=f"Ban بواسطة {message.author}"
            )
            await message.reply(
                f"🔨 تم تبنيد {target.mention}."
            )
        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يبند هذا العضو."
            )

        return True

    # سماح
    if content.startswith("سماح"):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        parts = content.split()

        if len(parts) < 2:
            await message.reply(
                "استخدم: `سماح ID`"
            )
            return True

        try:
            user_id = int(parts[1])
            user = await bot.fetch_user(user_id)

            await message.guild.unban(
                user,
                reason=f"Unban بواسطة {message.author}"
            )

            await message.reply(
                f"✅ تم فك الباند عن **{user}**."
            )

        except ValueError:
            await message.reply("❌ الـ ID غير صحيح.")

        except discord.NotFound:
            await message.reply("❌ هذا العضو غير موجود في قائمة الباند.")

        except discord.Forbidden:
            await message.reply("❌ البوت ما عنده صلاحية فك الباند.")

        return True

    # ترحيل / كيك
    if content.startswith("ترحيل ") or content.startswith("كيك "):

        if not has_role(message.author, MOD_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `ترحيل @العضو`"
            )
            return True

        if not can_target(message.author, target):
            await message.reply(
                "❌ ما تقدر تطرد هذا العضو."
            )
            return True

        try:
            await target.kick(
                reason=f"Kick بواسطة {message.author}"
            )

            await message.reply(
                f"👢 تم طرد {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يطرد هذا العضو."
            )

        return True

    # تايم / اص
    if content.startswith("تايم ") or content.startswith("اص "):

        if not has_role(message.author, TIMEOUT_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `تايم @العضو`"
            )
            return True

        if not can_target(message.author, target):
            await message.reply(
                "❌ ما تقدر تعطي هذا العضو تايم."
            )
            return True

        try:
            await target.timeout(
                timedelta(minutes=10),
                reason=f"Timeout بواسطة {message.author}"
            )

            await message.reply(
                f"⏳ تم إعطاء {target.mention} تايم لمدة 10 دقائق."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يعطي هذا العضو تايم."
            )

        return True

    # تحرير
    if content.startswith("تحرير "):

        if not has_role(message.author, TIMEOUT_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `تحرير @العضو`"
            )
            return True

        try:
            await target.timeout(
                None,
                reason=f"Remove timeout بواسطة {message.author}"
            )

            await message.reply(
                f"🔓 تم فك التايم عن {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يفك التايم."
            )

        return True

    # اخرس
    if content.startswith("اخرس "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `اخرس @العضو`"
            )
            return True

        if not can_target(message.author, target):
            await message.reply(
                "❌ ما تقدر تسكت هذا العضو."
            )
            return True

        role = discord.utils.get(
            message.guild.roles,
            name="ميوت"
        )

        if role is None:
            try:
                role = await message.guild.create_role(
                    name="ميوت",
                    reason="إنشاء رتبة الميوت"
                )
            except discord.Forbidden:
                await message.reply(
                    "❌ البوت ما عنده صلاحية إنشاء الرتب."
                )
                return True

        for channel in message.guild.text_channels:
            try:
                await channel.set_permissions(
                    role,
                    send_messages=False
                )
            except discord.Forbidden:
                pass

        try:
            await target.add_roles(
                role,
                reason=f"Chat mute بواسطة {message.author}"
            )

            await message.reply(
                f"🔇 تم إسكات {target.mention} في الشات."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يعطي رتبة الميوت."
            )

        return True

    # تكلم
    if content.startswith("تكلم "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `تكلم @العضو`"
            )
            return True

        role = discord.utils.get(
            message.guild.roles,
            name="ميوت"
        )

        if role is None:
            await message.reply(
                "❌ رتبة الميوت غير موجودة."
            )
            return True

        try:
            await target.remove_roles(
                role,
                reason=f"Unmute بواسطة {message.author}"
            )

            await message.reply(
                f"🔊 تم فك الميوت عن {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يشيل رتبة الميوت."
            )

        return True

    # سجن
    if content.startswith("سجن "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `سجن @العضو`"
            )
            return True

        if not can_target(message.author, target):
            await message.reply(
                "❌ ما تقدر تسجن هذا العضو."
            )
            return True

        role = discord.utils.get(
            message.guild.roles,
            name="سجين"
        )

        if role is None:
            try:
                role = await message.guild.create_role(
                    name="سجين",
                    reason="إنشاء رتبة السجين"
                )
            except discord.Forbidden:
                await message.reply(
                    "❌ ما أقدر أنشئ رتبة السجين."
                )
                return True

        try:
            await target.add_roles(
                role,
                reason=f"Jail بواسطة {message.author}"
            )

            await message.reply(
                f"🔒 تم سجن {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يعطي رتبة السجين."
            )

        return True

    # فك
    if content.startswith("فك "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `فك @العضو`"
            )
            return True

        role = discord.utils.get(
            message.guild.roles,
            name="سجين"
        )

        if role is None:
            await message.reply(
                "❌ رتبة السجين غير موجودة."
            )
            return True

        try:
            await target.remove_roles(
                role,
                reason=f"Unjail بواسطة {message.author}"
            )

            await message.reply(
                f"🔓 تم فك سجن {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يشيل رتبة السجين."
            )

        return True

    # لقب / اسم
    if content.startswith("لقب ") or content.startswith("اسم "):

        if not has_role(message.author, MOD_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `لقب @العضو الاسم الجديد`"
            )
            return True

        parts = content.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply(
                "❌ اكتب الاسم الجديد."
            )
            return True

        nickname = parts[2]

        try:
            await target.edit(
                nick=nickname,
                reason=f"Nickname بواسطة {message.author}"
            )

            await message.reply(
                f"🏷️ تم تغيير لقب {target.mention} إلى **{nickname}**."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يغير لقب العضو."
            )

        return True

    # تنزيل
    if content.startswith("تنزيل "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `تنزيل @العضو`"
            )
            return True

        manageable_roles = [
            role
            for role in target.roles
            if role != message.guild.default_role
            and not role.managed
            and role < message.guild.me.top_role
        ]

        if not manageable_roles:
            await message.reply(
                "❌ ما عنده رتبة قابلة للإزالة."
            )
            return True

        role = max(
            manageable_roles,
            key=lambda r: r.position
        )

        try:
            await target.remove_roles(
                role,
                reason=f"Remove role بواسطة {message.author}"
            )

            await message.reply(
                f"📉 تمت إزالة رتبة **{role.name}** من {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يشيل الرتبة."
            )

        return True

    # رجع
    if content.startswith("رجع "):

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `رجع @العضو اسم الرتبة`"
            )
            return True

        parts = content.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply(
                "❌ اكتب اسم الرتبة."
            )
            return True

        role_name = parts[2]

        role = discord.utils.find(
            lambda r: r.name.lower() == role_name.lower(),
            message.guild.roles
        )

        if role is None:
            await message.reply(
                "❌ الرتبة غير موجودة."
            )
            return True

        try:
            await target.add_roles(
                role,
                reason=f"Add role بواسطة {message.author}"
            )

            await message.reply(
                f"📈 تمت إضافة رتبة **{role.name}** إلى {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ البوت ما يقدر يعطي الرتبة."
            )

        return True

    # =====================================================
    # إدارة الرومات
    # =====================================================

    # اباده / مسح
    if content in ["اباده", "مسح"]:

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        try:
            deleted = await message.channel.purge(
                limit=100
            )

            confirmation = await message.channel.send(
                f"🧹 تم مسح **{len(deleted)}** رسالة."
            )

            await asyncio.sleep(3)

            try:
                await confirmation.delete()
            except discord.NotFound:
                pass

        except discord.Forbidden:
            await message.channel.send(
                "❌ ما عندي صلاحية حذف الرسائل."
            )

        return True

    # قفل
    if content == "قفل":

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        try:
            await message.channel.set_permissions(
                message.guild.default_role,
                send_messages=False
            )

            await message.channel.send(
                "🔒 تم قفل الروم."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أعدل صلاحيات الروم."
            )

        return True

    # فتح
    if content == "فتح":

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        try:
            await message.channel.set_permissions(
                message.guild.default_role,
                send_messages=None
            )

            await message.channel.send(
                "🔓 تم فتح الروم."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أعدل صلاحيات الروم."
            )

        return True

    # اخفاء / خفي
    if content in ["اخفاء", "خفي"]:

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        try:
            await message.channel.set_permissions(
                message.guild.default_role,
                view_channel=False
            )

            await message.channel.send(
                "👁️ تم إخفاء الروم."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أخفي الروم."
            )

        return True

    # اظهار
    if content == "اظهار":

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        try:
            await message.channel.set_permissions(
                message.guild.default_role,
                view_channel=True
            )

            await message.channel.send(
                "👁️ تم إظهار الروم."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أظهر الروم."
            )

        return True

    # =====================================================
    # إدارة الصوت
    # =====================================================

    # بره
    if content.startswith("بره "):

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None or target.voice is None:
            await message.reply(
                "❌ العضو مو داخل روم صوتي."
            )
            return True

        try:
            await target.move_to(None)

            await message.reply(
                f"👢 تم إخراج {target.mention} من الصوت."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أطلعه من الصوت."
            )

        return True

    # اصمت
    if content.startswith("اصمت "):

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None or target.voice is None:
            await message.reply(
                "❌ العضو مو داخل روم صوتي."
            )
            return True

        try:
            await target.edit(
                mute=True,
                reason=f"Server mute بواسطة {message.author}"
            )

            await message.reply(
                f"🔇 تم إسكات {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أسكته."
            )

        return True

    # انطق
    if content.startswith("انطق "):

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None or target.voice is None:
            await message.reply(
                "❌ العضو مو داخل روم صوتي."
            )
            return True

        try:
            await target.edit(
                mute=False,
                reason=f"Server unmute بواسطة {message.author}"
            )

            await message.reply(
                f"🔊 تم فك إسكات {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أفك الإسكات."
            )

        return True

    # اسحب
    if content.startswith("اسحب "):

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None or target.voice is None:
            await message.reply(
                "❌ العضو مو داخل روم صوتي."
            )
            return True

        if message.author.voice is None:
            await message.reply(
                "❌ ادخل روم صوتي أول."
            )
            return True

        try:
            await target.move_to(
                message.author.voice.channel
            )

            await message.reply(
                f"📥 تم سحب {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أسحب العضو."
            )

        return True

    # كم هير بيبي / تعال
    if (
        content.startswith("كم هير بيبي ")
        or content.startswith("تعال ")
    ):

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None or target.voice is None:
            await message.reply(
                "❌ العضو مو داخل روم صوتي."
            )
            return True

        try:
            await message.author.move_to(
                target.voice.channel
            )

            await message.reply(
                f"📍 تم نقلك عند {target.mention}."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أنقلك."
            )

        return True

    # اجمعهم
    if content == "اجمعهم":

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        if message.author.voice is None:
            await message.reply(
                "❌ ادخل روم صوتي أول."
            )
            return True

        destination = message.author.voice.channel
        moved = 0

        for voice_channel in message.guild.voice_channels:

            for member in list(voice_channel.members):

                if member.id == message.author.id:
                    continue

                try:
                    await member.move_to(destination)
                    moved += 1
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass

        await message.reply(
            f"📥 تم جمع **{moved}** عضو في رومك."
        )

        return True

    # اطلع
    if content == "اطلع":

        if not has_role(message.author, ADMIN_ROLES):
            await no_permission(message)
            return True

        if message.author.voice is None:
            await message.reply(
                "❌ ادخل الروم الصوتي أول."
            )
            return True

        channel = message.author.voice.channel

        kicked = 0

        for member in list(channel.members):

            if member.id == message.author.id:
                continue

            try:
                await member.move_to(None)
                kicked += 1
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass

        try:
            await channel.set_permissions(
                message.guild.default_role,
                connect=False
            )

            await message.reply(
                f"🚪 تم إخراج **{kicked}** أعضاء وقفل دخول الروم."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ تم إخراج الموجودين لكن ما قدرت أقفل الروم."
            )

        return True

    # مسموح
    if content.startswith("مسموح "):

        if not has_role(message.author, VOICE_ROLES):
            await no_permission(message)
            return True

        if message.author.voice is None:
            await message.reply(
                "❌ ادخل الروم الصوتي أول."
            )
            return True

        target = message.mentions[0] if message.mentions else None

        if target is None:
            await message.reply(
                "استخدم: `مسموح @العضو`"
            )
            return True

        try:
            await message.author.voice.channel.set_permissions(
                target,
                connect=True
            )

            await message.reply(
                f"✅ سمحت لـ {target.mention} يدخل الروم."
            )

        except discord.Forbidden:
            await message.reply(
                "❌ ما أقدر أعدل صلاحيات الروم."
            )

        return True

    return False


# =========================================================
# نظام اللوبي
# =========================================================

class LobbyView(View):

    def __init__(
        self,
        ctx,
        game_name,
        max_players=20,
        min_players=2
    ):

        super().__init__(timeout=None)

        self.ctx = ctx
        self.game_name = game_name
        self.max_players = max_players
        self.min_players = min_players

        self.players = []
        self.message = None
        self.started = False

        # مؤقت ثابت 30 ثانية
        self.start_task = asyncio.create_task(
            self.auto_start()
        )

    def make_embed(self):

        if self.players:

            players_text = "\n".join(
                f"`{i + 1}` {player.mention}"
                for i, player in enumerate(self.players)
            )

        else:

            players_text = "لا يوجد لاعبين حتى الآن."

        embed = discord.Embed(
            title=f"🎮 {self.game_name}",
            description=(
                "اضغط **دخول** للمشاركة.\n"
                "إذا غيرت رأيك اضغط **خروج**.\n\n"
                f"👥 **اللاعبون: "
                f"{len(self.players)}/{self.max_players}**\n\n"
                f"{players_text}\n\n"
                "⏱️ تبدأ اللعبة تلقائيًا بعد **30 ثانية**."
            ),
            color=discord.Color.default()
        )

        return embed

    async def auto_start(self):

        await asyncio.sleep(30)

        if self.started:
            return

        self.started = True

        # تعطيل جميع الأزرار
        for child in self.children:
            child.disabled = True

        # تحديث اللوبي
        if self.message:

            try:
                await self.message.edit(
                    embed=self.make_embed(),
                    view=self
                )
            except discord.HTTPException:
                pass

        # عدد اللاعبين غير كافي
        if len(self.players) < self.min_players:

            embed = discord.Embed(
                title=f"❌ {self.game_name}",
                description=(
                    "انتهى وقت التسجيل.\n\n"
                    f"المطلوب: **{self.min_players}** لاعبين.\n"
                    f"الموجود: **{len(self.players)}**."
                ),
                color=discord.Color.default()
            )

            try:
                await self.message.edit(
                    embed=embed,
                    view=self
                )
            except discord.HTTPException:
                pass

            self.stop()
            return

        await self.start_game()

    # =====================================================
    # دخول
    # =====================================================

    @discord.ui.button(
        label="دخول",
        emoji="🎮",
        style=discord.ButtonStyle.secondary
    )
    async def join(
        self,
        interaction: discord.Interaction,
        button: Button
    ):

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

        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self
        )

    # =====================================================
    # خروج
    # =====================================================

    @discord.ui.button(
        label="خروج",
        emoji="🚪",
        style=discord.ButtonStyle.secondary
    )
    async def leave(
        self,
        interaction: discord.Interaction,
        button: Button
    ):

        if self.started:

            await interaction.response.send_message(
                "❌ اللعبة بدأت.",
                ephemeral=True
            )
            return

        if interaction.user not in self.players:

            await interaction.response.send_message(
                "⚠️ أنت مو داخل اللعبة.",
                ephemeral=True
            )
            return

        self.players.remove(interaction.user)

        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self
        )

    async def start_game(self):
        pass


# =========================================================
# الروليت
# =========================================================

class RouletteLobby(LobbyView):

    async def start_game(self):

        winner = random.choice(self.players)

        embed = discord.Embed(
            title="🎰 الروليت",
            description=(
                f"👥 عدد اللاعبين: **{len(self.players)}**\n\n"
                f"💥 وقع الاختيار على:\n\n"
                f"## {winner.mention}"
            ),
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        self.stop()


@bot.command(name="روليت")
async def roulette(ctx):

    view = RouletteLobby(
        ctx,
        "🎰 الروليت",
        max_players=20,
        min_players=2
    )

    embed = view.make_embed()

    view.message = await ctx.send(
        embed=embed,
        view=view
    )


# =========================================================
# النرد
# =========================================================

class DiceLobby(LobbyView):

    async def start_game(self):

        results = []

        for player in self.players:

            number = random.randint(1, 6)

            results.append(
                (player, number)
            )

        highest = max(
            number
            for _, number in results
        )

        winners = [
            player
            for player, number in results
            if number == highest
        ]

        results_text = "\n".join(
            f"🎲 {player.mention} — **{number}**"
            for player, number in results
        )

        winner_text = ", ".join(
            player.mention
            for player in winners
        )

        embed = discord.Embed(
            title="🎲 النرد",
            description=(
                f"{results_text}\n\n"
                f"🏆 الفائز: {winner_text}"
            ),
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        self.stop()


@bot.command(name="نرد")
async def dice(ctx):

    view = DiceLobby(
        ctx,
        "🎲 النرد",
        max_players=20,
        min_players=2
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# =========================================================
# العجلة
# =========================================================

class WheelLobby(LobbyView):

    async def start_game(self):

        embed = discord.Embed(
            title="🎡 العجلة",
            description="🎡 جاري تدوير العجلة...",
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        await asyncio.sleep(2)

        winner = random.choice(self.players)

        embed = discord.Embed(
            title="🎡 العجلة",
            description=(
                f"🎉 توقفت العجلة على:\n\n"
                f"## {winner.mention}"
            ),
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        self.stop()


@bot.command(name="عجلة")
async def wheel(ctx):

    view = WheelLobby(
        ctx,
        "🎡 العجلة",
        max_players=20,
        min_players=2
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# =========================================================
# الكراسي
# =========================================================

class ChairsLobby(LobbyView):

    async def start_game(self):

        players = self.players.copy()

        while len(players) > 1:

            await asyncio.sleep(1)

            eliminated = random.choice(players)

            players.remove(eliminated)

            remaining = "\n".join(
                player.mention
                for player in players
            )

            embed = discord.Embed(
                title="🪑 الكراسي",
                description=(
                    f"❌ خرج {eliminated.mention}\n\n"
                    f"👥 المتبقين: **{len(players)}**\n\n"
                    f"{remaining}"
                ),
                color=discord.Color.default()
            )

            await self.message.edit(
                embed=embed,
                view=self
            )

        winner = players[0]

        embed = discord.Embed(
            title="🪑 الكراسي",
            description=(
                f"🏆 الفائز الأخير:\n\n"
                f"## {winner.mention}"
            ),
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        self.stop()


@bot.command(name="كراسي")
async def chairs(ctx):

    view = ChairsLobby(
        ctx,
        "🪑 الكراسي",
        max_players=20,
        min_players=2
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# =========================================================
# حجرة ورقة مقص
# =========================================================

class RPSLobby(LobbyView):

    async def start_game(self):

        choices = [
            "✊ حجر",
            "📄 ورقة",
            "✂️ مقص"
        ]

        results = []

        for player in self.players:

            choice = random.choice(choices)

            results.append(
                (player, choice)
            )

        text = "\n".join(
            f"{player.mention} → **{choice}**"
            for player, choice in results
        )

        winner = random.choice(self.players)

        embed = discord.Embed(
            title="✊ حجرة ورقة مقص",
            description=(
                f"{text}\n\n"
                f"🏆 الفائز:\n"
                f"## {winner.mention}"
            ),
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        self.stop()


@bot.command(name="حجرة")
async def rock_paper_scissors(ctx):

    view = RPSLobby(
        ctx,
        "✊ حجرة ورقة مقص",
        max_players=20,
        min_players=2
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# =========================================================
# ألعاب جماعية عشوائية
# =========================================================

class RandomGameLobby(LobbyView):

    def __init__(
        self,
        ctx,
        game_name,
        emoji,
        max_players=20,
        min_players=2
    ):

        self.emoji = emoji

        super().__init__(
            ctx,
            game_name,
            max_players,
            min_players
        )

    async def start_game(self):

        winner = random.choice(self.players)

        embed = discord.Embed(
            title=f"{self.emoji} {self.game_name}",
            description=(
                f"👥 المشاركون: **{len(self.players)}**\n\n"
                f"🏆 الفائز:\n\n"
                f"## {winner.mention}"
            ),
            color=discord.Color.default()
        )

        await self.message.edit(
            embed=embed,
            view=self
        )

        self.stop()


# مافيا
@bot.command(name="مافيا")
async def mafia(ctx):

    view = RandomGameLobby(
        ctx,
        "مافيا",
        "🔪"
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# غميضة
@bot.command(name="غميضة")
async def hide_seek(ctx):

    view = RandomGameLobby(
        ctx,
        "غميضة",
        "🙈"
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# ريبلكا
@bot.command(name="ريبلكا")
async def replica(ctx):

    view = RandomGameLobby(
        ctx,
        "ريبلكا",
        "⚡"
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# خمن
@bot.command(name="خمن")
async def guess(ctx):

    view = RandomGameLobby(
        ctx,
        "خمن",
        "🔢"
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# كلمة
@bot.command(name="كلمة")
async def word(ctx):

    view = RandomGameLobby(
        ctx,
        "كلمة",
        "🔤"
    )

    view.message = await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# =========================================================
# XO
# =========================================================

class XOButton(Button):

    def __init__(self, index, game):

        super().__init__(
            label="⠀",
            style=discord.ButtonStyle.secondary,
            row=index // 3
        )

        self.index = index
        self.game = game

    async def callback(self, interaction):

        game = self.game

        if game.finished:

            await interaction.response.send_message(
                "❌ اللعبة انتهت.",
                ephemeral=True
            )
            return

        current_player = game.players[
            game.turn
        ]

        if interaction.user.id != current_player.id:

            await interaction.response.send_message(
                "⏳ مو دورك.",
                ephemeral=True
            )
            return

        if game.board[self.index] != "":

            await interaction.response.send_message(
                "❌ هذا المكان مأخوذ.",
                ephemeral=True
            )
            return

        symbol = game.symbols[
            interaction.user.id
        ]

        game.board[self.index] = symbol

        self.label = symbol
        self.disabled = True

        winner = game.check_winner()

        if winner is not None:

            game.finished = True

            for child in game.children:
                child.disabled = True

            if winner == "draw":

                result = "🤝 انتهت اللعبة بتعادل."

            else:

                winner_user = next(
                    user
                    for user in game.players
                    if game.symbols[user.id] == winner
                )

                result = (
                    f"🏆 الفائز:\n"
                    f"## {winner_user.mention}"
                )

            await interaction.response.edit_message(
                content=result,
                view=game
            )

            game.stop()
            return

        game.turn = 1 - game.turn

        next_player = game.players[
            game.turn
        ]

        await interaction.response.edit_message(
            content=(
                f"❌ {game.players[0].mention}\n"
                f"⭕ {game.players[1].mention}\n\n"
                f"🎯 الدور الآن: {next_player.mention}"
            ),
            view=game
        )

    # نهاية callback


class XOGame(View):

    def __init__(
        self,
        message,
        players
    ):

        super().__init__(timeout=180)

        self.message = message
        self.players = players

        self.board = [""] * 9
        self.turn = 0
        self.finished = False

        self.symbols = {
            players[0].id: "❌",
            players[1].id: "⭕"
        }

        for index in range(9):

            self.add_item(
                XOButton(
                    index,
                    self
                )
            )

    def check_winner(self):

        combinations = [
            (0, 1, 2),
            (3, 4, 5),
            (6, 7, 8),
            (0, 3, 6),
            (1, 4, 7),
            (2, 5, 8),
            (0, 4, 8),
            (2, 4, 6)
        ]

        for a, b, c in combinations:

            if (
                self.board[a] != ""
                and
                self.board[a] == self.board[b]
                and
                self.board[a] == self.board[c]
            ):

                return self.board[a]

        if all(
            value != ""
            for value in self.board
        ):

            return "draw"

        return None


class XOLobby(LobbyView):

    async def start_game(self):

        game = XOGame(
            self.message,
            self.players
        )

        await self.message.edit(
            content=(
                f"❌ {self.players[0].mention}\n"
                f"⭕ {self.players[1].mention}\n\n"
                f"🎯 الدور الآن: "
                f"{self.players[0].mention}"
            ),
            embed=None,
            view=game
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
            "👥 اللعبة تحتاج لاعبين فقط.\n\n"
            "اضغط **دخول** للمشاركة.\n"
            "إذا غيرت رأيك اضغط **خروج**.\n\n"
            "⏱️ تبدأ اللعبة تلقائيًا بعد **30 ثانية**."
        ),
        color=discord.Color.default()
    )

    view.message = await ctx.send(
        embed=embed,
        view=view
    )


# =========================================================
# الألعاب الفردية
# =========================================================

# زر
@bot.command(name="زر")
async def button_game(ctx):

    class ButtonGame(View):

        def __init__(self):

            super().__init__(timeout=20)

            self.clicked = False

        @discord.ui.button(
            label="اضغط",
            emoji="🔘",
            style=discord.ButtonStyle.secondary
        )
        async def press(
            self,
            interaction: discord.Interaction,
            button: Button
        ):

            if self.clicked:

                await interaction.response.send_message(
                    "❌ أحدهم سبقك.",
                    ephemeral=True
                )
                return

            self.clicked = True
            button.disabled = True

            await interaction.response.edit_message(
                content=(
                    f"⚡ الفائز:\n"
                    f"## {interaction.user.mention}"
                ),
                view=self
            )

            self.stop()

    embed = discord.Embed(
        title="🔘 اضغط الزر",
        description="أول شخص يضغط يفوز!",
        color=discord.Color.default()
    )

    await ctx.send(
        embed=embed,
        view=ButtonGame()
    )


# اسرع
@bot.command(name="اسرع")
async def fastest(ctx):

    answers = [
        "تفاحة",
        "سيارة",
        "قمر",
        "نجم",
        "بحر",
        "كمبيوتر",
        "ديسكورد"
    ]

    answer = random.choice(answers)

    await ctx.send(
        f"⚡ **أسرع!**\n\n"
        f"أول شخص يكتب:\n"
        f"## {answer}"
    )

    def check(message):

        return (
            message.channel.id == ctx.channel.id
            and not message.author.bot
            and message.content.strip() == answer
        )

    try:

        winner = await bot.wait_for(
            "message",
            timeout=15,
            check=check
        )

        await ctx.send(
            f"🏆 أسرع شخص: {winner.author.mention}"
        )

    except asyncio.TimeoutError:

        await ctx.send(
            "⌛ انتهى الوقت."
        )


# فكك
@bot.command(name="فكك")
async def decompose(ctx):

    word = random.choice([
        "ديسكورد",
        "كمبيوتر",
        "امبراطورية",
        "سيرفر",
        "مملكة"
    ])

    separated = " ".join(word)

    await ctx.send(
        f"🧩 فكك الكلمة:\n\n"
        f"## {separated}"
    )


# ادمج
@bot.command(name="ادمج")
async def merge(ctx):

    words = random.sample(
        [
            "قمر",
            "بحر",
            "ليل",
            "ملك",
            "ذهب",
            "نار",
            "ورد"
        ],
        2
    )

    await ctx.send(
        f"🔗 ادمج الكلمتين:\n\n"
        f"**{words[0]} + {words[1]}**"
    )


# اعلام
@bot.command(name="اعلام")
async def flags(ctx):

    flags = [
        "🇸🇦 السعودية",
        "🇰🇼 الكويت",
        "🇦🇪 الإمارات",
        "🇶🇦 قطر",
        "🇧🇭 البحرين",
        "🇴🇲 عمان"
    ]

    selected = random.choice(flags)

    await ctx.send(
        f"🏳️ علمك هو:\n\n"
        f"## {selected}"
    )


# اعكس
@bot.command(name="اعكس")
async def reverse_word(ctx):

    word = random.choice([
        "ديسكورد",
        "امبراطورية",
        "سيرفر",
        "كمبيوتر",
        "مملكة"
    ])

    await ctx.send(
        f"🔄 اعكس الكلمة:\n\n"
        f"## {word}"
    )


# حرف
@bot.command(name="حرف")
async def random_letter(ctx):

    letters = list(
        "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"
    )

    letter = random.choice(letters)

    await ctx.send(
        f"🔤 الحرف المختار:\n\n"
        f"## {letter}"
    )


# صحح
@bot.command(name="صحح")
async def correct(ctx):

    sentences = [
        "انا ذهبت المدرسه",
        "هو يلعب لعبه",
        "نحن ذهبنا الى البيت",
        "انا احب الالعاب"
    ]

    sentence = random.choice(sentences)

    await ctx.send(
        f"✏️ صحح الجملة:\n\n"
        f"**{sentence}**"
    )


# ترتيب
@bot.command(name="ترتيب")
async def order_game(ctx):

    numbers = random.sample(
        range(1, 11),
        5
    )

    numbers_text = " - ".join(
        str(number)
        for number in numbers
    )

    await ctx.send(
        f"🔢 رتب الأرقام من الأصغر إلى الأكبر:\n\n"
        f"## {numbers_text}"
    )


# الوان
@bot.command(name="الوان")
async def colors_game(ctx):

    colors = [
        "🔴 أحمر",
        "🔵 أزرق",
        "🟢 أخضر",
        "🟡 أصفر",
        "🟣 بنفسجي",
        "🟠 برتقالي",
        "⚫ أسود",
        "⚪ أبيض"
    ]

    selected = random.choice(colors)

    await ctx.send(
        f"🎨 اللون المختار:\n\n"
        f"## {selected}"
    )


# ايموجي
@bot.command(name="ايموجي")
async def emoji_game(ctx):

    emojis = [
        "😀",
        "😂",
        "🔥",
        "👑",
        "🎮",
        "⚡",
        "🐺",
        "🦅",
        "💎",
        "🚀"
    ]

    selected = random.choice(emojis)

    await ctx.send(
        f"😀 الإيموجي المختار:\n\n"
        f"## {selected}"
    )


# اكشف
@bot.command(name="اكشف")
async def reveal(ctx):

    things = [
        "🎁 جائزة سرية",
        "💎 ألماسة",
        "👑 تاج",
        "💰 كنز",
        "⚔️ سلاح أسطوري",
        "🏆 كأس"
    ]

    selected = random.choice(things)

    await ctx.send(
        f"🔎 فتحت الصندوق...\n\n"
        f"## {selected}"
    )


# =========================================================
# قائمة الألعاب
# =========================================================

@bot.command(name="العاب")
async def games_list(ctx):

    embed = discord.Embed(
        title="🎮 مركز الألعاب",
        description=(
            "اختر اللعبة واستخدم أمرها.\n"
            "الألعاب الجماعية تبدأ بلوبي مدته **30 ثانية**."
        ),
        color=discord.Color.default()
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

    await ctx.send(
        embed=embed
    )


# =========================================================
# منع تكرار الأوامر الإدارية مع أوامر الألعاب
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    handled = await admin_command(message)

    if not handled:
        await bot.process_commands(message)


# =========================================================
# عند تشغيل البوت
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"✅ تم تشغيل البوت: {bot.user}")
    print(f"🆔 ID: {bot.user.id}")
    print("=" * 50)


# =========================================================
# تشغيل البوت
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ لم يتم العثور على DISCORD_TOKEN في Environment Variables."
    )

bot.run(TOKEN)
