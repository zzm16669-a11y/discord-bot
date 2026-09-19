import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print(f"Logged in as: {bot.user}")


@bot.command()
async def staff(ctx):
  await ctx.send("🔒 هذا أمر خاص بإدارة السيرفر")

@bot.command()
async def staff(ctx):
  await ctx.send("هذا أمر خاص بإدارة السيرفر 🔒")


bot.run(os.getenv("DISCORD_TOKEN")