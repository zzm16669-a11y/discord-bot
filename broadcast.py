import asyncio
import discord
from discord.ui import Button, View


class StopBroadcastView(View):
    def __init__(self, author_id: int, stop_event: asyncio.Event):
        super().__init__(timeout=3600)
        self.author_id = author_id
        self.stop_event = stop_event

    @discord.ui.button(label="إيقاف الإرسال", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ فقط من بدأ البرودكاست يستطيع إيقافه.", ephemeral=True
            )
            return

        self.stop_event.set()
        button.disabled = True
        await interaction.response.edit_message(
            content="🛑 تم طلب إيقاف البرودكاست، جاري إنهاء الإرسال الحالي...",
            view=self,
        )


def setup_broadcast(bot: discord.Client):
    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot or not message.guild:
            return

        content = message.content.strip()
        if content == ".dc" or content.startswith(".dc "):
            if not message.author.guild_permissions.administrator:
                await message.reply("❌ هذا الأمر مخصص للإدارة فقط.")
                return

            broadcast_text = message.content[3:].strip()
            if not broadcast_text:
                await message.reply(
                    "⚠️ اكتب الرسالة بعد الأمر، مثال:\n`.dc حياكم الله في السيرفر`"
                )
                return

            targets = [m for m in message.guild.members if not m.bot]
            if not targets:
                await message.reply("⚠️ لا يوجد أعضاء مستهدفون للإرسال.")
                return

            stop_event = asyncio.Event()
            view = StopBroadcastView(message.author.id, stop_event)

            status_msg = await message.reply(
                f"⏳ بدأ الإرسال لـ **{len(targets)}** عضو (تأخير 3 ثواني بين كل رسالة)...",
                view=view,
            )

            sent_count = 0
            failed_count = 0

            for index, member in enumerate(targets):
                if stop_event.is_set():
                    break

                try:
                    await member.send(f"{broadcast_text}\n<@{member.id}>")
                    sent_count += 1
                except Exception:
                    failed_count += 1

                if index < len(targets) - 1 and not stop_event.is_set():
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=3.0)
                        break
                    except asyncio.TimeoutError:
                        pass

            title = "🛑 **تم إيقاف البرودكاست!**" if stop_event.is_set() else "✅ **اكتمل البرودكاست!**"
            remaining = len(targets) - (sent_count + failed_count)
            await status_msg.edit(
                content=(
                    f"{title}\n"
                    f"• تم الإرسال بنجاح: **{sent_count}**\n"
                    f"• فشل الإرسال (الخاص مقفل أو خطأ): **{failed_count}**\n"
                    f"• المتبقي غير المرسل: **{remaining}**"
                ),
                view=None,
            )