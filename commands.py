# commands.py
import time
import os
import asyncio
import random
import requests
from io import BytesIO
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from config import (
    BOT_NAME, MAIN_GROUP_LINK, UPDATE_CHANNEL_LINK, MAIN_GROUP_ID,
    TOP_IMAGE, WANTED_IMAGE, TEMP_DIR, VAULT_CAPS, DEVIL_FRUITS, HAKI_NAMES,
    UPDATE_CHANNEL_USERNAME, get_fruit_display_category,
)
from data_manager import (
    get_player, save_data, user_data, GBANNED,
    get_global_giveaway, normal_characters, mythical_characters, exalted_characters,
    get_character_by_id, is_admin_or_owner, get_character_rarities, get_rarity_emoji,
)
from utils import (
    get_xp_needed, get_rank, check_cooldown, parse_amount,
    load_name_font, load_bounty_font, format_short_amount, build_copy_markup,
)
from pvp import (
    send_level_up_notification, send_level_up_group_notification,
    send_level_down_notification, send_level_down_group_notification,
)

my_chars_sessions = {}
show_sessions = {}


def get_show_card(session_key, index):
    """Return caption, keyboard, and character media for a /show card."""
    session = show_sessions.get(session_key)
    if not session or not session.get("characters"):
        return None
    characters = session["characters"]
    index = max(0, min(index, len(characters) - 1))
    character = characters[index]
    name = character.get("name", "Unknown")
    rarity = str(character.get("rarity", "NORMAL")).upper()
    emoji = get_rarity_emoji(rarity)
    caption = (
        "💞 **Card Search**\n\n"
        f"🆔 ID : `{character.get('id', 'N/A')}`\n"
        f"🎟️ Name : {name}\n"
        f"{emoji} Rarity : {rarity}\n\n"
        f"📄 Result {index + 1}/{len(characters)}"
    )
    rows = []
    if len(characters) > 1:
        rows.append([
            InlineKeyboardButton("⬅️ Back", callback_data=f"show_prev_{session_key}_{index}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"show_next_{session_key}_{index}"),
        ])
    rows.append([InlineKeyboardButton("❌ Close", callback_data=f"show_close_{session_key}")])
    return caption, InlineKeyboardMarkup(rows), character


def _load_wanted_template(source):
    """Load a wanted template from a local path or an HTTPS/raw image URL."""
    if not source:
        return None
    try:
        if source.startswith(("https://", "http://")):
            response = requests.get(source, timeout=15)
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGB")
        if os.path.exists(source):
            return Image.open(source).convert("RGB")
    except Exception as e:
        print(f"[info poster template] failed to load {source}: {e}")
    return None


# ==================== POSTER TEXT HELPERS ====================
def _fit_text_font(draw, text, font_loader, max_width, start_size,
                   min_size=14, step=2, max_height=None):
    """Pick the largest font (via font_loader) whose rendered text fits inside
    max_width (and, if given, max_height). Guarantees even huge bounty values
    still fit on-poster."""
    size = start_size
    font = None
    while size >= min_size:
        try:
            font = font_loader(size)
        except Exception:
            font = None
        if font is None:
            try:
                return ImageFont.load_default()
            except Exception:
                return None
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            ok_w = (bbox[2] - bbox[0]) <= max_width
            ok_h = True if max_height is None else (bbox[3] - bbox[1]) <= max_height
            if ok_w and ok_h:
                return font
        except Exception:
            return font
        size -= step
    return font


def _sans_italic(text):
    out = []
    for ch in str(text):
        if "A" <= ch <= "Z":
            out.append(chr(0x1D608 + ord(ch) - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D622 + ord(ch) - ord("a")))
        else:
            out.append(ch)
    return "".join(out)


def _sans_regular(text):
    out = []
    for ch in str(text):
        if "A" <= ch <= "Z":
            out.append(chr(0x1D5A0 + ord(ch) - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D5BA + ord(ch) - ord("a")))
        else:
            out.append(ch)
    return "".join(out)


# ==================== LEADERBOARD HELPERS ====================
def _leaderboard_markup(active):
    labels = {
        "bounty": "💰 Bounty",
        "level": "⚔️ Level",
        "crews": "⚓ Crews",
        "characters": "📦 Collectors",
    }
    buttons = []
    for mode in ("bounty", "level", "crews", "characters"):
        label = labels[mode] + (" ✓" if mode == active else "")
        buttons.append(InlineKeyboardButton(label, callback_data=f"leaderboard_{mode}"))
    return InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"leaderboard_{active}")],
        [InlineKeyboardButton("❌ Close", callback_data="delete_this")],
    ])


def _player_leaderboard_text(mode):
    if mode == "characters":
        def collection_stats(player):
            unique = {
                c.get("id") if c.get("id") is not None else str(c.get("name", "")).casefold()
                for c in player.captured_chars
            }
            return len(unique), len(player.captured_chars)

        collectors = [player for player in user_data.values() if player.captured_chars]
        players = sorted(collectors, key=lambda p: (*collection_stats(p), p.bounty), reverse=True)[:10]
        title, icon = "TOP 10 CHARACTER COLLECTORS", "📦"
    else:
        key = (lambda p: (p.bounty, p.level)) if mode == "bounty" else (lambda p: (p.level, p.bounty))
        players = sorted(user_data.values(), key=key, reverse=True)[:10]
        title = "TOP 10 BOUNTY PLAYERS" if mode == "bounty" else "TOP 10 LEVEL PLAYERS"
        icon = "💰" if mode == "bounty" else "⚔️"
    text = f"🏆 **{title}** 🏆\n────────────────────────\n\n"
    for i in range(10):
        if i < len(players):
            p = players[i]
            name = p.name if p.name and p.name.lower() != "nameless" else f"User_{p.user_id}"
            mention = f"[{name}](https://t.me/{p.username})" if p.username else name
            medal = "👑" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
            if mode == "characters":
                unique_count = len({
                    c.get("id") if c.get("id") is not None else str(c.get("name", "")).casefold()
                    for c in p.captured_chars
                })
                value = f"{icon} {unique_count} unique • {len(p.captured_chars)} total"
            else:
                value = f"{icon} ฿{p.bounty:,}" if mode == "bounty" else f"{icon} Lv.{p.level} • ฿{p.bounty:,}"
            text += f"{medal} {mention}\n   {value}\n\n"
        else:
            text += f"{i + 1}. — No Player\n\n"
    return text + "────────────────────────\n@Grand_Line_Sentinel_bot"


def _crew_leaderboard_text():
    from crew import CREW_STORE, crew_total_bounty, crew_power, crew_level

    crews = list(CREW_STORE.get("crews", {}).values())
    crews.sort(key=lambda c: (crew_total_bounty(c), len(c.get("members", [])), crew_power(c)), reverse=True)
    text = (
        "⚓ **TOP 10 CREWS BY BOUNTY** ⚓\n"
        "────────────────────────\n"
        f"Total crews: **{len(crews)}**\n\n"
    )
    for i in range(10):
        if i < len(crews):
            c = crews[i]
            text += (
                f"{i + 1}. **[{c.get('tag', '?')}]** {c.get('name', 'Unnamed Crew')}\n"
                f"   💰 ฿{crew_total_bounty(c):,} • Members: {len(c.get('members', []))} "
                f"• Lv.{crew_level(c)}\n\n"
            )
        else:
            text += f"{i + 1}. — No Crew\n\n"
    return text + "────────────────────────\n@Grand_Line_Sentinel_bot"


def leaderboard_text(mode):
    return _crew_leaderboard_text() if mode == "crews" else _player_leaderboard_text(mode)


async def show_leaderboard(client, message, mode="bounty", edit=False):
    mode = mode if mode in {"bounty", "level", "crews", "characters"} else "bounty"
    text = leaderboard_text(mode)
    markup = _leaderboard_markup(mode)
    if edit:
        try:
            if message.photo or message.document:
                await message.edit_caption(text, reply_markup=markup)
            else:
                await message.edit_text(text, reply_markup=markup)
            return
        except Exception as e:
            print(f"[leaderboard edit] {e}")
    if TOP_IMAGE:
        try:
            await message.reply_photo(TOP_IMAGE, caption=text, reply_markup=markup)
            return
        except Exception:
            try:
                await message.reply_document(TOP_IMAGE, caption=text, reply_markup=markup)
                return
            except Exception:
                pass
    await message.reply(text, reply_markup=markup)


# ==================== MODULE-LEVEL: SHOW CHARS PAGE ====================
async def show_chars_list_page(client, message, user_id, page):
    """Show a page of the user's captured characters."""
    session = my_chars_sessions.get(user_id)
    if not session:
        return

    char_list = session["char_list"]
    items_per_page = 10
    total_pages = (len(char_list) + items_per_page - 1) // items_per_page

    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0

    start = page * items_per_page
    end = start + items_per_page
    page_chars = char_list[start:end]

    text = f"📦 **YOUR CAPTURED CHARACTERS - PAGE {page + 1}/{max(1, total_pages)}**\n\n"

    keyboard = []

    for i, char in enumerate(page_chars, start + 1):
        live = get_character_by_id(char.get("id")) if char.get("id") not in (None, "N/A") else None
        rarity = (live or {}).get("rarity", char.get("rarity", "NORMAL"))
        rarity_emoji = get_rarity_emoji(rarity)
        text += (
            f"{rarity_emoji} **{i}.** {char['name']} (x{char['count']})\n"
            f"   ID: `{char.get('id', 'N/A')}`\n"
        )

        button = InlineKeyboardButton(
            f"{rarity_emoji} {char['name']} (x{char['count']})",
            switch_inline_query=f"character.{user_id} {char['name']}"
        )
        if keyboard and len(keyboard[-1]) == 1 and keyboard[-1][0].callback_data is None:
            keyboard[-1].append(button)
        else:
            keyboard.append([button])

    text += f"\n📊 **Total:** {len(char_list)} unique characters\n"
    text += f"🎮 **Player ID:** `{user_id}`\n\n"
    text += f"💡 **Tap a character name** to see its photos"

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ PREVIOUS", callback_data=f"chars_page_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("NEXT PAGE ▶️", callback_data=f"chars_page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton(
        f"CHECK ALL ({len(char_list)})",
        switch_inline_query=f"character.{user_id}"
    )])

    keyboard.append([InlineKeyboardButton("❌ CLOSE", callback_data="delete_this")])

    session["current_page"] = page
    my_chars_sessions[user_id] = session

    await message.reply(text, reply_markup=InlineKeyboardMarkup(keyboard))


def register_commands(app):

    # ==================== START COMMAND ====================
    @app.on_message(filters.command("start"))
    async def start_cmd(client, message):
        user_id = message.from_user.id
        p = get_player(user_id, user=message.from_user)
        p.name = message.from_user.first_name
        if message.from_user.username:
            p.username = message.from_user.username
        save_data()

        args = message.text.split()
        if len(args) > 1 and args[1] == "global_giveaway":
            gg = get_global_giveaway()
            if gg is not None:
                if user_id not in gg["participants"]:
                    main_joined = False
                    updates_joined = False

                    try:
                        m = await client.get_chat_member(MAIN_GROUP_ID, user_id)
                        if str(m.status).split(".")[-1].upper() in (
                            "MEMBER", "ADMINISTRATOR", "OWNER", "CREATOR"
                        ):
                            main_joined = True
                    except Exception:
                        pass

                    try:
                        m = await client.get_chat_member(UPDATE_CHANNEL_USERNAME, user_id)
                        if str(m.status).split(".")[-1].upper() in (
                            "MEMBER", "ADMINISTRATOR", "OWNER", "CREATOR"
                        ):
                            updates_joined = True
                    except Exception:
                        pass

                    if main_joined and updates_joined:
                        gg["participants"].append(user_id)
                        await message.reply(
                            f"✅ **Joined the Global Giveaway!**\n\n"
                            f"📦 Prize: ฿{gg['total_prize']:,}\n"
                            f"👥 Total: {len(gg['participants'])}\n\n"
                            f"Good luck!"
                        )
                    else:
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🏠 Join Main Group", url=MAIN_GROUP_LINK)],
                            [InlineKeyboardButton("📢 Join Updates", url=UPDATE_CHANNEL_LINK)],
                            [InlineKeyboardButton("✅ Verify & Join", callback_data="verify_global_giveaway")]
                        ])
                        await message.reply(
                            f"❌ **Join both communities first!**",
                            reply_markup=kb
                        )
                else:
                    await message.reply("✅ **Already joined!**")
            else:
                await message.reply("❌ **No active global giveaway!**")
            return

        is_new = p.bounty == 0 and p.level == 1

        join_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Join Main Group", url=MAIN_GROUP_LINK)],
            [InlineKeyboardButton("📢 Join Updates Channel", url=UPDATE_CHANNEL_LINK)],
            [InlineKeyboardButton("🔄 Check Membership", callback_data="check_membership")]
        ])

        if is_new:
            welcome_text = (
                f"🏴‍☠️ **WELCOME TO GRAND LINE SENTINEL!** 🏴‍☠️\n\n"
                f"⚓ Welcome to the Grand Line, {message.from_user.first_name}!\n"
                f"💪 Your journey to become the Pirate King starts now!\n\n"
                f"📜 **Get started:**\n"
                f"• Use /help to see all commands\n"
                f"• Use /daily to claim daily reward\n"
                f"• Use /shop to buy items\n"
                f"• Use /info to view your profile\n\n"
                f"⚠️ **Please join our communities:**\n"
                f"• Main Group for events\n"
                f"• Updates Channel for news\n\n"
                f"⚔️ **Good luck on your adventure!** ⚔️\n\n"
                f"🤖 @Grand_Line_Sentinel_bot"
            )
        else:
            welcome_text = (
                f"🏴‍☠️ **WELCOME BACK!** 🏴‍☠️\n\n"
                f"⚓ Welcome back, {message.from_user.first_name}!\n"
                f"💪 Continue your journey to become the Pirate King!\n\n"
                f"📊 **Your Stats:**\n"
                f"💰 Bounty: ฿{p.bounty:,}\n"
                f"⚔️ Level: {p.level}\n"
                f"🏆 Rank: {get_rank(p.level)}\n\n"
                f"📜 Use /help for commands.\n\n"
                f"🤖 @Grand_Line_Sentinel_bot"
            )

        await message.reply(welcome_text, reply_markup=join_keyboard, disable_web_page_preview=True)

    # ==================== HELP COMMAND (Public) ====================
    @app.on_message(filters.command("help"))
    async def help_cmd(client, message):
        await message.reply(
            f"📜 **COMMANDS** 📜\n\n"
            f"💰 **GAMES (CD: 2s):**\n"
            f"/bet [amount] [t/h] - 🪙 Coin flip\n"
            f"/dice [amount] [e/o] - 🎲 Dice game\n"
            f"/dart [amount] - 🎯 Dart game\n"
            f"/bowl [amount] - 🎳 Bowling game\n"
            f"/soccer [amount] - ⚽ Soccer game\n"
            f"/slot [amount] - 🎰 Slot machine (3x on 7️⃣7️⃣7️⃣)\n\n"
            f"/mines [amount] - 💣 Mines gambling game\n\n"
            f"/basket [amount] - 🏀 Basketball dice game\n"
            f"/rps [amount] - ✊ Rock Paper Scissors vs bot or player\n\n"
            f"👤 **PROFILE:**\n"
            f"/info - 📸 Your wanted poster\n"
            f"/bal - 💰 Check balance\n"
            f"/xp - 📈 Check level and XP bar\n"
            f"/tokens - 🔮 Check advanced tokens\n"
            f"/daily - 📅 Daily reward (10k)\n"
            f"/weekly - 📆 Weekly reward (1M)\n"
            f"/claim - 🎁 Main group join reward\n"
            f"/top - 🏆 Top 10 bounty\n"
            f"/xtop - ⚔️ Top 10 level\n\n"
            f"🎒 **INVENTORY:**\n"
            f"/inventory - 📦 View your items\n"
            f"/useshield - 🛡️ Activate a shield\n"
            f"/useboost - ⚡ Activate an XP boost\n\n"
            f"🛒 **SHOP:**\n"
            f"/shop - 🏪 Buy items\n"
            f"/fruits - 🍎 Check your Devil Fruit\n"
            f"/sell_fruit - 🍎 Sell fruit (50%)\n\n"
            f"🎣 **FISHING:**\n"
            f"/fish - Cast your line\n"
            f"/fishing - Player XP and equipment status\n"
            f"/fishes - View your fish\n"
            f"/sell_fish - Sell fish one by one or all\n\n"
            f"⚔️ **PVP & FIGHT:**\n"
            f"/attack - ⚔️ Fight player (reply)\n"
            f"/rob - 💰 Rob player (reply)\n"
            f"/challenge [name] - 👹 Fight character\n"
            f"/timeleft - ⏰ Character despawn timer\n"
            f"/mychars - 📦 Your captured characters\n"
            f"/trade [amount] - 💰 Sell character (reply)\n"
            f"/battle - 🌑 Fight World Boss\n\n"
            f"🏦 **VAULT:**\n"
            f"/deposit [amount] - 📥 Store bounty\n"
            f"/dig [amount] - 📤 Withdraw bounty\n\n"
            f"⚙️ **SETTINGS:**\n"
            f"/pvp - ⚔️ Toggle PVP Mode\n"
            f"/passive - 🛡️ Toggle Shield Protection\n\n"
            f"⚔️ **HAKI:**\n"
            f"/haki - 📊 View your Haki\n"
            f"/activehaki - 🟢 Activate Haki\n"
            f"/disactivehaki - 🔴 Deactivate Haki\n"
            f"/upgradehaki - ⬆️ Level up Haki\n"
            f"/sell_haki - 💵 Sell Haki\n\n"
            f"⚓ **CREW:**\n"
            f"/crew - 📋 Crew menu\n"
            f"/crewcreate [name] | [TAG] - Create crew\n"
            f"/crewinfo - Crew info\n"
            f"/crewlist - Top crews\n"
            f"/crewtop - Full leaderboard\n"
            f"/crewbank - Shared bank\n"
            f"/ship - View your ship\n"
            f"/shiplist - All ships\n\n"
            f"🎁 **GIVEAWAY:**\n"
            f"/join - Join active giveaway\n\n"
            f"📊 **CHARACTER INFO:**\n"
            f"/charinfo [name] or /c [name] - View character info\n"
            f"@Grand_Line_Sentinel_bot [name] - Search inline\n\n"
            f"🤖 @Grand_Line_Sentinel_bot"
        )

    # ==================== BALANCE COMMAND ====================
    @app.on_message(filters.command("bal"))
    async def balance_cmd(client, message):
        if message.reply_to_message:
            target_user = message.reply_to_message.from_user
            p = get_player(target_user.id, user=target_user)
            name = target_user.first_name
        else:
            p = get_player(message.from_user.id, user=message.from_user)
            name = message.from_user.first_name

        cap = VAULT_CAPS.get(p.vault_level, 25_000_000)
        await message.reply(
            f"**{name}'s Bounty:** ฿`{p.bounty:,}`\n"
            f"**Vault:** ฿`{p.vault:,}` / `{cap:,}`",
            reply_markup=build_copy_markup([
                ("📋 Copy Bounty", f"{int(p.bounty or 0)}"),
            ]),
        )

    # ==================== XP COMMAND ====================
    @app.on_message(filters.command("xp"))
    async def xp_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        needed = get_xp_needed(p.level)
        current = min(max(int(p.xp or 0), 0), needed)
        filled = min(10, int((current / needed) * 10)) if needed else 0
        bar = "█" * filled + "░" * (10 - filled)
        await message.reply(
            f"📈 **XP PROGRESS**\n\n"
            f"⚔️ Level: **{p.level}**\n"
            f"🏆 Rank: **{get_rank(p.level)}**\n\n"
            f"`{bar}`\n"
            f"XP: **{current:,} / {needed:,}**\n"
            f"Remaining: **{max(0, needed - current):,} XP**"
        )

    # ==================== TOKENS COMMAND ====================
    @app.on_message(filters.command("tokens"))
    async def tokens_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        await message.reply(
            f"🔮 **ADVANCED TOKENS** 🔮\n\n"
            f"📦 Tokens: ⚜️**{p.advanced_token}**\n"
            f"✨ Advanced Haki: **{'✅ Unlocked' if p.advanced_haki else '❌ Locked'}**"
        )

    # ==================== DAILY COMMAND ====================
    @app.on_message(filters.command("daily"))
    async def daily_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        now = int(time.time())
        if now - p.daily < 86400:
            left = 86400 - (now - p.daily)
            await message.reply(f"📅 Already claimed! Next in {left // 3600}h")
            return
        p.daily = now
        p.bounty += 10_000
        p.xp += 50
        if p.boost_end > time.time():
            p.xp += 25

        old_lvl = p.level
        while p.xp >= get_xp_needed(p.level) and p.level < 200:
            p.xp -= get_xp_needed(p.level)
            p.level += 1
        if p.level >= 200:
            p.xp = 0

        save_data()

        if p.level > old_lvl:
            await send_level_up_notification(app, message.from_user.id, old_lvl, p.level, "daily")
            await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)

        lt = f"\n\n🎉 **LEVEL UP!** {old_lvl} → {p.level}" if p.level > old_lvl else ""
        await message.reply(f"🎁 **Daily:** ฿10,000 + 50 XP!{lt}")

    # ==================== WEEKLY COMMAND ====================
    @app.on_message(filters.command("weekly"))
    async def weekly_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        now = int(time.time())
        if now - p.weekly < 604800:
            left = 604800 - (now - p.weekly)
            await message.reply(f"📆 Already claimed! Next in {left // 86400}d")
            return
        p.weekly = now
        p.bounty += 1_000_000
        p.xp += 500
        if p.boost_end > time.time():
            p.xp += 250

        old_lvl = p.level
        while p.xp >= get_xp_needed(p.level) and p.level < 200:
            p.xp -= get_xp_needed(p.level)
            p.level += 1
        if p.level >= 200:
            p.xp = 0

        save_data()

        if p.level > old_lvl:
            await send_level_up_notification(app, message.from_user.id, old_lvl, p.level, "weekly")
            await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)

        lt = f"\n\n🎉 **LEVEL UP!** {old_lvl} → {p.level}" if p.level > old_lvl else ""
        await message.reply(f"🎁 **Weekly:** ฿1,000,000 + 500 XP!{lt}")

    # ==================== SHOW CHARACTER(S) ====================
    @app.on_message(filters.command("show"))
    async def show_character_cmd(client, message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            await message.reply("Usage: `/show [character name]`\nExample: `/show Luffy`")
            return

        query = args[1].strip().casefold()
        all_characters = normal_characters + mythical_characters + exalted_characters
        exact = [c for c in all_characters if str(c.get("name", "")).casefold() == query]
        matches = exact or [
            c for c in all_characters
            if query in str(c.get("name", "")).casefold()
        ]
        matches.sort(key=lambda c: (
            str(c.get("name", "")).casefold(),
            int(c.get("id", 0)) if str(c.get("id", "0")).isdigit() else 0,
        ))
        if not matches:
            await message.reply(f"❌ No character connected with **{args[1].strip()}**.")
            return

        session_key = f"{message.from_user.id}_{int(time.time() * 1000) % 1000000}"
        show_sessions[session_key] = {"characters": matches, "owner_id": message.from_user.id}
        card = get_show_card(session_key, 0)
        caption, markup, character = card
        media = character.get("image")
        try:
            if media and character.get("media_type") == "video":
                await message.reply_video(media, caption=caption, reply_markup=markup)
            elif media:
                try:
                    await message.reply_photo(media, caption=caption, reply_markup=markup)
                except Exception:
                    await message.reply_document(media, caption=caption, reply_markup=markup)
            else:
                await message.reply(caption, reply_markup=markup)
        except Exception:
            await message.reply(caption, reply_markup=markup)

    # ==================== CHARACTER INFO ====================
    @app.on_message(
        filters.command("charinfo")
        | filters.command("c")
        | filters.command("charid")
        | filters.command("checkchar")
    )
    async def character_info_cmd(client, message):
        args = message.text.split(maxsplit=1)
        command_name = (message.command[0] if message.command else "charinfo").lower()
        if len(args) < 2:
            await message.reply(
                "📊 **CHARACTER INFO**\n\n"
                "Usage: `/charinfo [name]` or `/c [name]`\n"
                "Example: `/charinfo Zoro`\n\n"
                "🆔 Short lookup: `/c [id]` (for example, `/c 123`)"
            )
            return

        raw_query = args[1].strip()
        query = raw_query.lower()
        found = None
        ctype = None

        if query.isdigit():
            found = get_character_by_id(int(query))
            if found:
                ctype = found.get("rarity", "NORMAL")
        elif command_name in {"charid", "checkchar"}:
            await message.reply(f"❌ Invalid character ID: `{raw_query}`")
            return

        if found:
            query = ""
        for c in normal_characters:
            if found:
                break
            if c.get("name", "").lower() == query:
                found, ctype = c, c.get("rarity", "NORMAL")
                break
        if not found:
            for c in mythical_characters:
                if c.get("name", "").lower() == query:
                    found, ctype = c, c.get("rarity", "MYTHICAL")
                    break
        if not found:
            for c in exalted_characters:
                if c.get("name", "").lower() == query:
                    found, ctype = c, c.get("rarity", "EXALTED")
                    break
        if not found:
            for c in normal_characters:
                if query in c.get("name", "").lower():
                    found, ctype = c, c.get("rarity", "NORMAL")
                    break
        if not found:
            for c in mythical_characters:
                if query in c.get("name", "").lower():
                    found, ctype = c, c.get("rarity", "MYTHICAL")
                    break
        if not found:
            for c in exalted_characters:
                if query in c.get("name", "").lower():
                    found, ctype = c, c.get("rarity", "EXALTED")
                    break

        if not found:
            await message.reply(f"❌ Character **{args[1]}** not found!")
            return

        capturers = []
        total = 0
        for uid_str, pl in user_data.items():
            cnt = sum(1 for c in pl.captured_chars if c.get("name") == found["name"])
            if cnt > 0:
                total += cnt
                capturers.append({
                    "user_id": pl.user_id,
                    "name": pl.name or f"User_{uid_str}",
                    "username": pl.username,
                    "count": cnt,
                })
        capturers.sort(key=lambda x: x["count"], reverse=True)

        cap_lines = []
        for i, st in enumerate(capturers[:15], 1):
            if st["username"]:
                m = f"[{st['name']}](https://t.me/{st['username']})"
            else:
                m = f"[{st['name']}](tg://user?id={st['user_id']})"
            cap_lines.append(f"{i}. {m} - {st['count']}x")
        if len(capturers) > 15:
            cap_lines.append(f"... +{len(capturers) - 15} more")
        cap_text = "\n".join(cap_lines) if cap_lines else "No one captured yet."

        info_text = (
            f"📊 **CHARACTER INFO**\n\n"
            f"👤 **Name:** {found['name']}\n"
            f"{get_rarity_emoji(ctype)} **Rarity:** {ctype}\n"
            f"🆔 **ID:** {found.get('id', 'N/A')}\n"
            f"📦 **Captures:** {total}\n\n"
            f"🏆 **Captured by:**\n{cap_text}\n\n"
            f"🤖 @Grand_Line_Sentinel_bot"
        )

        img = found.get("image")
        if img and isinstance(img, str):
            try:
                if found.get("media_type") == "video":
                    await message.reply_video(img, caption=info_text)
                    return
                if img.startswith(("http://", "https://")):
                    await message.reply_photo(img, caption=info_text)
                    return
                try:
                    await message.reply_photo(img, caption=info_text)
                    return
                except Exception:
                    await message.reply_document(img, caption=info_text)
                    return
            except Exception:
                pass
        await message.reply(info_text)

    # ==================== TOP COMMAND ====================
    @app.on_message(filters.command("top"))
    async def top_cmd(client, message):
        await show_leaderboard(client, message, "bounty")

    # ==================== XTOP COMMAND ====================
    @app.on_message(filters.command("xtop"))
    async def xtop_cmd(client, message):
        await show_leaderboard(client, message, "level")

    # ==================== CREW TOP COMMAND ====================
    @app.on_message(filters.command("crewtop"))
    async def crew_top_cmd(client, message):
        await show_leaderboard(client, message, "crews")

    @app.on_message(filters.command(["topchars", "topcharacters", "charactertop"]))
    async def character_top_cmd(client, message):
        await show_leaderboard(client, message, "characters")

    # ==================== CLAIM COMMAND ====================
    @app.on_message(filters.command("claim"))
    async def claim_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if message.chat.id != MAIN_GROUP_ID:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Join Main Group", url=MAIN_GROUP_LINK)],
                [InlineKeyboardButton("🔄 Check Again", callback_data="try_claim")]
            ])
            await message.reply(
                f"❌ **Use this in the main group!**\n\n{MAIN_GROUP_LINK}",
                reply_markup=kb,
                disable_web_page_preview=True
            )
            return

        if p.claimed_main:
            await message.reply("❌ Already claimed!")
            return

        p.claimed_main = True
        p.bounty += 3_000_000
        p.xp += 200
        p.boost_end = max(p.boost_end, time.time() + 900)

        old_lvl = p.level
        while p.xp >= get_xp_needed(p.level) and p.level < 200:
            p.xp -= get_xp_needed(p.level)
            p.level += 1
        if p.level >= 200:
            p.xp = 0

        save_data()

        if p.level > old_lvl:
            await send_level_up_notification(app, message.from_user.id, old_lvl, p.level, "claim")
            await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)

        lt = f"\n\n🎉 **LEVEL UP!** {old_lvl} → {p.level}" if p.level > old_lvl else ""
        await message.reply(
            f"🎁 **CLAIMED!**\n\n"
            f"💰 +฿3,000,000\n"
            f"⭐ +200 XP\n"
            f"⚡ 2x XP (15 min){lt}\n\n"
            f"🏆 ฿{p.bounty:,}\n"
            f"⚔️ Lv.{p.level}"
        )

    # ==================== PVP TOGGLE ====================
    @app.on_message(filters.command("pvp"))
    async def pvp_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        p.pvp_enabled = not p.pvp_enabled
        save_data()
        if p.pvp_enabled:
            await message.reply(f"⚔️ **PVP: ON**\n\nYou can attack and be attacked.")
        else:
            await message.reply(f"🛡️ **PVP: OFF**\n\nYou're safe from attacks.")

    # ==================== PASSIVE TOGGLE ====================
    @app.on_message(filters.command("passive"))
    async def passive_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        p.passive_enabled = not p.passive_enabled
        save_data()
        if p.passive_enabled:
            await message.reply(f"🛡️ **PASSIVE: ON**\n\nShield will protect you.")
        else:
            await message.reply(f"⚔️ **PASSIVE: OFF**\n\nShield won't protect you.")

    # ==================== INFO COMMAND ====================
    @app.on_message(filters.command("info"))
    async def info_cmd(client, message):
        if message.reply_to_message:
            u = message.reply_to_message.from_user
            p = get_player(u.id, user=u)
            player_name = u.first_name
            is_self = False
        else:
            u = message.from_user
            p = get_player(u.id, user=u)
            player_name = u.first_name
            is_self = True

        need = get_xp_needed(p.level)
        rank = get_rank(p.level)

        if p.haki:
            haki_name = HAKI_NAMES.get(p.haki, p.haki)
            haki_line = f"Haki: {haki_name} Lv.{p.haki_level}"
        else:
            haki_line = "Haki: None"

        is_banned = p.user_id in GBANNED
        passive_status = "🟢 ON" if p.passive_enabled else "🔴 OFF"
        pvp_status = "⚔️ ON" if p.pvp_enabled else "🛡️ OFF"

        fruit_display = f"{_sans_italic('None None No Mi')}, ({_sans_regular('None')})"
        if p.devil_fruit:
            found = False
            for _, fruits in DEVIL_FRUITS.items():
                for fruit in fruits:
                    if fruit["full"] == p.devil_fruit:
                        fruit_display = (
                            f"{_sans_italic(fruit['full'])} "
                            f"({_sans_regular(get_fruit_display_category(fruit))})"
                        )
                        found = True
                        break
                if found:
                    break
            if not found:
                fruit_display = _sans_italic(p.devil_fruit)

        save_data()

        percent = min(10, int((p.xp / need) * 10)) if need > 0 else 0
        bar = "■" * percent + "□" * (10 - percent)
        xp_needed = max(0, need - p.xp)

        sorted_players = sorted(user_data.values(), key=lambda x: x.bounty, reverse=True)
        global_rank = 1
        for i, pl in enumerate(sorted_players, 1):
            if pl.user_id == p.user_id:
                global_rank = i
                break

        crew_name = "None"
        crew_position = "None"
        crew_rank = "N/A"
        try:
            from crew import CREW_STORE, get_player_crew, crew_total_bounty
            crew = get_player_crew(p.user_id)
            if crew:
                crew_name = crew.get("name", "Unnamed Crew")
                if str(crew.get("captain_id")) == str(p.user_id):
                    crew_position = "Captain"
                elif str(p.user_id) in [str(x) for x in crew.get("officers", [])]:
                    crew_position = "Officer"
                else:
                    crew_position = "Member"
                ranked_crews = sorted(
                    CREW_STORE.get("crews", {}).values(),
                    key=lambda c: crew_total_bounty(c),
                    reverse=True,
                )
                crew_rank = next(
                    (i for i, c in enumerate(ranked_crews, 1)
                     if c.get("tag") == crew.get("tag")),
                    "N/A",
                )
        except Exception as e:
            print(f"[info crew] {e}")

        ban_warning = ""
        if is_banned:
            ban_warning = "\n⚠️ **GLOBALLY BANNED!** ⚠️\n"

        stats = (
            f"**{player_name}**  [`{p.user_id}`]\n"
            f"──────────────────\n"
            f"Username: @{p.username or 'None'}\n"
            f"Rank: {rank}\n"
            f"Passive: {'Yes' if p.passive_enabled else 'No'}\n"
            f"{haki_line}\n"
            f"Global Rank: {global_rank}\n"
            f"──────────────────\n"
            f"Bounty: ฿{p.bounty:,}\n"
            f"Vault: ฿{p.vault:,}/{VAULT_CAPS.get(p.vault_level, 25_000_000):,}\n"
            f"──────────────────\n"
            f"Level: {p.level}\n"
            f"[{bar}] ({xp_needed}XP for next level)\n"
            f"──────────────────\n"
            f"🏴‍☠️ **Crew Details**\n"
            f"• Name: {crew_name}\n"
            f"• Position: {crew_position}\n"
            f"• Rank: {crew_rank}\n"
            f"Devil Fruit: {fruit_display}"
            f"{ban_warning}\n"
            f"🤖 @Grand_Line_Sentinel_bot"
        )

        # Poster generation
        if PIL_AVAILABLE and WANTED_IMAGE:
            try:
                template = _load_wanted_template(WANTED_IMAGE)
                if template is None:
                    raise FileNotFoundError(f"Cannot load wanted template: {WANTED_IMAGE}")
                poster = template.resize((1000, 1400))

                # Use the configured absolute temp directory; the VPS may
                # start the bot from a different working directory.
                pfp_path = os.path.join(TEMP_DIR, f"pfp_{p.user_id}.jpg")
                pfp = None
                if os.path.exists(pfp_path):
                    pfp = pfp_path
                else:
                    try:
                        async for photo in client.get_chat_photos(int(p.user_id), limit=1):
                            pfp = await client.download_media(photo.file_id, file_name=pfp_path)
                            break
                    except Exception:
                        pfp = None
                    if not pfp and getattr(u, "photo", None):
                        try:
                            pfp = await client.download_media(
                                u.photo.big_file_id or u.photo.small_file_id,
                                file_name=pfp_path,
                            )
                        except Exception:
                            pfp = None

                if pfp and os.path.exists(pfp):
                    try:
                        img = Image.open(pfp).convert("RGB")
                        img = ImageOps.fit(img, (820, 588), Image.Resampling.LANCZOS)
                        poster.paste(img, (90, 298))
                    except Exception as e:
                        print(f"[poster pfp] {e}")

                draw = ImageDraw.Draw(poster)

                import unicodedata
                # Keep letters (incl. bold/styled Unicode like 𝐊𝐎𝐁𝐀), marks,
                # numbers, and punctuation (incl. "|" so "KOBA |STR|" survives).
                # Only Control chars and decorative Symbols (e.g. emoji) are
                # stripped — they would otherwise break the poster layout.
                _NAME_ALLOWED = {
                    "Lu", "Ll", "Lt", "Lm", "Lo",   # letters (incl. styled)
                    "Mn", "Mc", "Me",               # combining marks
                    "Nd", "Nl", "No",               # numbers
                    "Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po",  # punctuation
                }
                cleaned = "".join(
                    c for c in player_name
                    if unicodedata.category(c) in _NAME_ALLOWED
                ).strip() or f"User {p.user_id}"
                if len(cleaned) > 16:
                    cleaned = cleaned[:15] + "…"
                name_text = cleaned.upper() if cleaned.isascii() else cleaned

                name_font = None
                name_y = 996
                for size in (150, 140, 130, 120, 110, 100, 90, 80, 70, 60):
                    try:
                        f = load_name_font(size, name_text)
                        if f is None:
                            continue
                        bbox = draw.textbbox((0, 0), name_text, font=f)
                        if bbox[2] - bbox[0] <= 900:
                            name_font = f
                            name_y = 996 + (150 - size) // 3
                            break
                    except Exception:
                        continue

                if name_font is None:
                    name_font = load_name_font(60, name_text) or ImageFont.load_default()
                    name_y = 1015

                name_bottom = name_y + 120
                try:
                    bbox = draw.textbbox((0, 0), name_text, font=name_font)
                    tw = bbox[2] - bbox[0]
                    x = (1000 - tw) // 2
                    draw.text((x, name_y), name_text, fill=(80, 55, 25), font=name_font)
                    name_bottom = name_y + bbox[3]
                except Exception:
                    pass

                bounty_value = p.bounty if isinstance(p.bounty, (int, float)) else 0
                # Full comma-separated number with a trailing dash. The
                # template already contains the currency symbol at left.
                # (Same format a user would read on a real Marine wanted page.)
                bounty_text = f"{bounty_value:,}-"

                # ---- Bounty sits DIRECTLY UNDER the name, inside the band
                #      (NO box is drawn — it was only a guide in the mock-up).
                #      The font auto-shrinks if the full number is wider than
                #      the band, so even a 10**18 value still fits.  ONLY the
                #      user's own bounty font (Vrinda.ttf) is used — no
                #      external / AI font is introduced.
                BAND_LEFT, BAND_RIGHT = 205, 795
                BAND_TOP = max(1150, name_bottom + 8)
                BAND_BOTTOM = 1272
                if BAND_BOTTOM - BAND_TOP < 70:
                    BAND_TOP = BAND_BOTTOM - 70
                max_width = BAND_RIGHT - BAND_LEFT
                max_height = (BAND_BOTTOM - BAND_TOP) - 8

                bounty_font = _fit_text_font(
                    draw, bounty_text, load_bounty_font, max_width,
                    start_size=170, min_size=14, step=2,
                    max_height=max_height,
                ) or ImageFont.load_default()

                try:
                    bbox = draw.textbbox((0, 0), bounty_text, font=bounty_font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    x = (1000 - tw) // 2
                    y = BAND_TOP + ((BAND_BOTTOM - BAND_TOP) - th) // 2 - bbox[1]
                    draw.text(
                        (x, y), bounty_text,
                        fill=(80, 55, 25), font=bounty_font,
                    )
                except Exception as e:
                    print(f"[poster bounty] {e}")

                buf = BytesIO()
                poster.save(buf, format="JPEG", quality=90, optimize=True)
                buf.seek(0)
                buf.name = f"wanted_{p.user_id}.jpg"

                await message.reply_photo(
                    buf, caption=stats,
                    reply_markup=build_copy_markup([
                        ("📋 Copy Bounty", f"{int(bounty_value)}"),
                    ]),
                )
                return

            except Exception as e:
                print(f"[info poster] {e}")

        if not PIL_AVAILABLE:
            print("[info poster] Pillow is unavailable; install requirements.txt")
        elif not WANTED_IMAGE or (
            not WANTED_IMAGE.startswith(("https://", "http://"))
            and not os.path.exists(WANTED_IMAGE)
        ):
            print(f"[info poster] wanted template missing: {WANTED_IMAGE}")
        await message.reply(stats)

    # ==================== MYCHARS ====================
    @app.on_message(filters.command("mychars"))
    async def my_chars_cmd(client, message):
        user_id = message.from_user.id
        p = get_player(user_id, user=message.from_user)

        if not p.captured_chars:
            await message.reply(
                "📭 **No captured characters yet!**\n\n"
                "Fight spawning characters with `/challenge `[name]!"
            )
            return

        char_counts = {}
        for char in p.captured_chars:
            name = char.get("name", "Unknown")
            char_id = char.get("id")
            key = char_id if char_id is not None else f"legacy:{str(name).casefold()}"
            live = get_character_by_id(char_id) if char_id is not None else None
            entry = char_counts.setdefault(key, {
                "name": name,
                "id": char_id if char_id is not None else "N/A",
                "rarity": (live or {}).get("rarity", char.get("rarity", "NORMAL")),
                "captured_at": char.get("captured_at", 0),
                "count": 0,
            })
            if live:
                entry["name"] = live.get("name", name)
                entry["rarity"] = live.get("rarity", entry["rarity"])
            entry["count"] += 1
            # Show the most recent capture time for duplicate characters.
            try:
                newer = float(char.get("captured_at", 0) or 0)
                current = float(entry.get("captured_at", 0) or 0)
            except (TypeError, ValueError):
                newer, current = 0, 0
            if newer > current:
                entry["captured_at"] = char.get("captured_at")

        char_list = list(char_counts.values())

        my_chars_sessions[user_id] = {
            "char_list": char_list,
            "current_page": 0,
        }

        await show_chars_list_page(client, message, user_id, 0)
