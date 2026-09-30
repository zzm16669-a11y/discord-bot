"""
voice_stay.py — يخلي البوت يتكي بأي روم صوتي تقوله عليه (ويرجع لو انطرد أو انقطع).

الأوامر:
  .ادخل   — ادخل روم صوتي، وبعدين اكتب الأمر: البوت يدخل نفس رومك ويتكي فيه.
  .اخرج   — يطلع البوت من الروم ويوقف التكي.
  (للإدارة بس: صلاحية Move Members أو Administrator)

اختياري: لو تبي البوت يدخل روم معيّن تلقائيًا كل ما يشتغل (حتى بعد إعادة النشر)،
حط الـ ID بـ STAY_VOICE_CHANNEL تحت. بدونه، البوت ينسى الروم لو انعاد تشغيله
ويستنى أمر .ادخل من جديد.

الربط ببوتك (جنب باقي الأنظمة):

    import voice_stay
    voice_stay.setup_voice_stay(bot)

وبـ requirements.txt لازم تضيف:
    PyNaCl
    davey
(والأفضل تخلي discord.py محدّث لآخر نسخة)

صلاحيات البوت بالروم الصوتي: View Channel + Connect.
"""
import asyncio

import discord
from discord.ext import commands, tasks

# ================= إعدادات =================
# (اختياري) روم صوتي يدخله البوت تلقائيًا عند التشغيل: ID رقم أو اسم بين علامتي تنصيص. 0 = بدون.
STAY_VOICE_CHANNEL = 0

CHECK_INTERVAL_SECONDS = 30      # كل كم ثانية يتأكد إنه داخل الروم
SELF_DEAF = True                 # البوت يدخل وهو مسوّي ديفن

_lock = asyncio.Lock()
_targets: dict[int, int | None] = {}   # guild_id -> channel_id (None = طلّعناه بأمر .اخرج)


def _is_voice(ch) -> bool:
    return isinstance(ch, (discord.VoiceChannel, discord.StageChannel))


def _default_channel(bot: commands.Bot):
    target = STAY_VOICE_CHANNEL
    if not target:
        return None
    if isinstance(target, int) or str(target).isdigit():
        ch = bot.get_channel(int(target))
        return ch if _is_voice(ch) else None
    for guild in bot.guilds:
        for ch in guild.voice_channels:
            if ch.name == target:
                return ch
    for guild in bot.guilds:
        for ch in guild.voice_channels:
            if str(target).lower() in ch.name.lower():
                return ch
    return None


def _target_for(bot: commands.Bot, guild: discord.Guild):
    if guild.id in _targets:
        cid = _targets[guild.id]
        if cid is None:
            return None
        ch = guild.get_channel(cid)
        return ch if _is_voice(ch) else None
    default = _default_channel(bot)
    if default is not None and default.guild.id == guild.id:
        return default
    return None


async def _ensure_connected(bot: commands.Bot, guild: discord.Guild) -> None:
    channel = _target_for(bot, guild)
    if channel is None:
        return
    async with _lock:
        vc = guild.voice_client
        try:
            if vc is None:
                await channel.connect(self_deaf=SELF_DEAF, reconnect=True)
            elif not vc.is_connected():
                await vc.disconnect(force=True)
                await channel.connect(self_deaf=SELF_DEAF, reconnect=True)
            elif vc.channel is None or vc.channel.id != channel.id:
                await vc.move_to(channel)
        except RuntimeError as e:
            # غالبًا PyNaCl / davey مو منزّلة
            print(f"[VoiceStay] ❌ {e} — تأكد إن PyNaCl و davey بـ requirements.txt")
        except (discord.ClientException, discord.Forbidden, discord.HTTPException, asyncio.TimeoutError) as e:
            print(f"[VoiceStay] ما قدرت أدخل الروم الصوتي: {e!r}")


def _can_manage(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.move_members


def setup_voice_stay(bot: commands.Bot) -> None:
    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def watchdog():
        for guild in bot.guilds:
            await _ensure_connected(bot, guild)

    async def _on_ready_voice():
        if not watchdog.is_running():
            watchdog.start()

    async def _on_voice_state_voice(member: discord.Member, before: discord.VoiceState,
                                     after: discord.VoiceState):
        # لو البوت نفسه انسحب/انطرد من الروم، نرجعه بعد ثواني قليلة
        if bot.user is None or member.id != bot.user.id:
            return
        if before.channel is not None and after.channel is None:
            await asyncio.sleep(3)
            await _ensure_connected(bot, member.guild)

    bot.add_listener(_on_ready_voice, "on_ready")
    bot.add_listener(_on_voice_state_voice, "on_voice_state_update")

    @bot.command(name="ادخل")
    async def join_voice_cmd(ctx: commands.Context):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        if not _can_manage(ctx.author):
            await ctx.send(f"{ctx.author.mention} ❌ ما عندك الصلاحية.")
            return
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("⚠️ ادخل روم صوتي أول وبعدين اكتب الأمر.")
            return
        channel = ctx.author.voice.channel
        _targets[ctx.guild.id] = channel.id
        await _ensure_connected(bot, ctx.guild)
        vc = ctx.guild.voice_client
        if vc is not None and vc.is_connected() and vc.channel and vc.channel.id == channel.id:
            await ctx.send(f"✅ دخلت **{channel.name}** وبتكي فيه.")
        else:
            await ctx.send("❌ ما قدرت أدخل الروم (تأكد من صلاحيات البوت، وراجع لوق Render).")

    @bot.command(name="اخرج")
    async def leave_voice_cmd(ctx: commands.Context):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        if not _can_manage(ctx.author):
            await ctx.send(f"{ctx.author.mention} ❌ ما عندك الصلاحية.")
            return
        _targets[ctx.guild.id] = None
        vc = ctx.guild.voice_client
        if vc is not None:
            await vc.disconnect(force=True)
            await ctx.send("👋 طلعت من الروم الصوتي.")
        else:
            await ctx.send("⚠️ أنا مو داخل أي روم صوتي.")
