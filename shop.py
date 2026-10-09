# shop.py
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    BOT_NAME, SHOP_IMAGE, VAULT_CAPS,
    FRUIT_SELL_REFUNDS, DEVIL_FRUITS, FRUIT_CATEGORIES,
    get_fruit_tier, get_fruit_icon, normalize_fruit_name,
    get_fruit_category, get_fruit_display_category,
)
from data_manager import get_player, save_data
from utils import parse_amount


def _sans_italic(text):
    out = []
    for ch in str(text):
        code = ord(ch)
        if "A" <= ch <= "Z":
            out.append(chr(0x1D608 + code - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D622 + code - ord("a")))
        else:
            out.append(ch)
    return "".join(out)


def _sans_regular(text):
    out = []
    for ch in str(text):
        code = ord(ch)
        if "A" <= ch <= "Z":
            out.append(chr(0x1D5A0 + code - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D5BA + code - ord("a")))
        else:
            out.append(ch)
    return "".join(out)


def register_shop(app):

    # ==================== /shop ====================
    @app.on_message(filters.command("shop"))
    async def shop_cmd(client, message):
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚔️ Haki", callback_data="shop_haki"),
                InlineKeyboardButton("🛡️ Shield", callback_data="shop_shield"),
                InlineKeyboardButton("🍎 Devil Fruit", callback_data="shop_fruit"),
            ],
            [
                InlineKeyboardButton("🏦 Vault", callback_data="shop_vault"),
                InlineKeyboardButton("⚡ 2x XP", callback_data="shop_boost"),
                InlineKeyboardButton("🔄 Switch Haki", callback_data="shop_switch_haki"),
            ],
            [InlineKeyboardButton("🎣 Fishing Rods & Bait", callback_data="shop_fishing")],
        ])
        text = f"**SHOP**\n\nSelect a category.\n\n{BOT_NAME}"

        if SHOP_IMAGE and isinstance(SHOP_IMAGE, str) and SHOP_IMAGE.strip():
            try:
                await message.reply_photo(SHOP_IMAGE, caption=text, reply_markup=kb)
                return
            except Exception as e:
                print(f"[shop] photo failed: {e}")
            try:
                await message.reply_document(SHOP_IMAGE, caption=text, reply_markup=kb)
                return
            except Exception as e:
                print(f"[shop] document failed: {e}")

        await message.reply(text, reply_markup=kb)

    # ==================== /fruits ====================
    @app.on_message(filters.command("fruits"))
    async def fruits_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        if not p.devil_fruit:
            await message.reply("❌ You don't have a Devil Fruit yet.")
            return

        fruit_name = normalize_fruit_name(p.devil_fruit)
        category = "Unknown"
        for fruit_group in DEVIL_FRUITS.values():
            for fruit in fruit_group:
                if fruit.get("full") == p.devil_fruit or fruit.get("full") == fruit_name:
                    fruit_name = fruit.get("full", fruit_name)
                    category = get_fruit_display_category(fruit)
                    break

        await message.reply(
            f"**Your Fruit:** {_sans_italic(fruit_name)}.\n"
            f"**Category:** {_sans_regular(category)}.\n\n"
            f"You can return this Devil Fruit!\n"
            f"**NOTE:** You will get 50% of the price back!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Sell Fruit", callback_data="fruits_sell")]
            ]),
        )

    # ==================== /sell_fruit ====================
    @app.on_message(filters.command("sell_fruit"))
    async def sell_fruit_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        if not p.devil_fruit:
            await message.reply("❌ You don't have a devil fruit!")
            return

        normalized = normalize_fruit_name(p.devil_fruit)
        tier = get_fruit_tier(normalized) or p.fruit_category or "Bad"
        refund = FRUIT_SELL_REFUNDS.get(tier, 12_500_000)

        fruit_name = normalized
        icon = get_fruit_icon(fruit_name)

        await message.reply(
            f"**SELL DEVIL FRUIT**\n\n"
            f"{icon} **Fruit:** {fruit_name}\n"
            f"Refund: ฿{refund:,} (50%)\n\n"
            f"This will permanently remove your fruit. Confirm?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm Sell", callback_data="confirm_sell_fruit")],
                [InlineKeyboardButton("❌ Cancel", callback_data="noop")],
            ]),
        )

    # ==================== /fruitlist ====================
    @app.on_message(filters.command("fruitlist"))
    async def fruit_list_cmd(client, message):
        text = "**ALL DEVIL FRUITS BY CANONICAL TYPE**\n"
        text += "────────────────────────────────\n\n"
        fruits_by_type = {}
        for fruit_group in DEVIL_FRUITS.values():
            for fruit in fruit_group:
                category = get_fruit_category(fruit)
                fruits_by_type.setdefault(category, []).append(fruit)
        for category in FRUIT_CATEGORIES:
            if category not in fruits_by_type:
                continue
            fruits = sorted(fruits_by_type[category], key=lambda f: f["full"].casefold())
            text += f"**{category}** ({len(fruits)}):\n"
            for fruit in fruits:
                icon = get_fruit_icon(fruit["full"])
                text += f"  {icon} {fruit['full']} — {get_fruit_display_category(fruit)}\n"
            text += "\n"

        text += f"{BOT_NAME}"

        def _split(t, limit=4000):
            lines = t.split("\n")
            out, buf = [], ""
            for line in lines:
                if len(buf) + len(line) + 1 > limit:
                    out.append(buf)
                    buf = line
                else:
                    buf = f"{buf}\n{line}" if buf else line
            if buf:
                out.append(buf)
            return out

        for chunk in _split(text):
            await message.reply(chunk)

    # ==================== /deposit ====================
    @app.on_message(filters.command("deposit"))
    async def deposit_cmd(client, message):
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/deposit [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ **Invalid amount!** Must be positive.")
            return

        p = get_player(message.from_user.id, user=message.from_user)
        cap = VAULT_CAPS.get(p.vault_level, 25_000_000)
        if amount > p.bounty:
            await message.reply(f"Not enough! You have ฿{p.bounty:,}")
            return
        if p.vault + amount > cap:
            await message.reply(f"Vault full! Capacity: ฿{cap:,}")
            return

        p.bounty -= amount
        p.vault += amount
        save_data()
        await message.reply(
            f"Deposited ฿{amount:,}!\n"
            f"Vault: ฿{p.vault:,}\n"
            f"Bounty: ฿{p.bounty:,}"
        )

    # ==================== /dig ====================
    @app.on_message(filters.command("dig"))
    async def dig_cmd(client, message):
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/dig [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ **Invalid amount!** Must be positive.")
            return

        p = get_player(message.from_user.id, user=message.from_user)
        if amount > p.vault:
            await message.reply(f"Not enough! Vault: ฿{p.vault:,}")
            return

        p.vault -= amount
        p.bounty += amount
        save_data()
        await message.reply(
            f"Withdrew ฿{amount:,}!\n"
            f"Vault: ฿{p.vault:,}\n"
            f"Bounty: ฿{p.bounty:,}"
        )
