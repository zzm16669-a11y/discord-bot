# colors.py - لوحة اختيار لون الرتبة (22 لون) بقائمة منسدلة
#
# حط الملف + colors_panel.png بنفس مجلد bot.py، وفي bot.py أضف:
#     import colors
#     colors.setup_colors(bot)
# الأمر (للأدمن فقط):  .ألوان   يرسل اللوحة في الروم اللي تكتب فيه الأمر

import os
import discord
from discord.ext import commands

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_PATH = os.path.join(BASE_DIR, "colors_panel.png")

# (الرقم، الاسم، ايدي الرتبة)
COLOR_ROLES = [
    (1,  "Black",         1540230365438804049),
    (2,  "White",         1540231400870125579),
    (3,  "Red",           1540231846804066304),
    (4,  "Blue",          1540231711386771517),
    (5,  "Green",         1540231929209561159),
    (6,  "Yellow",        1540232028425945118),
    (7,  "Pink",          1540249452181323797),
    (8,  "Purple",        1540231781217738874),
    (9,  "Cherry",        1545536778809643118),
    (10, "Maroon",        1545536929452392448),
    (11, "Dark Orange",   1545537060134322226),
    (12, "Grass Green",   1545537348983459850),
    (13, "Lemon",         1545537213079752805),
    (14, "Light Teal",    1545537480470560991),
    (15, "Sky Blue",      1545537603535896766),
    (16, "Navy",          1545537699442593882),
    (17, "Lavender",      1545537840610549810),
    (18, "Lilac",         1545538098031493171),
    (19, "Hot Pink",      1545538247931859074),
    (20, "Fuchsia",       1545538367381311498),
    (21, "Beige",         1545538500252668025),
    (22, "Chocolate",     1545538626912260106),
]

ROLE_BY_VALUE = {str(n): rid for n, _, rid in COLOR_ROLES}
ALL_COLOR_IDS = set(ROLE_BY_VALUE.values())


class ColorSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=f"{n} - {name}", value=str(n))
            for n, name, _ in COLOR_ROLES
        ]
        super().__init__(
            custom_id="color_roles_select",  # ثابت عشان تشتغل بعد إعادة تشغيل البوت
            placeholder="اختر",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return await interaction.followup.send("هذا الأمر يشتغل داخل السيرفر فقط.", ephemeral=True)

        new_role = guild.get_role(ROLE_BY_VALUE[self.values[0]])
        if new_role is None:
            return await interaction.followup.send("رتبة هذا اللون غير موجودة بالسيرفر، بلغ الإدارة.", ephemeral=True)

        # الرتب القديمة (أي لون من الـ 22 غير المختار)
        old_roles = [r for r in member.roles if r.id in ALL_COLOR_IDS and r.id != new_role.id]

        if new_role in member.roles and not old_roles:
            return await interaction.followup.send(f"عندك لون **{new_role.name}** من قبل.", ephemeral=True)

        try:
            if old_roles:
                await member.remove_roles(*old_roles, reason="تغيير لون الرتبة")
            if new_role not in member.roles:
                await member.add_roles(new_role, reason="اختيار لون الرتبة")
        except discord.Forbidden:
            return await interaction.followup.send(
                "ما أقدر أعطيك الرتبة. تأكد إن رتبة البوت أعلى من رتب الألوان وعنده صلاحية Manage Roles.",
                ephemeral=True,
            )
        except discord.HTTPException:
            return await interaction.followup.send("صار خطأ، جرب مرة ثانية.", ephemeral=True)

        await interaction.followup.send(f"تم تغيير لونك إلى **{new_role.name}**.", ephemeral=True)


class ColorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ColorSelect())


def setup_colors(bot: commands.Bot):
    bot.add_view(ColorView())  # يخلي القائمة تشتغل حتى بعد ريستارت البوت

    @bot.command(name="ألوان")
    async def send_color_panel(ctx: commands.Context):
        if ctx.guild is None:
            return
        author = ctx.author
        if not (author.id == ctx.guild.owner_id or author.guild_permissions.administrator):
            await ctx.send(f"{author.mention} ❌ ما عندك الصلاحية.")
            return

        # الصورة لحالها (بدون إطار/قالب وبدون كلام) + القائمة المنسدلة تحتها
        if os.path.exists(IMAGE_PATH):
            await ctx.send(file=discord.File(IMAGE_PATH, filename="colors_panel.png"), view=ColorView())
        else:
            # لو الصورة مو موجودة نرسل القائمة بس (ديسكورد ما يقبل رسالة فاضية تمامًا)
            await ctx.send("\u200b", view=ColorView())
