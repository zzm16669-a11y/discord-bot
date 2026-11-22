import io
from pathlib import Path

import discord
from discord.ext import commands
from PIL import Image, ImageDraw

# ================== الإعدادات ==================
WELCOME_CHANNEL_ID = 1573898040362668084  # حط هنا ايدي روم الترحيب

# الصورة لازم تكون بنفس مجلد هذا الملف باسم welcome_bg.png
BG_PATH = Path(__file__).parent / "welcome_bg.png"

# مكان وحجم الأفتار داخل الدائرة (نسب من حجم الصورة، فتشتغل مع أي دقة)
CENTER_X = 0.1995  # مكان مركز الدائرة أفقياً (0 = أقصى اليسار، 1 = أقصى اليمين)
CENTER_Y = 0.4873  # مكان مركز الدائرة عمودياً (0 = فوق، 1 = تحت)
AVATAR_SIZE = 0.1886  # قطر الأفتار بالنسبة لعرض الصورة
# ===============================================


def build_welcome_image(avatar_bytes: bytes) -> io.BytesIO:
    bg = Image.open(BG_PATH).convert("RGBA")
    bg_w, bg_h = bg.size

    diameter = int(bg_w * AVATAR_SIZE)
    cx = int(bg_w * CENTER_X)
    cy = int(bg_h * CENTER_Y)

    # تجهيز الأفتار وقصه دائري
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    avatar = avatar.resize((diameter, diameter), Image.LANCZOS)

    # قناع دائري ناعم (رسم بحجم 4x ثم تصغير عشان الحواف تطلع ناعمة)
    scale = 4
    mask = Image.new("L", (diameter * scale, diameter * scale), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * scale, diameter * scale), fill=255)
    mask = mask.resize((diameter, diameter), Image.LANCZOS)

    avatar.putalpha(mask)

    # لصق الأفتار داخل الدائرة
    bg.paste(avatar, (cx - diameter // 2, cy - diameter // 2), avatar)

    output = io.BytesIO()
    bg.save(output, format="PNG")
    output.seek(0)
    return output


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if channel is None:
            return

        try:
            avatar_bytes = await member.display_avatar.replace(
                size=512, format="png"
            ).read()
            image = await self.bot.loop.run_in_executor(
                None, build_welcome_image, avatar_bytes
            )
            file = discord.File(image, filename="welcome.png")
            await channel.send(content=f"hey {member.mention}", file=file)
        except Exception as e:
            print(f"[Welcome] خطأ: {e}")
            # لو صار خطأ بالصورة يرسل الرسالة بس
            await channel.send(f"hey {member.mention}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
