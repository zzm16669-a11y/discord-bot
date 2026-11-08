"""
card_backgrounds.py — متجر خلفيات بطاقة البروفايل (وحدة مستقلة داخل bot.py)
=========================================================================
- زر "🖼️ خلفية" بالمتجر ← 20 زر (خلفية 1 ... خلفية 20) سعر كل وحدة 3000 نقطة.
- الضغط على رقم = معاينة بطاقتك (الأفتار + البنك + النقاط + الزينة) على الخلفية قبل الشراء.
- الصور الأفقية بمجلد  card_backgrounds  بجنب bot.py  بأسماء:  1.png  2.png ... 20.png
  (يقبل png / jpg / jpeg / webp)
- مستقلة: ما تلمس games.py ولا أي بوت ثاني. تخزينها بملف card_backgrounds.json بس،
  وتخصم النقاط من economy.json بنفس طريقة bot.py.
"""

import json
import os

import discord

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

BG_DIR = "card_backgrounds"
BG_COUNT = 20
BG_PRICE = 3000
BG_FILE = "card_backgrounds.json"
ECONOMY_FILE = "economy.json"
BG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
EMBED_COLOR = 0x2ECC71

_renderer = None       # async (guild, member, bg_num) -> BytesIO   (يتعبّى من bot.py)
_shop_factory = None   # (member) -> ShopView                      (يتعبّى من bot.py)


def set_renderer(fn) -> None:
    global _renderer
    _renderer = fn


def set_shop_factory(fn) -> None:
    global _shop_factory
    _shop_factory = fn


# ---------------- تخزين ----------------
def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_entry(guild_id: int, user_id: int) -> dict:
    e = _load(BG_FILE).get(str(guild_id), {}).get(str(user_id), {})
    return {"owned": list(e.get("owned", [])), "active": e.get("active")}


def _save_entry(guild_id: int, user_id: int, entry: dict) -> None:
    data = _load(BG_FILE)
    data.setdefault(str(guild_id), {})[str(user_id)] = entry
    _save(BG_FILE, data)


def get_active(guild_id: int, user_id: int):
    """رقم الخلفية اللي لابسها العضو (أو None)."""
    return get_entry(guild_id, user_id).get("active")


def _balance(guild_id: int, user_id: int) -> int:
    return int(_load(ECONOMY_FILE).get(str(guild_id), {}).get(str(user_id), 0))


def _spend(guild_id: int, user_id: int, amount: int) -> bool:
    data = _load(ECONOMY_FILE)
    gid, uid = str(guild_id), str(user_id)
    bal = int(data.get(gid, {}).get(uid, 0))
    if bal < amount:
        return False
    data.setdefault(gid, {})[uid] = bal - amount
    _save(ECONOMY_FILE, data)
    return True


def find_image(num: int):
    for ext in BG_EXTS:
        p = os.path.join(BG_DIR, f"{num}{ext}")
        if os.path.exists(p):
            return p
    return None


# ---------------- دمج الخلفية مع قالب البطاقة ----------------
def apply_background(base, bg_num):
    """يركّب الصورة الأفقية خلف القالب: الصورة تغطي البطاقة، تغمق تدريجيًا لتحت (عشان النص يبان)،
    وزخارف القالب (الشرائط والإطارات) تبقى فوقها. لو ما فيه خلفية يرجع القالب كما هو."""
    if not bg_num or not PIL_AVAILABLE:
        return base
    path = find_image(int(bg_num))
    if not path:
        return base
    try:
        W, H = base.size
        bg = Image.open(path).convert("RGB")
        scale = max(W / bg.width, H / bg.height)
        nw, nh = max(W, int(bg.width * scale + 0.5)), max(H, int(bg.height * scale + 0.5))
        bg = bg.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - W) // 2, (nh - H) // 2
        bg = bg.crop((left, top, left + W, top + H))

        # تغميق تدريجي: خفيف فوق، قوي تحت (منطقة الاسم والصناديق)
        col = Image.new("L", (1, H), 0)
        y0, y1 = int(H * 0.40), int(H * 0.70)
        for y in range(H):
            if y <= y0:
                a = 35
            elif y >= y1:
                a = 228
            else:
                a = 35 + (228 - 35) * (y - y0) / (y1 - y0)
            col.putpixel((0, y), int(a))
        shade = col.resize((W, H))
        bg = Image.composite(Image.new("RGB", (W, H), (8, 18, 22)), bg, shade)

        # زخارف القالب (الفاتحة) فوق الخلفية
        tpl = base.convert("RGB")
        orn = tpl.convert("L").point(lambda v: 0 if v < 38 else min(255, (v - 38) * 5))
        bg.paste(tpl, (0, 0), orn)

        # قص بزوايا دايرية داخل إطار القالب
        ss = 2
        rm = Image.new("L", (W * ss, H * ss), 0)
        ImageDraw.Draw(rm).rounded_rectangle((9 * ss, 9 * ss, (W - 9) * ss, (H - 9) * ss),
                                             radius=56 * ss, fill=255)
        rm = rm.resize((W, H), Image.LANCZOS)
        out = tpl.copy()
        out.paste(bg, (0, 0), rm)
        return out.convert("RGBA")
    except Exception as e:
        print(f"[خلفيات] تعذّر تركيب الخلفية {bg_num}: {e}")
        return base


# ---------------- واجهة المتجر ----------------
class BackgroundsView(discord.ui.View):
    def __init__(self, member: discord.Member, mode: str = "list", sel: int | None = None):
        super().__init__(timeout=300)
        self.member = member
        self.mode = mode
        self.sel = sel
        self.build()

    # ----- الإطار -----
    def embed(self) -> discord.Embed:
        g = self.member.guild
        bal = _balance(g.id, self.member.id)
        entry = get_entry(g.id, self.member.id)
        e = discord.Embed(color=EMBED_COLOR)
        e.set_author(name=f"متجر {g.name}", icon_url=g.icon.url if g.icon else None)
        if self.mode == "preview" and self.sel:
            e.title = f"🖼️ خلفية {self.sel} — معاينة"
            if self.sel in entry["owned"]:
                state = "✅ مفعّلة عندك" if entry["active"] == self.sel else "✅ تملكها — اضغط تفعيل"
            else:
                state = f"السعر: **{BG_PRICE}** نقطة"
            e.description = f"💰 رصيدك: **{bal}** نقطة\n{state}\n\nهذي معاينة، ما انحفظ شي لين تشتري."
        else:
            e.title = "🖼️ خلفيات البطاقة"
            e.description = (f"💰 رصيدك: **{bal}** نقطة\n\nاضغط على رقم الخلفية وتشوف بطاقتك عليها قبل الشراء.\n"
                             f"سعر كل خلفية: **{BG_PRICE}** نقطة، تشتريها مرة وحدة وتبقى لك.\n"
                             "✅ = تملكها | الأخضر = اللي لابسها الحين")
        return e

    def _btn(self, label, style, row, cb, emoji=None, disabled=False):
        b = discord.ui.Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)
        b.callback = cb
        self.add_item(b)

    def build(self):
        self.clear_items()
        S = discord.ButtonStyle
        g = self.member.guild
        entry = get_entry(g.id, self.member.id)
        if self.mode == "list":
            for n in range(1, BG_COUNT + 1):
                async def cb(interaction, _n=n):
                    await self.show(interaction, "preview", _n)
                owned = n in entry["owned"]
                if entry["active"] == n:
                    style = S.success
                elif owned:
                    style = S.primary
                else:
                    style = S.secondary
                self._btn(f"خلفية {n}", style, (n - 1) // 5, cb, "✅" if owned else None,
                          disabled=find_image(n) is None)

            async def home(interaction):
                await self.go_shop(interaction)

            async def clear(interaction):
                e = get_entry(g.id, self.member.id)
                e["active"] = None
                _save_entry(g.id, self.member.id, e)
                await self.show(interaction, "list")
            self._btn("القائمة الرئيسية", S.secondary, 4, home, "🏠")
            if entry["active"]:
                self._btn("إزالة الخلفية", S.danger, 4, clear, "🗑️")
        else:
            n = self.sel
            bal = _balance(g.id, self.member.id)
            if n in entry["owned"]:
                async def equip(interaction):
                    e = get_entry(g.id, self.member.id)
                    e["active"] = n
                    _save_entry(g.id, self.member.id, e)
                    await self.show(interaction, "preview", n)
                    await interaction.followup.send(f"✅ لبست **خلفية {n}** — اكتب `p` تشوف بطاقتك.", ephemeral=True)
                self._btn("مفعّلة" if entry["active"] == n else "تفعيل",
                          S.success, 0, equip, "✅", disabled=entry["active"] == n)
            else:
                async def buy(interaction):
                    e = get_entry(g.id, self.member.id)
                    if n in e["owned"]:
                        await self.show(interaction, "preview", n)
                        return
                    if not _spend(g.id, self.member.id, BG_PRICE):
                        await interaction.response.send_message(
                            f"❌ رصيدك ما يكفي (تحتاج {BG_PRICE} نقطة).", ephemeral=True)
                        return
                    e["owned"].append(n)
                    e["active"] = n
                    _save_entry(g.id, self.member.id, e)
                    await self.show(interaction, "preview", n)
                    await interaction.followup.send(
                        f"✅ اشتريت **خلفية {n}** وانلبست على بطاقتك! اكتب `p` تشوفها.", ephemeral=True)
                self._btn(f"شراء — {BG_PRICE} نقطة", S.primary if bal >= BG_PRICE else S.secondary, 0, buy, "🛒")

            async def back(interaction):
                await self.show(interaction, "list")
            self._btn("رجوع للخلفيات", S.secondary, 0, back, "◀️")

    # ----- تنقل وعرض -----
    async def show(self, interaction: discord.Interaction, mode: str, sel: int | None = None):
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.mode, self.sel = mode, sel
        self.build()
        try:
            if mode == "preview":
                if _renderer is None:
                    raise RuntimeError("renderer not set")
                buf = await _renderer(self.member.guild, self.member, sel)
                file = discord.File(buf, filename="preview.png")
                embed = self.embed()
                embed.set_image(url="attachment://preview.png")
                await interaction.edit_original_response(embed=embed, view=self, attachments=[file])
            else:
                await interaction.edit_original_response(embed=self.embed(), view=self, attachments=[])
        except Exception as e:
            print(f"[خلفيات] خطأ بعرض المعاينة: {e}")
            try:
                await interaction.followup.send("❌ صار خطأ وأنا أرسم المعاينة.", ephemeral=True)
            except discord.HTTPException:
                pass

    async def go_shop(self, interaction: discord.Interaction):
        if _shop_factory is None:
            await interaction.response.send_message("اكتب `.متجر` من جديد.", ephemeral=True)
            return
        v = _shop_factory(self.member)
        v.message = interaction.message
        await interaction.response.edit_message(embed=v.embed(), view=v, attachments=[])
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("هذا المتجر مو لك، اكتب `.متجر` تفتح متجرك.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def open_backgrounds(interaction: discord.Interaction, member: discord.Member) -> None:
    """يفتحه زر "🖼️ خلفية" من المتجر."""
    view = BackgroundsView(member)
    await interaction.response.edit_message(embed=view.embed(), view=view)
