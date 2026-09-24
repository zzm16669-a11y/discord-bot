"""
tickets.py — نظام تكتات كامل.

المطلوب يكون جاهز يدويًا بالسيرفر قبل التشغيل:
  - رتبة اسمها بالضبط: TICKETS  (فريق الدعم اللي يشوف ويرد على التكتات)
  - كاتيقوري اسمها بالضبط: Tickets  (اللي بتتفتح فيها رومات التكتات)
  - روم اسمه فيه "ticket-logs" (نفس روم اللوق اللي تستخدمه حاليًا) — يرسل له
    الترانسكريبت وقت الإغلاق.

طريقة الربط ببوتك (بدون أي تعديل على باقي bot.py):
  بعد تعريف `bot = commands.Bot(...)` بأي مكان قبل `bot.run(...)`، ضيف سطرين بس:

      import tickets
      tickets.setup_tickets(bot)

  وخلاص. الأمر `.تكت` يرسل بانل فتح التكتات (قائمة اختيار)، والباقي (الاستلام/
  الإغلاق/الخيارات) يشتغل تلقائي عبر أزرار دائمة (persistent views) تفضل تشتغل
  حتى بعد إعادة تشغيل البوت.
"""
import asyncio
import io
from datetime import datetime, timezone

import discord
from discord.ext import commands

import db as _db

# ================= إعدادات (غيّرها هنا لو تبي) =================
SUPPORT_ROLE_NAME = "TICKETS"
TICKETS_CATEGORY_NAME = "Tickets"
TICKET_LOG_CHANNEL_HINT = "ticket-logs"     # نفس اسم الروم الموجود عندك
TICKET_CHANNEL_PREFIX = "ticket"            # الرومات تطلع ticket-0001, ticket-0002...

TICKET_PANEL_IMAGE = "ticket_assets/panel.png"

TICKET_TYPES = [
    ("inquiry", "❓", "استفسار"),
    ("complaint", "⚠️", "شكوى"),
    ("support", "🛠️", "التواصل مع الدعم الفني"),
]
TICKET_TYPE_LABELS = {key: label for key, _, label in TICKET_TYPES}


# ============================================================
# دوال مساعدة
# ============================================================
def _find_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    for ch in guild.text_channels:
        normalized = ch.name.lower().replace("_", "-")
        if TICKET_LOG_CHANNEL_HINT in normalized:
            return ch
    return None


def _support_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=SUPPORT_ROLE_NAME)


def _tickets_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    return discord.utils.get(guild.categories, name=TICKETS_CATEGORY_NAME)


def _is_support(member: discord.Member) -> bool:
    role = _support_role(member.guild)
    return role is not None and role in member.roles


# ============================================================
# فتح تكت جديد
# ============================================================
class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key, emoji=emoji)
            for key, emoji, label in TICKET_TYPES
        ]
        super().__init__(
            placeholder="اختر نوع التكت...",
            min_values=1, max_values=1,
            options=options,
            custom_id="ticket_panel_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await open_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    """البانل الدائم اللي يحتوي قائمة اختيار نوع التكت."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())


async def open_ticket(interaction: discord.Interaction, ticket_type: str):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=True)

    category = _tickets_category(guild)
    role = _support_role(guild)
    if category is None or role is None:
        await interaction.followup.send(
            "⚠️ ما لقيت كاتيقوري Tickets أو رتبة TICKETS بالسيرفر، خبر الإدارة.", ephemeral=True)
        return

    number = _db.next_ticket_number(guild.id)
    channel_name = f"{TICKET_CHANNEL_PREFIX}-{number:04d}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    try:
        channel = await guild.create_text_channel(
            channel_name, category=category, overwrites=overwrites,
            reason=f"تكت جديد بواسطة {author}")
    except discord.Forbidden:
        await interaction.followup.send("❌ ما أقدر أنشئ روم التكت (ناقصني صلاحية).", ephemeral=True)
        return

    _db.create_ticket(guild.id, channel.id, author.id, ticket_type, number)

    embed = discord.Embed(
        title=f"🎫 تكت #{number:04d} — {TICKET_TYPE_LABELS[ticket_type]}",
        description=f"أهلًا {author.mention}! فريق الدعم بيوصلك قريب.\n"
                     f"اشرح طلبك أو مشكلتك بالتفصيل وانتظر الرد.",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="النوع", value=TICKET_TYPE_LABELS[ticket_type], inline=True)
    embed.add_field(name="فتحه", value=author.mention, inline=True)
    embed.set_footer(text=f"معرف العضو: {author.id}")

    await channel.send(content=role.mention, embed=embed, view=TicketControlView())
    await interaction.followup.send(f"✅ تم فتح تكتك: {channel.mention}", ephemeral=True)


# ============================================================
# أزرار التحكم بالتكت (استلام / إغلاق / خيارات) — دائمة
# ============================================================
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📥 استلام", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_support(interaction.user):
            await interaction.response.send_message("⚠️ بس فريق الدعم يقدر يستلم التكتات.", ephemeral=True)
            return
        ticket = _db.get_ticket(interaction.channel.id)
        if ticket is None:
            await interaction.response.send_message("⚠️ هذا الروم مو مسجل كتكت.", ephemeral=True)
            return
        if ticket.get("claimed_by"):
            claimer = interaction.guild.get_member(int(ticket["claimed_by"]))
            name = claimer.mention if claimer else "عضو غادر"
            await interaction.response.send_message(f"⚠️ التكت مستلم مسبقًا من {name}.", ephemeral=True)
            return
        _db.set_ticket_claimed(interaction.channel.id, interaction.user.id)
        button.label = f"✅ مستلم: {interaction.user.display_name}"[:80]
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"📥 {interaction.user.mention} استلم التكت.")

    @discord.ui.button(label="🔒 إغلاق", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = _db.get_ticket(interaction.channel.id)
        if ticket is None:
            await interaction.response.send_message("⚠️ هذا الروم مو مسجل كتكت.", ephemeral=True)
            return
        is_opener = str(interaction.user.id) == ticket["opener_id"]
        if not (_is_support(interaction.user) or is_opener):
            await interaction.response.send_message("⚠️ بس فريق الدعم أو صاحب التكت يقدر يغلقه.", ephemeral=True)
            return
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send("🔒 جارٍ إغلاق التكت وحفظ المحادثة خلال 5 ثواني...")
        await close_ticket(interaction.channel, interaction.user, ticket)

    @discord.ui.button(label="⚙️ خيارات", style=discord.ButtonStyle.secondary, custom_id="ticket_options")
    async def options(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_support(interaction.user):
            await interaction.response.send_message("⚠️ بس فريق الدعم يقدر يستخدم الخيارات.", ephemeral=True)
            return
        await interaction.response.send_message("⚙️ اختر إجراء:", view=TicketOptionsView(), ephemeral=True)


async def close_ticket(channel: discord.TextChannel, closer: discord.Member, ticket: dict):
    """يبني ترانسكريبت نصي، يرسله لروم ticket-logs، وبعدها يحذف روم التكت."""
    guild = channel.guild
    lines = []
    async for msg in channel.history(limit=None, oldest_first=True):
        time_str = msg.created_at.strftime("%Y-%m-%d %H:%M")
        content = msg.content or ""
        if msg.attachments:
            content += " " + " ".join(a.url for a in msg.attachments)
        lines.append(f"[{time_str}] {msg.author}: {content}")
    transcript_text = "\n".join(lines) if lines else "(ما فيه رسائل)"
    buffer = io.BytesIO(transcript_text.encode("utf-8"))
    file = discord.File(buffer, filename=f"{channel.name}-transcript.txt")

    opener = guild.get_member(int(ticket["opener_id"]))
    embed = discord.Embed(
        title=f"🔒 تم إغلاق تكت #{ticket['number']:04d}",
        color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="النوع", value=TICKET_TYPE_LABELS.get(ticket["ticket_type"], ticket["ticket_type"]), inline=True)
    embed.add_field(name="فتحه", value=(opener.mention if opener else f"`{ticket['opener_id']}`"), inline=True)
    embed.add_field(name="أغلقه", value=closer.mention, inline=True)
    if ticket.get("claimed_by"):
        claimer = guild.get_member(int(ticket["claimed_by"]))
        embed.add_field(name="مستلم من", value=(claimer.mention if claimer else f"`{ticket['claimed_by']}`"), inline=True)

    log_channel = _find_log_channel(guild)
    if log_channel:
        try:
            await log_channel.send(embed=embed, file=file)
        except (discord.Forbidden, discord.HTTPException):
            pass

    _db.close_ticket(channel.id)
    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"إغلاق تكت بواسطة {closer}")
    except (discord.Forbidden, discord.NotFound):
        pass


# ============================================================
# قائمة "خيارات" الفرعية (إضافة/إزالة عضو، تحويل، تغيير اسم)
# ============================================================
class TicketOptionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="➕ إضافة عضو", style=discord.ButtonStyle.success)
    async def add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر العضو تبي تضيفه:", view=AddMemberSelectView(), ephemeral=True)

    @discord.ui.button(label="➖ إزالة عضو", style=discord.ButtonStyle.danger)
    async def remove_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر العضو تبي تزيله:", view=RemoveMemberSelectView(), ephemeral=True)

    @discord.ui.button(label="🔁 تحويل للموظف", style=discord.ButtonStyle.primary)
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر الموظف تبي تحول له التكت:", view=TransferSelectView(), ephemeral=True)

    @discord.ui.button(label="✏️ تغيير الاسم", style=discord.ButtonStyle.secondary)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RenameModal())


class AddMemberSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="اختر عضو...")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        channel = interaction.channel
        await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.edit_message(content=f"✅ تم إضافة {member.mention} للتكت.", view=None)
        await channel.send(f"➕ {interaction.user.mention} أضاف {member.mention} للتكت.")


class RemoveMemberSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="اختر عضو...")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        channel = interaction.channel
        await channel.set_permissions(member, overwrite=None)
        await interaction.response.edit_message(content=f"✅ تم إزالة {member.mention} من التكت.", view=None)
        await channel.send(f"➖ {interaction.user.mention} أزال {member.mention} من التكت.")


class TransferSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="اختر موظف...")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        if not isinstance(member, discord.Member) or not _is_support(member):
            await interaction.response.edit_message(content="⚠️ هذا العضو مو من فريق الدعم.", view=None)
            return
        channel = interaction.channel
        _db.set_ticket_claimed(channel.id, member.id)
        await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.edit_message(content=f"✅ تم تحويل التكت لـ {member.mention}.", view=None)
        await channel.send(f"🔁 {interaction.user.mention} حول التكت لـ {member.mention}.")


class RenameModal(discord.ui.Modal, title="تغيير اسم روم التكت"):
    new_name = discord.ui.TextInput(label="الاسم الجديد", placeholder="مثال: ticket-ahmed", max_length=90)

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel
        old_name = channel.name
        try:
            await channel.edit(name=self.new_name.value, reason=f"تغيير اسم بواسطة {interaction.user}")
            await interaction.response.send_message(f"✅ تم تغيير الاسم من `{old_name}` إلى `{channel.name}`.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ ما قدرت أغيّر الاسم (جرب بعد شوي — فيه حد لعدد مرات تغيير اسم الروم): {e}", ephemeral=True)


# ============================================================
# الربط بالبوت
# ============================================================
def setup_tickets(bot: commands.Bot) -> None:
    @bot.command(name="تكت")
    async def ticket_panel_cmd(ctx: commands.Context):
        if not (_is_support(ctx.author) or ctx.author.guild_permissions.manage_channels):
            await ctx.send(f"{ctx.author.mention} ❌ ما عندك صلاحية ترسل بانل التكتات.", delete_after=8)
            return
        embed = discord.Embed(
            title="🎫 مركز الدعم",
            description="اختر نوع طلبك من القائمة تحت وبيتفتح لك روم خاص مع فريق الدعم.",
            color=discord.Color.blurple(),
        )
        file = None
        if TICKET_PANEL_IMAGE:
            try:
                file = discord.File(TICKET_PANEL_IMAGE, filename="panel.png")
                embed.set_image(url="attachment://panel.png")
            except FileNotFoundError:
                file = None
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
        if file:
            await ctx.send(embed=embed, view=TicketPanelView(), file=file)
        else:
            await ctx.send(embed=embed, view=TicketPanelView())

    async def _on_ready_tickets():
        bot.add_view(TicketPanelView())
        bot.add_view(TicketControlView())

    bot.add_listener(_on_ready_tickets, "on_ready")
