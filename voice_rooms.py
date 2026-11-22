"""
voice_rooms.py — نظام الغرف الصوتية الخاصة (Join to Create) + لوحة تحكم ثابتة بروم نصي
=====================================================================
الفكرة:
  - العضو يدخل روم "أنشئ غرفتك" ← البوت يسوي له روم صوتي خاص وينقله له.
  - لوحة التحكم رسالة وحدة ثابتة بروم "لوحة-التحكم". تكتب  .لوحة  فتنرسل اللوحة وتنحذف رسالة الأمر.
  - أي زر يتحكم بالغرفة اللي العضو داخلها الحين، وبس مالك الغرفة يقدر يستخدمه.
  - الغرفة تنحذف تلقائيًا لما تفضى من الأعضاء.
  - الأزرار تشتغل حتى بعد ريستارت البوت.

التركيب بـ bot.py (سطرين بس):
    import voice_rooms
    voice_rooms.setup_voice_rooms(bot)

صلاحيات البوت المطلوبة: Manage Channels / Move Members / Send Messages / Embed Links /
                         Attach Files / Manage Messages (عشان يحذف رسالة .لوحة)
المكتبة: discord.py 2.1 أو أحدث (عشان قوائم اختيار الأعضاء).
"""

import asyncio
import json
import os
import sys
import time

import discord
from discord import ui
from discord.ext import commands

# ============================================================
# الإعدادات — عدّل هنا بس
# ============================================================
CREATE_ROOM_CHANNEL_ID = 1573893960781533295   # روم "أنشئ غرفتك" الصوتي
ROOMS_CATEGORY_ID = 1573893886206550147        # الكاتقوري اللي تنعمل فيه الغرف (0 = نفس كاتقوري روم الإنشاء)
CONTROL_CHANNEL_ID = 1573895530252083260       # روم "لوحة-التحكم" النصي (اللوحة تنرسل له)

PANEL_IMAGE_PATH = "voice_panel.png"   # صورة اللوحة (جنب bot.py). لو ما لقاها يرسل اللوحة بدون صورة
PANEL_FOOTER = "OwzKLR"
ROOM_NAME_TEMPLATE = "غرفة {name}"
CREATE_COOLDOWN = 10           # ثواني بين إنشاء غرفة وغرفة لنفس العضو
GOLD = 0xD4AF37
DATA_FILE = "voice_rooms.json"

# إيموجيات الأزرار (الذهبية اللي رفعتها)
EMOJI_IDS = {
    "lock": 1573886128107299116,
    "unlock": 1573885913392611338,
    "eye": 1573886001242316831,
    "eye_hidden": 1573886020552757360,
    "rename": 1573886191151882374,
    "limit": 1573886076223750214,
    "kick": 1573886055076208860,
    "allow": 1573885880412803162,
    "owner": 1573886171472334958,
    "delete": 1573885980853665914,
}
EMOJI = {name: discord.PartialEmoji(name=name, id=eid) for name, eid in EMOJI_IDS.items()}

PANEL_IMAGE_NAME = os.path.basename(PANEL_IMAGE_PATH)
_PANEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), PANEL_IMAGE_PATH)


# ============================================================
# التخزين (يحفظ مين مالك كل غرفة عشان يرجع بعد الريستارت)
# ============================================================
def _load() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save() -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(_rooms, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[voice_rooms] ما قدرت أحفظ الملف: {e}")


_rooms: dict = _load()          # {آيدي الروم: {"owner": آيدي المالك}}
_cooldown: dict = {}            # {آيدي العضو: وقت آخر إنشاء}
_creating: set = set()          # أعضاء جاري إنشاء غرفة لهم الحين
_ready_done = False
_bot = None


def get_room(channel_id) -> dict | None:
    return _rooms.get(str(channel_id))


def _has_humans(channel: discord.VoiceChannel) -> bool:
    return any(not m.bot for m in channel.members)


async def remove_room(channel: discord.VoiceChannel, reason: str) -> None:
    _rooms.pop(str(channel.id), None)
    _save()
    try:
        await channel.delete(reason=reason)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


# ============================================================
# فحص المالك — الأزرار تتحكم بالغرفة اللي العضو داخلها
# ============================================================
async def get_owned_room(interaction: discord.Interaction) -> discord.VoiceChannel | None:
    """يرجع غرفة العضو لو هو مالكها، وإلا يرد عليه رد مخفي ويرجع None."""
    voice = getattr(interaction.user, "voice", None)
    channel = voice.channel if voice is not None else None
    if channel is None:
        await interaction.response.send_message(
            "ادخل غرفتك الصوتية أول عشان تتحكم فيها.", ephemeral=True)
        return None
    info = get_room(channel.id)
    if info is None:
        await interaction.response.send_message(
            "انت مو داخل غرفة خاصة. ادخل روم «أنشئ غرفتك» وتنعمل لك غرفة.", ephemeral=True)
        return None
    if info["owner"] != interaction.user.id:
        await interaction.response.send_message(
            "هذي مو غرفتك، بس مالك الغرفة يقدر يستخدم الأزرار.", ephemeral=True)
        return None
    return channel


async def _set_everyone(interaction: discord.Interaction, channel: discord.VoiceChannel,
                        ok_text: str, **perms) -> None:
    """يعدل صلاحية @everyone على الغرفة (قفل / فتح / إخفاء / إظهار) ويرد على المالك."""
    await interaction.response.defer(ephemeral=True)
    ow = channel.overwrites_for(channel.guild.default_role)
    for key, value in perms.items():
        setattr(ow, key, value)
    try:
        await channel.set_permissions(channel.guild.default_role, overwrite=ow,
                                      reason="تحكم من مالك الغرفة")
    except discord.HTTPException:
        await interaction.followup.send("ما قدرت أنفذ الأمر.", ephemeral=True)
        return
    await interaction.followup.send(ok_text, ephemeral=True)


# ============================================================
# النوافذ (تغيير الاسم / عدد الأعضاء)
# ============================================================
class RenameModal(ui.Modal, title="تغيير اسم الغرفة"):
    new_name = ui.TextInput(label="الاسم الجديد", placeholder="اكتب اسم الغرفة...",
                            max_length=100, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        channel = await get_owned_room(interaction)
        if channel is None:
            return
        await interaction.response.defer(ephemeral=True)
        name = str(self.new_name.value).strip()
        if not name:
            await interaction.followup.send("الاسم فاضي.", ephemeral=True)
            return
        try:
            await asyncio.wait_for(channel.edit(name=name, reason="تغيير اسم الغرفة من المالك"), timeout=10)
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "ديسكورد يحدد تغيير اسم الروم (مرتين كل 10 دقائق تقريبًا)، جرّب بعد شوي.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send("ما قدرت أغير الاسم.", ephemeral=True)
            return
        await interaction.followup.send("تم تغيير اسم الغرفة.", ephemeral=True)


class LimitModal(ui.Modal, title="عدد الأعضاء"):
    limit_input = ui.TextInput(label="العدد من 0 إلى 99 (0 = بدون حد)", placeholder="مثال: 5",
                               max_length=2, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        channel = await get_owned_room(interaction)
        if channel is None:
            return
        raw = str(self.limit_input.value).strip()
        if not raw.isdigit() or not 0 <= int(raw) <= 99:
            await interaction.response.send_message("اكتب رقم من 0 إلى 99.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        limit = int(raw)
        try:
            await channel.edit(user_limit=limit, reason="تغيير عدد الأعضاء من المالك")
        except discord.HTTPException:
            await interaction.followup.send("ما قدرت أغير العدد.", ephemeral=True)
            return
        await interaction.followup.send("تم تحديد العدد: " + (str(limit) if limit else "بدون حد"), ephemeral=True)


# ============================================================
# قوائم اختيار الأعضاء (طرد / سماح / نقل ملكية) — رسالة مخفية للمالك
# ============================================================
class PickSelect(ui.UserSelect):
    def __init__(self, action: str, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        channel = await get_owned_room(interaction)
        if channel is None:
            return
        await interaction.response.defer()
        picked = self.values[0]
        target = interaction.guild.get_member(picked.id)
        result = ""

        if self.action == "allow":
            if picked.bot:
                result = "ما أقدر أسمح لبوت."
            else:
                try:
                    await channel.set_permissions(picked, view_channel=True, connect=True,
                                                  reason="سماح من مالك الغرفة")
                    result = f"تم السماح لـ {picked.mention} بدخول الغرفة."
                except discord.HTTPException:
                    result = "ما قدرت أسمح له."

        elif target is None or target not in channel.members:
            result = "هذا الشخص مو موجود بالغرفة."

        elif target.id == interaction.user.id:
            result = "هذا انت مالك الغرفة."

        elif self.action == "kick":
            try:
                await target.move_to(None, reason="طرد من مالك الغرفة")
                await channel.set_permissions(target, overwrite=None, reason="طرد من مالك الغرفة")
                result = f"تم طرد {target.mention} من الغرفة."
            except discord.HTTPException:
                result = "ما قدرت أطرده."

        elif self.action == "owner":
            if target.bot:
                result = "ما أقدر أنقل الملكية لبوت."
            else:
                try:
                    await channel.set_permissions(target, view_channel=True, connect=True, speak=True,
                                                  stream=True, reason="نقل ملكية الغرفة")
                    _rooms[str(channel.id)]["owner"] = target.id
                    _save()
                    result = f"تم نقل ملكية الغرفة إلى {target.mention}."
                except discord.HTTPException:
                    result = "ما قدرت أنقل الملكية."

        await interaction.edit_original_response(content=result, view=None)


class PickView(ui.View):
    def __init__(self, action: str, placeholder: str):
        super().__init__(timeout=60)
        self.add_item(PickSelect(action, placeholder))


# ============================================================
# لوحة التحكم (دائمة — تشتغل بعد الريستارت)
# ============================================================
class RoomPanel(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ---------- الصف الأول ----------
    @ui.button(label="قفل الغرفة", emoji=EMOJI["lock"], style=discord.ButtonStyle.secondary,
               custom_id="vr:lock", row=0)
    async def lock_btn(self, interaction: discord.Interaction, button: ui.Button):
        channel = await get_owned_room(interaction)
        if channel is not None:
            await _set_everyone(interaction, channel, "تم قفل الغرفة.", connect=False)

    @ui.button(label="فتح الغرفة", emoji=EMOJI["unlock"], style=discord.ButtonStyle.secondary,
               custom_id="vr:unlock", row=0)
    async def unlock_btn(self, interaction: discord.Interaction, button: ui.Button):
        channel = await get_owned_room(interaction)
        if channel is not None:
            await _set_everyone(interaction, channel, "تم فتح الغرفة.", connect=None)

    @ui.button(label="إظهار الغرفة", emoji=EMOJI["eye"], style=discord.ButtonStyle.secondary,
               custom_id="vr:show", row=0)
    async def show_btn(self, interaction: discord.Interaction, button: ui.Button):
        channel = await get_owned_room(interaction)
        if channel is not None:
            await _set_everyone(interaction, channel, "تم إظهار الغرفة.", view_channel=None)

    @ui.button(label="إخفاء الغرفة", emoji=EMOJI["eye_hidden"], style=discord.ButtonStyle.secondary,
               custom_id="vr:hide", row=0)
    async def hide_btn(self, interaction: discord.Interaction, button: ui.Button):
        channel = await get_owned_room(interaction)
        if channel is not None:
            await _set_everyone(interaction, channel, "تم إخفاء الغرفة.", view_channel=False)

    @ui.button(label="تغيير الاسم", emoji=EMOJI["rename"], style=discord.ButtonStyle.secondary,
               custom_id="vr:rename", row=0)
    async def rename_btn(self, interaction: discord.Interaction, button: ui.Button):
        if await get_owned_room(interaction) is None:
            return
        await interaction.response.send_modal(RenameModal())

    # ---------- الصف الثاني ----------
    @ui.button(label="عدد الأعضاء", emoji=EMOJI["limit"], style=discord.ButtonStyle.secondary,
               custom_id="vr:limit", row=1)
    async def limit_btn(self, interaction: discord.Interaction, button: ui.Button):
        if await get_owned_room(interaction) is None:
            return
        await interaction.response.send_modal(LimitModal())

    @ui.button(label="طرد شخص", emoji=EMOJI["kick"], style=discord.ButtonStyle.secondary,
               custom_id="vr:kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, button: ui.Button):
        if await get_owned_room(interaction) is None:
            return
        await interaction.response.send_message("اختر الشخص اللي تبي تطرده من الغرفة:",
                                                view=PickView("kick", "اختر شخص من الغرفة..."), ephemeral=True)

    @ui.button(label="سماح لشخص", emoji=EMOJI["allow"], style=discord.ButtonStyle.secondary,
               custom_id="vr:allow", row=1)
    async def allow_btn(self, interaction: discord.Interaction, button: ui.Button):
        if await get_owned_room(interaction) is None:
            return
        await interaction.response.send_message("اختر الشخص اللي تبي تسمح له بدخول الغرفة (حتى لو مقفلة):",
                                                view=PickView("allow", "اختر شخص..."), ephemeral=True)

    @ui.button(label="نقل الملكية", emoji=EMOJI["owner"], style=discord.ButtonStyle.secondary,
               custom_id="vr:owner", row=1)
    async def owner_btn(self, interaction: discord.Interaction, button: ui.Button):
        if await get_owned_room(interaction) is None:
            return
        await interaction.response.send_message("اختر الشخص اللي تبي تنقل له ملكية الغرفة (لازم يكون بالغرفة):",
                                                view=PickView("owner", "اختر شخص من الغرفة..."), ephemeral=True)

    @ui.button(label="حذف الغرفة", emoji=EMOJI["delete"], style=discord.ButtonStyle.danger,
               custom_id="vr:delete", row=1)
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        channel = await get_owned_room(interaction)
        if channel is None:
            return
        await interaction.response.send_message("تم حذف الغرفة.", ephemeral=True)
        await remove_room(channel, "حذف الغرفة من المالك")


def build_panel_embed(has_image: bool) -> discord.Embed:
    embed = discord.Embed(
        title="لوحة التحكم بالغرفة",
        description="ادخل غرفتك الصوتية ثم اضغط الأزرار تحت عشان تتحكم فيها.\n"
                    "بس مالك الغرفة يقدر يستخدم الأزرار.",
        color=GOLD,
    )
    embed.set_footer(text=PANEL_FOOTER)
    if has_image:
        embed.set_image(url=f"attachment://{PANEL_IMAGE_NAME}")
    return embed


# ============================================================
# أمر .لوحة — يرسل لوحة التحكم ويحذف رسالة الأمر
# ============================================================
@commands.command(name="لوحة")
async def panel_cmd(ctx: commands.Context):
    member = ctx.author
    allowed = ctx.guild is not None and isinstance(member, discord.Member) and (
        member.id == ctx.guild.owner_id or member.guild_permissions.administrator)
    if not allowed:
        try:
            await ctx.message.add_reaction("❌")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        return

    target = ctx.guild.get_channel(CONTROL_CHANNEL_ID) or ctx.channel
    kwargs = {}
    has_image = os.path.isfile(_PANEL_FILE)
    if has_image:
        kwargs["file"] = discord.File(_PANEL_FILE, filename=PANEL_IMAGE_NAME)
    try:
        await target.send(embed=build_panel_embed(has_image), view=RoomPanel(), **kwargs)
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"[voice_rooms] ما قدرت أرسل اللوحة: {e}")
        await ctx.send("ما قدرت أرسل اللوحة، تأكد من صلاحيات البوت بروم التحكم.")
        return

    # نحذف رسالة الأمر بدون ما تنسجل بلوق الحذف (نفس طريقة .قول)
    silent_ids = getattr(sys.modules.get("__main__"), "silent_deleted_ids", None)
    if isinstance(silent_ids, set):
        silent_ids.add(ctx.message.id)
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        if isinstance(silent_ids, set):
            silent_ids.discard(ctx.message.id)


# ============================================================
# إنشاء الغرفة تلقائيًا + حذفها لما تفضى
# ============================================================
async def create_room(member: discord.Member, create_channel: discord.VoiceChannel) -> int | None:
    """ينشئ غرفة للعضو وينقله لها. لو عنده غرفة من قبل ينقله لها. يرجع آيدي الغرفة."""
    guild = member.guild

    # عنده غرفة؟ رجّعه لها بدل ما نسوي ثانية
    for cid, info in list(_rooms.items()):
        if info.get("owner") == member.id:
            existing = guild.get_channel(int(cid))
            if existing is not None:
                try:
                    await member.move_to(existing)
                except discord.HTTPException:
                    pass
                return existing.id
            _rooms.pop(cid, None)
            _save()

    # منع السبام
    now = time.monotonic()
    if now - _cooldown.get(member.id, 0) < CREATE_COOLDOWN or member.id in _creating:
        try:
            await member.move_to(None, reason="إنشاء غرف بسرعة")
        except discord.HTTPException:
            pass
        return None
    _cooldown[member.id] = now
    _creating.add(member.id)

    try:
        category = guild.get_channel(ROOMS_CATEGORY_ID) if ROOMS_CATEGORY_ID else create_channel.category
        overwrites = dict(category.overwrites) if category is not None else {}
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True,
                                                         speak=True, stream=True)
        name = ROOM_NAME_TEMPLATE.format(name=member.display_name)[:100]
        try:
            room = await guild.create_voice_channel(name=name, category=category, overwrites=overwrites,
                                                    reason=f"غرفة خاصة لـ {member}")
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[voice_rooms] فشل إنشاء الغرفة: {e}")
            return None

        _rooms[str(room.id)] = {"owner": member.id}
        _save()

        try:
            await member.move_to(room)
        except discord.HTTPException:
            await remove_room(room, "العضو طلع قبل النقل")
            return None
        return room.id
    finally:
        _creating.discard(member.id)


async def _on_voice_state_update(member: discord.Member, before: discord.VoiceState,
                                 after: discord.VoiceState):
    if member.bot or before.channel == after.channel:
        return

    keep_id = None
    if CREATE_ROOM_CHANNEL_ID and after.channel is not None and after.channel.id == CREATE_ROOM_CHANNEL_ID:
        keep_id = await create_room(member, after.channel)

    left = before.channel
    if left is not None and left.id != keep_id and get_room(left.id) is not None:
        if not _has_humans(left):
            await remove_room(left, "الغرفة فاضية")


async def _on_ready():
    global _ready_done
    if _ready_done:
        return
    _ready_done = True
    _bot.add_view(RoomPanel())   # يخلي أزرار اللوحة تشتغل بعد الريستارت

    # تنظيف الغرف اللي انحذفت أو فضت وقت ما كان البوت مطفي
    for cid in list(_rooms.keys()):
        channel = _bot.get_channel(int(cid))
        if channel is None:
            _rooms.pop(cid, None)
        elif not _has_humans(channel):
            await remove_room(channel, "الغرفة فاضية")
    _save()

    if not CREATE_ROOM_CHANNEL_ID:
        print("[voice_rooms] ⚠️ لازم تحط CREATE_ROOM_CHANNEL_ID داخل voice_rooms.py عشان النظام يشتغل.")


def setup_voice_rooms(bot) -> None:
    """يسجل النظام بالبوت. يتنادى مرة وحدة من bot.py."""
    global _bot
    _bot = bot
    bot.add_listener(_on_voice_state_update, "on_voice_state_update")
    bot.add_listener(_on_ready, "on_ready")
    # يتسجل بس لو ما فيه أمر "لوحة" ثاني (يمنع خطأ "الأمر مسجل مرتين")
    if bot.get_command("لوحة") is None:
        bot.add_command(panel_cmd)
    else:
        print("[voice_rooms] ⚠️ فيه أمر اسمه «لوحة» مسجل من قبل، ما سجلت أمر اللوحة.")
