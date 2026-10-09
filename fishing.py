# fishing.py
import random
import json
import os

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    BOT_NAME, OWNER_ID, DATA_DIR, FISHES, FISHING_STICKER, FISHING_RODS, FISHING_BAITS,
    FISHING_PLAYER_XP,
)
from data_manager import get_player, save_data
from utils import get_xp_needed

_FISHING_STICKER_FILE = os.path.join(DATA_DIR, "fishing_sticker.json")
try:
    with open(_FISHING_STICKER_FILE, "r", encoding="utf-8") as _fh:
        _saved_sticker = json.load(_fh).get("file_id", "")
        if _saved_sticker:
            FISHING_STICKER = _saved_sticker
except (FileNotFoundError, OSError, ValueError, AttributeError):
    pass


def _player_xp_bar(player):
    need = get_xp_needed(player.level)
    progress = min(10, int((player.xp / need) * 10)) if need else 10
    return "█" * progress + "░" * (10 - progress)


def _fish_value(name):
    low, high = FISHES.get(name, (0, 0))
    return random.randint(low, high)


def fishing_status_text(player):
    rod = player.fishing_rod or {}
    bait = player.fishing_bait or {}
    rod_info = FISHING_RODS.get(rod.get("type"), {})
    bait_info = FISHING_BAITS.get(bait.get("type"), {})
    total = sum(int(v) for v in player.fish_inventory.values())
    return (
        f"🎣 **FISHING STATUS**\n\n"
        f"Player Level: **{player.level}**\n"
        f"XP: `{_player_xp_bar(player)}` {player.xp}/{get_xp_needed(player.level)}\n\n"
        f"Rod: **{rod_info.get('name', rod.get('type', 'None'))}** "
        f"({max(0, int(rod.get('uses', 0)))}/{rod.get('max_uses', 0)} uses)\n"
        f"Bait: **{bait_info.get('name', bait.get('type', 'None'))}** "
        f"({max(0, int(bait.get('uses', 0)))}/{bait.get('max_uses', 0)} uses)\n"
        f"Fish held: **{total}**\n\n{BOT_NAME}"
    )


def _fish_inventory_text(player):
    if not player.fish_inventory:
        return "🐟 **YOUR FISH**\n\nNo fish yet. Use `/fish` to cast your line."
    lines = ["🐟 **YOUR FISH**\n"]
    for index, (name, count) in enumerate(player.fish_inventory.items(), 1):
        low, high = FISHES.get(name, (0, 0))
        lines.append(f"**{index}.** {name} ×{count} — ฿{low:,}–฿{high:,} each")
    lines.append(f"\nTotal fish: {sum(player.fish_inventory.values())}")
    return "\n".join(lines)


def _fish_sell_keyboard(player):
    rows = []
    for index, (name, count) in enumerate(player.fish_inventory.items()):
        rows.append([InlineKeyboardButton(
            f"Sell {name} ×{count}", callback_data=f"fish_sell_one_{index}"
        )])
    if player.fish_inventory:
        rows.append([InlineKeyboardButton("Sell All Fish", callback_data="fish_sell_all")])
    rows.append([InlineKeyboardButton("Close", callback_data="delete_this")])
    return InlineKeyboardMarkup(rows)


def register_fishing(app):
    @app.on_message(filters.command("setfish"))
    async def set_fish_sticker_cmd(client, message):
        global FISHING_STICKER
        if message.from_user.id != OWNER_ID:
            await message.reply("")
            return
        replied = message.reply_to_message
        if not replied or not replied.sticker:
            await message.reply(
                "Reply to a sticker with `/setfish` to set the fishing sticker."
            )
            return
        file_id = replied.sticker.file_id
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(_FISHING_STICKER_FILE, "w", encoding="utf-8") as fh:
                json.dump({"file_id": file_id}, fh)
            FISHING_STICKER = file_id
            await message.reply("✅ Fishing sticker saved. `/fish` will use it now.")
        except OSError as exc:
            print(f"[fishing sticker save] {exc}")
            await message.reply("❌ Could not save the fishing sticker.")

    @app.on_message(filters.command("fish"))
    async def fish_cmd(client, message):
        player = get_player(message.from_user.id, user=message.from_user)
        rod = player.fishing_rod or {}
        bait = player.fishing_bait or {}
        if int(rod.get("uses", 0)) <= 0:
            await message.reply("❌ Your fishing rod is broken. Buy a new rod in `/shop`.")
            return
        if int(bait.get("uses", 0)) <= 0:
            await message.reply("❌ Your bait is finished. Buy more bait in `/shop`.")
            return

        if FISHING_STICKER:
            try:
                await message.reply_sticker(FISHING_STICKER)
            except Exception as e:
                print(f"[fishing sticker] {e}")
        else:
            await message.reply("🎣 Casting the line...")

        rod_type = rod.get("type", "wooden")
        bait_type = bait.get("type", "basic")
        rod["uses"] = max(0, int(rod.get("uses", 0)) - 1)
        bait["uses"] = max(0, int(bait.get("uses", 0)) - 1)
        player.fishing_rod = rod
        player.fishing_bait = bait

        fish_name = random.choice(list(FISHES))
        value = _fish_value(fish_name)
        player.fish_inventory[fish_name] = player.fish_inventory.get(fish_name, 0) + 1
        xp_gain = FISHING_PLAYER_XP + FISHING_RODS.get(rod_type, {}).get("xp_bonus", 0) + FISHING_BAITS.get(bait_type, {}).get("xp_bonus", 0)
        old_level = player.level
        player.xp += xp_gain
        while player.level < 200 and player.xp >= get_xp_needed(player.level):
            player.xp -= get_xp_needed(player.level)
            player.level += 1
        if player.level >= 200:
            player.xp = 0
        save_data()

        level_text = f"\n🎉 Level Up: {old_level} → {player.level}" if old_level != player.level else ""
        broken = "\n⚠️ Your rod or bait is now empty—visit `/shop` to replace it." if not rod["uses"] or not bait["uses"] else ""
        await message.reply(
            f"🐟 **You caught a {fish_name}!**\n\n"
            f"Value: ฿{value:,}\n"
            f"Player XP: +{xp_gain}\n"
            f"XP: `{_player_xp_bar(player)}` {player.xp}/{get_xp_needed(player.level)}\n"
            f"Rod uses left: {rod['uses']}\n"
            f"Bait uses left: {bait['uses']}"
            f"{level_text}{broken}"
        )

    @app.on_message(filters.command(["fishes", "sell_fish"]))
    async def fish_inventory_cmd(client, message):
        player = get_player(message.from_user.id, user=message.from_user)
        if not player.fish_inventory:
            await message.reply(_fish_inventory_text(player))
            return
        await message.reply(_fish_inventory_text(player), reply_markup=_fish_sell_keyboard(player))

    @app.on_message(filters.command("fishing"))
    async def fishing_status_cmd(client, message):
        player = get_player(message.from_user.id, user=message.from_user)
        await message.reply(fishing_status_text(player))
