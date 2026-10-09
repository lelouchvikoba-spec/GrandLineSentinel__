# crew.py
import json
import os
import time
from datetime import datetime
from io import BytesIO

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    BOT_NAME, DATA_DIR, FONTS_DIR,
    SHIPS, SHIP_MAX_TIER, SHIP_IMAGES,
    TIMEZONE,
)
from data_manager import (
    get_player, save_data, user_data, is_admin_or_owner,
    _atomic_json_write,
)
from utils import parse_amount

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


CREW_FILE = os.path.join(DATA_DIR, "crews.json")

# ---------- constants ----------
CREW_CREATE_COST = 50_000_000
CREW_MAX_MEMBERS = 10
CREW_TAG_MIN = 2
CREW_TAG_MAX = 5
INVITE_TTL = 86400
CREW_IMAGE_CHANGE_COST = 10_000_000
CREW_TOP_LIMIT = 10

CREW_IMAGE_LISTEN = {}


# ---------- storage ----------
def _default_store():
    return {"crews": {}, "player_crew": {}, "pending_invites": {}}


def load_crews():
    try:
        with open(CREW_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_store()
        data.setdefault("crews", {})
        data.setdefault("player_crew", {})
        data.setdefault("pending_invites", {})
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_store()


def save_crews():
    try:
        _atomic_json_write(CREW_FILE, CREW_STORE)
        # NEW: sync to channel storage
        try:
            from data_manager import _sync_to_channel
            _sync_to_channel("crews.json")
        except Exception:
            pass
    except Exception as e:
        print(f"[crew] save failed: {e}")


CREW_STORE = _default_store()


def _migrate_crews():
    for tag, c in CREW_STORE["crews"].items():
        if "image" not in c:
            c["image"] = None
        try:
            c["ship_tier"] = min(max(1, int(c.get("ship_tier", 1))), SHIP_MAX_TIER)
        except (ValueError, TypeError):
            c["ship_tier"] = 1
        try:
            c["bank"] = int(c.get("bank", 0) or 0)
        except (ValueError, TypeError):
            c["bank"] = 0
        if not isinstance(c.get("members"), list):
            c["members"] = []
        if not isinstance(c.get("officers"), list):
            c["officers"] = []


def reload_crews():
    global CREW_STORE
    CREW_STORE = load_crews()
    _migrate_crews()


# ---------- helpers ----------
def get_crew(tag):
    if not tag:
        return None
    return CREW_STORE["crews"].get(str(tag).upper())


def get_player_crew(user_id):
    tag = CREW_STORE["player_crew"].get(str(user_id))
    if not tag:
        return None
    return get_crew(tag)


def is_captain(user_id, crew):
    if not crew:
        return False
    return str(crew.get("captain_id")) == str(user_id)


def is_officer(user_id, crew):
    if not crew:
        return False
    return str(user_id) in [str(x) for x in crew.get("officers", [])]


def is_member(user_id, crew):
    if not crew:
        return False
    return str(user_id) in [str(x) for x in crew.get("members", [])]


def can_manage(user_id, crew):
    return is_captain(user_id, crew) or is_officer(user_id, crew)


def crew_total_bounty(crew):
    total = 0
    for uid in crew.get("members", []):
        p = user_data.get(str(uid))
        if p:
            total += p.bounty
    return total


def crew_avg_bounty(crew):
    n = len(crew.get("members", []))
    return crew_total_bounty(crew) // n if n else 0


def crew_power(crew):
    total = 0
    for uid in crew.get("members", []):
        p = user_data.get(str(uid))
        if p:
            total += p.level
    return total


def crew_level(crew):
    member_count = len(crew.get("members", []))
    total_bounty = crew_total_bounty(crew)
    lvl = 1
    lvl += min(3, member_count // 3)
    lvl += min(5, total_bounty // 1_000_000_000)
    return min(lvl, 10)


def _safe_ship_tier(crew):
    try:
        return min(max(1, int(crew.get("ship_tier", 1))), SHIP_MAX_TIER)
    except (ValueError, TypeError):
        return 1


def crew_ship(crew):
    return SHIPS[_safe_ship_tier(crew)]


def crew_ship_bonus(crew, bonus_type):
    return crew_ship(crew).get(bonus_type, 0.0)


def player_crew_bonus(user_id, bonus_type):
    crew = get_player_crew(user_id)
    if not crew:
        return 0.0
    return crew_ship_bonus(crew, bonus_type)


def find_crew_by_tag_or_name(query):
    q = str(query).upper()
    for tag, crew in CREW_STORE["crews"].items():
        if tag == q:
            return crew
        if crew["name"].upper() == q:
            return crew
        if q in crew["name"].upper():
            return crew
    return None


def top_crews(limit=10):
    crews = list(CREW_STORE["crews"].values())
    crews.sort(
        key=lambda c: (crew_level(c), crew_power(c), c.get("bank", 0)),
        reverse=True,
    )
    return crews[:limit]


def top_crews_by_bounty(limit=None):
    items = []
    for c in CREW_STORE["crews"].values():
        tb = crew_total_bounty(c)
        items.append((tb, len(c.get("members", [])), crew_power(c), c))
    items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    crews = [x[3] for x in items]
    return crews[:limit] if limit else crews


# ==================== CAPTAIN MENTION ====================
def _captain_display(crew):
    from utils import build_mention

    if not crew:
        return "*Unknown*"

    captain_id = crew.get("captain_id")
    if not captain_id:
        return "*Unknown*"

    captain = user_data.get(str(captain_id))
    name = (captain.name if captain and captain.name else None) or f"User {captain_id}"

    if len(name) > 20:
        name = name[:19] + "…"

    username = captain.username if captain else None

    return build_mention(captain_id, name, username)


# ==================== OVERVIEW BUILDER ====================
async def _build_crew_overview(crew, detailed=False):
    tag = crew["tag"]
    lvl = crew_level(crew)
    power = crew_power(crew)
    member_count = len(crew["members"])

    ship_tier = _safe_ship_tier(crew)
    ship = SHIPS[ship_tier]

    cap = get_player(crew["captain_id"])
    cap_name = cap.name or str(crew["captain_id"])

    lines = []
    for i, uid in enumerate(crew["members"], 1):
        p = user_data.get(str(uid))
        name = (p.name if p else None) or f"User {uid}"
        badge = ""
        if str(uid) == str(crew["captain_id"]):
            badge = " (Captain)"
        elif is_officer(uid, crew):
            badge = " (Officer)"
        bounty = f"฿{p.bounty:,}" if p else "?"
        lvl_p = f"Lv.{p.level}" if p else "?"
        lines.append(f"{i}. {name}{badge} — {lvl_p} • {bounty}")

    text = (
        f"**[{tag}] {crew['name']}**\n"
        f"──────────────────\n"
        f"Level: {lvl}\n"
        f"Power: {power}\n"
        f"Members: {member_count}/{CREW_MAX_MEMBERS}\n"
        f"Bank: ฿{crew.get('bank', 0):,}\n"
        f"Ship: {ship['emoji']} {ship['name']} (Tier {ship_tier})\n"
        f"Captain: {cap_name}\n"
        f"W/L: {crew.get('wins', 0)}/{crew.get('losses', 0)}\n"
        f"──────────────────\n"
        f"**Members:**\n" + "\n".join(lines)
    )
    if detailed:
        created = datetime.fromtimestamp(
            crew.get("created_at", 0), tz=TIMEZONE
        ).strftime("%Y-%m-%d")
        text += f"\n──────────────────\nFounded: {created}"
    text += f"\n\n{BOT_NAME}"
    return text


def _build_crew_menu_kb(user_id, crew):
    rows = []
    if can_manage(user_id, crew):
        rows.append([
            InlineKeyboardButton("Bank", callback_data="crewmenu_bank"),
            InlineKeyboardButton("Members", callback_data="crewmenu_members"),
        ])
        rows.append([
            InlineKeyboardButton("Invite", callback_data="crewmenu_invite"),
            InlineKeyboardButton("Ship", callback_data="crewmenu_ship"),
        ])
    if is_captain(user_id, crew):
        rows.append([
            InlineKeyboardButton("Manage", callback_data="crewmenu_manage"),
        ])
    rows.append([
        InlineKeyboardButton("Leave", callback_data="crewmenu_leave"),
    ])
    return InlineKeyboardMarkup(rows)


# ==================== CREW BANNER (auto-generated) ====================
def _pick_crew_color(tag):
    palette = [
        (200, 40, 40), (30, 100, 200), (40, 160, 80), (180, 60, 180),
        (220, 140, 30), (200, 60, 100), (60, 60, 60), (20, 140, 140),
    ]
    h = 0
    for ch in tag:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return palette[h % len(palette)]


def generate_crew_banner(tag, name, members_count, level, power):
    if not PIL_AVAILABLE:
        return None
    try:
        W, H = 1200, 480
        bg = _pick_crew_color(tag)
        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)

        for i in range(0, W, 40):
            draw.line(
                [(i, 0), (i + H, H)],
                fill=tuple(min(255, c + 20) for c in bg),
                width=2,
            )

        try:
            font_tag = ImageFont.truetype(
                os.path.join(FONTS_DIR, "TimesNewRoman-Bold.ttf"), 160
            )
            font_name = ImageFont.truetype(
                os.path.join(FONTS_DIR, "TimesNewRoman-Bold.ttf"), 72
            )
            font_small = ImageFont.truetype(
                os.path.join(FONTS_DIR, "arial.ttf"), 40
            )
        except Exception:
            font_tag = font_name = font_small = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), tag, font=font_tag)
        draw.text(
            ((W - (bbox[2] - bbox[0])) // 2, 60),
            tag, fill=(255, 255, 255), font=font_tag,
        )

        bbox = draw.textbbox((0, 0), name, font=font_name)
        draw.text(
            ((W - (bbox[2] - bbox[0])) // 2, 250),
            name[:40], fill=(255, 230, 200), font=font_name,
        )

        stats = f"Lv.{level}  •  Members: {members_count}  •  Power: {power}"
        bbox = draw.textbbox((0, 0), stats, font=font_small)
        draw.text(
            ((W - (bbox[2] - bbox[0])) // 2, 380),
            stats, fill=(255, 255, 255), font=font_small,
        )

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)
        buf.name = "crew.jpg"
        return buf
    except Exception as e:
        print(f"[crew banner] {e}")
        return None


async def _send_crew_media(target, crew, caption, markup=None):
    img = crew.get("image")
    if img:
        try:
            await target.reply_photo(img, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            print(f"[crew img photo] {e}")
        try:
            await target.reply_document(img, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            print(f"[crew img doc] {e}")

    banner = generate_crew_banner(
        crew["tag"], crew["name"],
        len(crew["members"]), crew_level(crew), crew_power(crew),
    )
    if banner:
        try:
            await target.reply_photo(banner, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            print(f"[crew banner] {e}")

    await target.reply(caption, reply_markup=markup)


# ==================== TOP 10 RENDERERS ====================
def _medal(i):
    return (
        "👑" if i == 1 else
        "🥈" if i == 2 else
        "🥉" if i == 3 else
        f"{i}."
    )


async def _show_crew_top_page(client, message, page=0, edit=False):
    crews = top_crews_by_bounty(CREW_TOP_LIMIT)
    if not crews:
        text = "📭 **No crews yet.** Create one with `/crewcreate`!"
        if edit:
            try:
                await message.edit_text(text)
                return
            except Exception:
                pass
        await message.reply(text)
        return

    all_crews = list(CREW_STORE["crews"].values())

    text = (
        f"**TOP {CREW_TOP_LIMIT} CREWS BY BOUNTY**\n"
        f"──────────────────\n"
        f"Total crews: **{len(all_crews)}**\n"
        f"──────────────────\n\n"
    )

    for i, c in enumerate(crews, 1):
        tb = crew_total_bounty(c)
        ship_emoji = SHIPS[_safe_ship_tier(c)]["emoji"]
        captain_mention = _captain_display(c)

        text += (
            f"{_medal(i)} **[{c['tag']}]** {c['name']}\n"
            f"   Captain: {captain_mention}\n"
            f"   ฿{tb:,} • Members: {len(c['members'])} • "
            f"Lv.{crew_level(c)} • {ship_emoji} T{_safe_ship_tier(c)}\n\n"
        )

    text += "──────────────────\n"
    text += f"{BOT_NAME}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bounty", callback_data="crewtop_bounty"),
            InlineKeyboardButton("Level", callback_data="crewtop_level"),
            InlineKeyboardButton("Power", callback_data="crewtop_power"),
        ],
        [InlineKeyboardButton("Refresh", callback_data="crewtop_bounty")],
        [InlineKeyboardButton("Close", callback_data="delete_this")],
    ])

    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.reply(text, reply_markup=kb)


async def _show_crew_top_by_level(client, message, page=0, edit=False):
    crews = list(CREW_STORE["crews"].values())
    crews.sort(key=lambda c: (crew_level(c), crew_total_bounty(c)), reverse=True)
    crews = crews[:CREW_TOP_LIMIT]
    await _render_top10(
        client, message, crews,
        header="**TOP 10 CREWS BY LEVEL**",
        value_fn=lambda c: f"Lv.{crew_level(c)}",
        edit=edit,
    )


async def _show_crew_top_by_power(client, message, page=0, edit=False):
    crews = list(CREW_STORE["crews"].values())
    crews.sort(key=lambda c: (crew_power(c), crew_total_bounty(c)), reverse=True)
    crews = crews[:CREW_TOP_LIMIT]
    await _render_top10(
        client, message, crews,
        header="**TOP 10 CREWS BY POWER**",
        value_fn=lambda c: f"Power: {crew_power(c)}",
        edit=edit,
    )


async def _render_top10(client, message, crews, header, value_fn, edit=False):
    if not crews:
        text = "📭 No crews yet."
        if edit:
            try:
                await message.edit_text(text)
                return
            except Exception:
                pass
        await message.reply(text)
        return

    all_crews = list(CREW_STORE["crews"].values())
    text = (
        f"{header}\n"
        f"──────────────────\n"
        f"Total crews: **{len(all_crews)}**\n"
        f"──────────────────\n\n"
    )

    for i, c in enumerate(crews, 1):
        ship_emoji = SHIPS[_safe_ship_tier(c)]["emoji"]
        captain_mention = _captain_display(c)

        text += (
            f"{_medal(i)} **[{c['tag']}]** {c['name']}\n"
            f"   Captain: {captain_mention}\n"
            f"   {value_fn(c)} • Members: {len(c['members'])} • "
            f"฿{crew_total_bounty(c):,} • {ship_emoji} T{_safe_ship_tier(c)}\n\n"
        )

    text += "──────────────────\n"
    text += f"{BOT_NAME}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bounty", callback_data="crewtop_bounty"),
            InlineKeyboardButton("Level", callback_data="crewtop_level"),
            InlineKeyboardButton("Power", callback_data="crewtop_power"),
        ],
        [InlineKeyboardButton("Refresh", callback_data="crewtop_bounty")],
        [InlineKeyboardButton("Close", callback_data="delete_this")],
    ])

    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.reply(text, reply_markup=kb)


# ==================== CREW IMAGE HELPERS ====================
async def _apply_crew_image(client, message, crew, file_id):
    uid = message.from_user.id

    if not is_captain(uid, crew):
        await message.reply("❌ You are no longer the Captain.")
        CREW_IMAGE_LISTEN.pop(str(uid), None)
        return

    if isinstance(file_id, str) and file_id.startswith(("http://", "https://")) \
            and file_id.lower().endswith(".gif"):
        await message.reply("❌ GIFs not supported.")
        return

    p = get_player(uid)
    if p.bounty < CREW_IMAGE_CHANGE_COST:
        await message.reply(
            f"❌ Need ฿{CREW_IMAGE_CHANGE_COST:,}.\nYou have ฿{p.bounty:,}."
        )
        return

    p.bounty -= CREW_IMAGE_CHANGE_COST
    crew["image"] = file_id
    save_data()
    save_crews()
    CREW_IMAGE_LISTEN.pop(str(uid), None)

    await message.reply(
        f"✅ **Crew image updated!**\n\n"
        f"[{crew['tag']}] {crew['name']}\n"
        f"-฿{CREW_IMAGE_CHANGE_COST:,}\n"
        f"Left: ฿{p.bounty:,}\n\n"
        f"View with `/crewinfo {crew['tag']}`"
    )


# ==================== DISBAND ====================
async def _disband_crew(crew):
    tag = crew["tag"]
    bank = int(crew.get("bank", 0) or 0)
    member_ids = list(crew.get("members", []))
    captain_id = crew["captain_id"]
    n = len(member_ids)

    if n > 0 and bank > 0:
        share = bank // n
        remainder = bank - (share * n)
        for uid in member_ids:
            if share > 0:
                get_player(uid).bounty += share
        if remainder > 0:
            get_player(captain_id).bounty += remainder

    ship_tier = _safe_ship_tier(crew)
    total_ship_spent = sum(SHIPS[t]["cost"] for t in range(1, ship_tier + 1))
    ship_refund = total_ship_spent // 2
    if ship_refund > 0:
        get_player(captain_id).bounty += ship_refund

    for uid in member_ids:
        CREW_STORE["player_crew"].pop(str(uid), None)
        CREW_IMAGE_LISTEN.pop(str(uid), None)

    CREW_STORE["crews"].pop(tag, None)
    save_crews()
    save_data()

    return {"bank_split": bank, "ship_refund": ship_refund}


# ==================== REGISTER ====================
def register_crew(app):

    # ==================== PHOTO LISTENER ====================
    @app.on_message(filters.photo & filters.private, group=-10)
    async def crew_image_listener(client, message):
        uid = str(message.from_user.id)

        from data_manager import GBANNED, TEMP_BANNED
        try:
            if int(uid) in GBANNED or int(uid) in TEMP_BANNED:
                message.continue_propagation()
                return
        except (ValueError, TypeError):
            pass

        listen = CREW_IMAGE_LISTEN.get(uid)
        if not listen:
            message.continue_propagation()
            return
        if time.time() > listen["expires"]:
            CREW_IMAGE_LISTEN.pop(uid, None)
            message.continue_propagation()
            return

        crew = get_crew(listen["tag"])
        if not crew:
            CREW_IMAGE_LISTEN.pop(uid, None)
            message.continue_propagation()
            return

        await _apply_crew_image(client, message, crew, message.photo.file_id)
        message.stop_propagation()

    # ==================== /crew ====================
    @app.on_message(filters.command("crew"))
    async def crew_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply(
                f"**CREW MENU**\n\n"
                f"You're not in a crew yet.\n\n"
                f"Create: `/crewcreate [name] | [TAG]`\n"
                f"Find: `/crewlist` or `/crewsearch [tag]`\n\n"
                f"Create cost: ฿{CREW_CREATE_COST:,}\n"
                f"Max members: {CREW_MAX_MEMBERS}\n\n"
                f"{BOT_NAME}"
            )
            return
        text = await _build_crew_overview(crew)
        kb = _build_crew_menu_kb(uid, crew)
        await _send_crew_media(message, crew, text, markup=kb)

    # ==================== /crewcreate ====================
    @app.on_message(filters.command("crewcreate"))
    async def crew_create_cmd(client, message):
        uid = message.from_user.id
        p = get_player(uid)

        if get_player_crew(uid):
            await message.reply("❌ You're already in a crew! Leave first with `/crewleave`.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2 or "|" not in args[1]:
            await message.reply(
                "**CREATE CREW**\n\n"
                "Format: `/crewcreate [name] | [TAG]`\n\n"
                "Example:\n"
                "`/crewcreate Straw Hat Pirates | STRAW`"
            )
            return

        parts = [x.strip() for x in args[1].split("|", 1)]
        name, tag = parts[0], parts[1].upper()

        if len(name) < 3 or len(name) > 30:
            await message.reply("❌ Name must be 3-30 characters.")
            return
        if not (CREW_TAG_MIN <= len(tag) <= CREW_TAG_MAX):
            await message.reply(f"❌ Tag must be {CREW_TAG_MIN}-{CREW_TAG_MAX} chars.")
            return
        if not tag.isalnum():
            await message.reply("❌ Tag must be alphanumeric.")
            return
        if tag in CREW_STORE["crews"]:
            await message.reply(f"❌ Tag **{tag}** already taken.")
            return
        if p.bounty < CREW_CREATE_COST:
            await message.reply(f"❌ Need ฿{CREW_CREATE_COST:,}! You have ฿{p.bounty:,}")
            return

        p.bounty -= CREW_CREATE_COST
        CREW_STORE["crews"][tag] = {
            "name": name,
            "tag": tag,
            "captain_id": uid,
            "officers": [],
            "members": [uid],
            "bank": 0,
            "created_at": time.time(),
            "level": 1,
            "wins": 0,
            "losses": 0,
            "image": None,
            "ship_tier": 1,
        }
        CREW_STORE["player_crew"][str(uid)] = tag
        save_crews()
        save_data()

        await message.reply(
            f"**CREW CREATED!**\n\n"
            f"{name}\n"
            f"Tag: `{tag}`\n"
            f"Captain: {p.name or uid}\n"
            f"Left: ฿{p.bounty:,}\n\n"
            f"Starting ship: Dinghy\n\n"
            f"{BOT_NAME}"
        )

    # ==================== /crewinfo ====================
    @app.on_message(filters.command("crewinfo"))
    async def crew_info_cmd(client, message):
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            crew = find_crew_by_tag_or_name(args[1])
        else:
            crew = get_player_crew(message.from_user.id)

        if not crew:
            await message.reply("❌ Crew not found.")
            return

        text = await _build_crew_overview(crew, detailed=True)
        await _send_crew_media(message, crew, text)

    # ==================== /crewsearch ====================
    @app.on_message(filters.command("crewsearch"))
    async def crew_search_cmd(client, message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/crewsearch [tag]`")
            return
        crew = find_crew_by_tag_or_name(args[1])
        if not crew:
            await message.reply(f"❌ No crew matching **{args[1]}**.")
            return
        text = await _build_crew_overview(crew, detailed=True)
        await _send_crew_media(message, crew, text)

    # ==================== /crewlist ====================
    @app.on_message(filters.command("crewlist"))
    async def crew_list_cmd(client, message):
        top = top_crews(15)
        if not top:
            await message.reply("📭 No crews yet. Create one with `/crewcreate`!")
            return

        for i, c in enumerate(top[:3], 1):
            medal = "👑" if i == 1 else "🥈" if i == 2 else "🥉"
            tb = crew_total_bounty(c)
            ship_emoji = SHIPS[_safe_ship_tier(c)]["emoji"]
            caption = (
                f"{medal} **#{i} — [{c['tag']}] {c['name']}**\n"
                f"฿{tb:,} • Members: {len(c['members'])} • "
                f"Lv.{crew_level(c)} • {ship_emoji}\n"
                f"Power: {crew_power(c)}"
            )
            await _send_crew_media(message, c, caption)

        if len(top) > 3:
            text = "──────────────────\n"
            for i, c in enumerate(top[3:], 4):
                text += (
                    f"{i}. **[{c['tag']}]** {c['name']} — "
                    f"฿{crew_total_bounty(c):,} • Members: {len(c['members'])}\n"
                )
            text += "──────────────────\n"
            text += "Use `/crewtop` for full leaderboard."
            await message.reply(text)

    # ==================== /crewinvite ====================
    @app.on_message(filters.command("crewinvite"))
    async def crew_invite_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not can_manage(uid, crew):
            await message.reply("❌ Only Captain/Officers can invite.")
            return
        if not message.reply_to_message:
            await message.reply("Reply to a user with `/crewinvite`.")
            return

        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name

        if get_player_crew(target_id):
            await message.reply(f"❌ **{target_name}** is already in a crew!")
            return
        if len(crew["members"]) >= CREW_MAX_MEMBERS:
            await message.reply(f"❌ Crew is full ({CREW_MAX_MEMBERS} max).")
            return

        tag = crew["tag"]
        CREW_STORE["pending_invites"].setdefault(str(target_id), {})[tag] = time.time()
        save_crews()

        await message.reply(f"✅ Invited **{target_name}** to **[{tag}]**!")
        try:
            await client.send_message(
                target_id,
                f"**CREW INVITE**\n\n"
                f"[{tag}] {crew['name']}\n\n"
                f"Join with `/crewaccept {tag}`\n"
                f"Expires in 24h"
            )
        except Exception:
            pass

    # ==================== /crewaccept ====================
    @app.on_message(filters.command("crewaccept"))
    async def crew_accept_cmd(client, message):
        uid = message.from_user.id
        if get_player_crew(uid):
            await message.reply("❌ You're already in a crew!")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/crewaccept [tag]`")
            return
        tag = args[1].strip().upper()

        invites = CREW_STORE["pending_invites"].get(str(uid), {})
        if tag not in invites:
            await message.reply(f"❌ No pending invite for **{tag}**.")
            return
        if time.time() - invites[tag] > INVITE_TTL:
            del invites[tag]
            save_crews()
            await message.reply("❌ Invite expired.")
            return

        crew = get_crew(tag)
        if not crew:
            await message.reply("❌ Crew no longer exists.")
            return
        if len(crew["members"]) >= CREW_MAX_MEMBERS:
            await message.reply("❌ Crew is full.")
            return

        crew["members"].append(uid)
        CREW_STORE["player_crew"][str(uid)] = tag
        del invites[tag]
        if not invites:
            CREW_STORE["pending_invites"].pop(str(uid), None)
        save_crews()

        await message.reply(f"✅ **Joined [{tag}] {crew['name']}!**")

    # ==================== /crewdecline ====================
    @app.on_message(filters.command("crewdecline"))
    async def crew_decline_cmd(client, message):
        uid = message.from_user.id
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/crewdecline [tag]`")
            return
        tag = args[1].strip().upper()
        invites = CREW_STORE["pending_invites"].get(str(uid), {})
        if tag in invites:
            del invites[tag]
            if not invites:
                CREW_STORE["pending_invites"].pop(str(uid), None)
            save_crews()
            await message.reply(f"✅ Declined **{tag}**.")
        else:
            await message.reply(f"❌ No invite from **{tag}**.")

    # ==================== /crewleave ====================
    @app.on_message(filters.command("crewleave"))
    async def crew_leave_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return

        if is_captain(uid, crew):
            if len(crew["members"]) > 1:
                await message.reply(
                    "❌ You're the Captain!\n\n"
                    "Transfer with `/crewtransfer` or disband with `/crewdisband`."
                )
                return
            CREW_IMAGE_LISTEN.pop(str(uid), None)
            await _disband_crew(crew)
            await message.reply("✅ Crew disbanded (sole member).")
            return

        CREW_IMAGE_LISTEN.pop(str(uid), None)
        crew["members"] = [m for m in crew["members"] if str(m) != str(uid)]
        if is_officer(uid, crew):
            crew["officers"] = [o for o in crew["officers"] if str(o) != str(uid)]
        CREW_STORE["player_crew"].pop(str(uid), None)
        save_crews()
        await message.reply(f"✅ Left **[{crew['tag']}] {crew['name']}**.")

    # ==================== /crewkick ====================
    @app.on_message(filters.command("crewkick"))
    async def crew_kick_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can kick.")
            return
        if not message.reply_to_message:
            await message.reply("Reply to a member with `/crewkick`.")
            return

        target_id = message.reply_to_message.from_user.id
        if str(target_id) == str(uid):
            await message.reply("❌ Can't kick yourself.")
            return
        if not is_member(target_id, crew):
            await message.reply("❌ Not a member.")
            return

        CREW_IMAGE_LISTEN.pop(str(target_id), None)
        crew["members"] = [m for m in crew["members"] if str(m) != str(target_id)]
        crew["officers"] = [o for o in crew["officers"] if str(o) != str(target_id)]
        CREW_STORE["player_crew"].pop(str(target_id), None)
        save_crews()

        await message.reply(f"✅ Kicked **{message.reply_to_message.from_user.first_name}**.")
        try:
            await client.send_message(
                target_id,
                f"⚠️ You were kicked from **[{crew['tag']}] {crew['name']}**."
            )
        except Exception:
            pass

    # ==================== /crewp ====================
    @app.on_message(filters.command("crewp"))
    async def crew_promote_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can promote.")
            return
        if not message.reply_to_message:
            await message.reply("Reply to a member with `/crewp`.")
            return

        target_id = message.reply_to_message.from_user.id
        if not is_member(target_id, crew):
            await message.reply("❌ Not a member.")
            return
        if is_officer(target_id, crew):
            await message.reply("Already an officer.")
            return

        crew["officers"].append(target_id)
        save_crews()
        await message.reply("✅ Promoted to **Officer**!")

    # ==================== /crewd ====================
    @app.on_message(filters.command("crewd"))
    async def crew_demote_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can demote.")
            return
        if not message.reply_to_message:
            await message.reply("Reply to an officer with `/crewd`.")
            return

        target_id = message.reply_to_message.from_user.id
        if not is_officer(target_id, crew):
            await message.reply("❌ Not an officer.")
            return

        crew["officers"] = [o for o in crew["officers"] if str(o) != str(target_id)]
        save_crews()
        await message.reply("✅ Demoted to **Member**.")

    # ==================== /crewtransfer ====================
    @app.on_message(filters.command("crewtransfer"))
    async def crew_transfer_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can transfer.")
            return
        if not message.reply_to_message:
            await message.reply("Reply to a member with `/crewtransfer`.")
            return

        target_id = message.reply_to_message.from_user.id
        if str(target_id) == str(uid):
            await message.reply("❌ Already Captain.")
            return
        if not is_member(target_id, crew):
            await message.reply("❌ Not a member.")
            return

        CREW_IMAGE_LISTEN.pop(str(uid), None)
        crew["captain_id"] = target_id
        if str(uid) not in [str(x) for x in crew["officers"]]:
            crew["officers"].append(uid)
        crew["officers"] = [o for o in crew["officers"] if str(o) != str(target_id)]
        save_crews()

        await message.reply("✅ Captaincy transferred.")

    # ==================== /crewdisband ====================
    @app.on_message(filters.command("crewdisband"))
    async def crew_disband_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can disband.")
            return

        bank = int(crew.get("bank", 0) or 0)
        n = len(crew["members"])
        share = bank // n if n else 0

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirm Disband", callback_data=f"crewdisband_{crew['tag']}")],
            [InlineKeyboardButton("Cancel", callback_data="noop")],
        ])
        await message.reply(
            f"**DISBAND [{crew['tag']}] {crew['name']}?**\n\n"
            f"Members: {n}\n"
            f"Bank: ฿{bank:,} (split ~฿{share:,} each)\n"
            f"Ship refund: 50% to Captain\n\n"
            f"Are you sure?",
            reply_markup=kb,
        )

    # ==================== /crewbank ====================
    @app.on_message(filters.command("crewbank"))
    async def crew_bank_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return

        args = message.text.split()
        if len(args) == 1:
            await message.reply(
                f"**CREW BANK**\n\n"
                f"Balance: ฿{int(crew.get('bank', 0) or 0):,}\n\n"
                f"`/crewbank deposit [amount]`\n"
                f"`/crewbank withdraw [amount]` *(Officer+)*"
            )
            return

        sub = args[1].lower()

        if sub == "deposit":
            if len(args) != 3:
                await message.reply("Usage: `/crewbank deposit [amount]`")
                return
            amount = parse_amount(args[2])
            if amount is None or amount <= 0:
                await message.reply("❌ Invalid amount!")
                return
            p = get_player(uid)
            if p.bounty < amount:
                await message.reply(f"❌ Need ฿{amount:,}, have ฿{p.bounty:,}")
                return
            p.bounty -= amount
            crew["bank"] = int(crew.get("bank", 0) or 0) + amount
            save_data()
            save_crews()
            await message.reply(
                f"✅ Deposited ฿{amount:,}!\n"
                f"Bank: ฿{crew['bank']:,}\n"
                f"Your bounty: ฿{p.bounty:,}"
            )
            return

        if sub == "withdraw":
            if not can_manage(uid, crew):
                await message.reply("❌ Only Captain/Officers can withdraw.")
                return
            if len(args) != 3:
                await message.reply("Usage: `/crewbank withdraw [amount]`")
                return
            amount = parse_amount(args[2])
            if amount is None or amount <= 0:
                await message.reply("❌ Invalid amount!")
                return
            bank = int(crew.get("bank", 0) or 0)
            if bank < amount:
                await message.reply(f"❌ Bank only has ฿{bank:,}")
                return
            p = get_player(uid)
            crew["bank"] = bank - amount
            p.bounty += amount
            save_data()
            save_crews()
            await message.reply(
                f"✅ Withdrew ฿{amount:,}!\n"
                f"Bank: ฿{crew['bank']:,}\n"
                f"Your bounty: ฿{p.bounty:,}"
            )
            return

        await message.reply("Usage: `/crewbank [deposit|withdraw] [amount]`")

    # ==================== /crewsetimage ====================
    @app.on_message(filters.command("crewsetimage"))
    async def crew_set_image_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can change the crew image.")
            return

        if message.reply_to_message and message.reply_to_message.photo:
            await _apply_crew_image(
                client, message, crew, message.reply_to_message.photo.file_id
            )
            return
        if message.reply_to_message and message.reply_to_message.document:
            doc = message.reply_to_message.document
            if doc.mime_type and doc.mime_type.startswith("image/"):
                await _apply_crew_image(client, message, crew, doc.file_id)
                return
            await message.reply("❌ That document isn't an image.")
            return

        CREW_IMAGE_LISTEN[str(uid)] = {
            "tag": crew["tag"],
            "expires": time.time() + 300,
        }
        await message.reply(
            f"**SET CREW IMAGE**\n\n"
            f"Crew: **[{crew['tag']}] {crew['name']}**\n"
            f"Cost: ฿{CREW_IMAGE_CHANGE_COST:,}\n\n"
            f"Send a **photo in DM** with me (not in this group).\n\n"
            f"5 minutes.\n"
            f"Cancel with `/crewremoveimage`."
        )

    # ==================== /crewremoveimage ====================
    @app.on_message(filters.command("crewremoveimage"))
    async def crew_remove_image_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ Only Captain can remove the image.")
            return

        CREW_IMAGE_LISTEN.pop(str(uid), None)

        if not crew.get("image"):
            await message.reply("No custom image is set.")
            return

        crew["image"] = None
        save_crews()
        await message.reply("✅ Custom image removed.")

    # ==================== /ship ====================
    @app.on_message(filters.command("ship"))
    async def ship_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return

        current_tier = _safe_ship_tier(crew)
        current_ship = SHIPS[current_tier]

        text = (
            f"**CREW SHIP**\n\n"
            f"Crew: **[{crew['tag']}] {crew['name']}**\n"
            f"{current_ship['emoji']} **Current:** {current_ship['name']} (Tier {current_tier})\n"
            f"Bank: ฿{int(crew.get('bank', 0) or 0):,}\n\n"
            f"**Current Bonuses:**\n"
            f"PVP: +{int(current_ship['pvp_damage_bonus'] * 100)}%\n"
            f"Daily: +{int(current_ship['daily_bonus'] * 100)}%\n"
            f"XP: +{int(current_ship['xp_bonus'] * 100)}%\n\n"
        )

        if current_tier < SHIP_MAX_TIER:
            nt = current_tier + 1
            ns = SHIPS[nt]
            text += (
                f"──────────────────\n"
                f"**NEXT:**\n"
                f"{ns['emoji']} **{ns['name']}** (Tier {nt})\n"
                f"฿{ns['cost']:,}\n"
                f"{ns['description']}\n\n"
                f"`/shipupgrade`"
            )
        else:
            text += "Maximum tier reached!"

        text += f"\n\n{BOT_NAME}"

        ship_img = SHIP_IMAGES.get(current_tier)
        if ship_img:
            try:
                await message.reply_photo(ship_img, caption=text)
                return
            except Exception:
                pass
        await message.reply(text)

    # ==================== /shipupgrade ====================
    @app.on_message(filters.command("shipupgrade"))
    async def ship_upgrade_cmd(client, message):
        uid = message.from_user.id
        crew = get_player_crew(uid)
        if not crew:
            await message.reply("❌ You're not in a crew!")
            return
        if not is_captain(uid, crew):
            await message.reply("❌ **Captain Only!** Only the Captain can upgrade the ship.")
            return

        current_tier = _safe_ship_tier(crew)
        if current_tier >= SHIP_MAX_TIER:
            await message.reply("✅ Already at max tier!")
            return

        next_tier = current_tier + 1
        next_ship = SHIPS[next_tier]
        cost = next_ship["cost"]
        bank = int(crew.get("bank", 0) or 0)

        if bank < cost:
            await message.reply(
                f"❌ **Not enough in crew bank!**\n\n"
                f"{next_ship['emoji']} **{next_ship['name']}**\n"
                f"Cost: ฿{cost:,}\n"
                f"Bank: ฿{bank:,}\n"
                f"Short: ฿{cost - bank:,}\n\n"
                f"Members deposit: `/crewbank deposit [amount]`"
            )
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"Confirm (฿{cost:,})",
                callback_data=f"shipupgrade_confirm_{crew['tag']}_{next_tier}",
            )],
            [InlineKeyboardButton("Cancel", callback_data="shipupgrade_cancel")],
        ])

        cur_ship = SHIPS[current_tier]
        await message.reply(
            f"**SHIP UPGRADE**\n\n"
            f"Crew: **[{crew['tag']}] {crew['name']}**\n\n"
            f"{cur_ship['emoji']} {cur_ship['name']}\n"
            f"      ⬇️\n"
            f"{next_ship['emoji']} **{next_ship['name']}**\n\n"
            f"Cost: ฿{cost:,}\n"
            f"Bank: ฿{bank:,}\n"
            f"After: ฿{bank - cost:,}\n\n"
            f"**New bonuses:**\n"
            f"+{int(next_ship['pvp_damage_bonus'] * 100)}% PVP\n"
            f"+{int(next_ship['daily_bonus'] * 100)}% daily\n"
            f"+{int(next_ship['xp_bonus'] * 100)}% XP\n\n"
            f"Confirm?",
            reply_markup=kb,
        )

    # ==================== /shiplist ====================
    @app.on_message(filters.command("shiplist"))
    async def shiplist_cmd(client, message):
        text = "**ALL SHIPS**\n──────────────────\n\n"
        for tier, ship in SHIPS.items():
            cost_line = f"฿{ship['cost']:,}" if ship["cost"] > 0 else "Free"
            text += (
                f"**Tier {tier}:** {ship['emoji']} **{ship['name']}**\n"
                f"   {cost_line}\n"
                f"   +{int(ship['pvp_damage_bonus'] * 100)}% PVP • "
                f"+{int(ship['daily_bonus'] * 100)}% daily • "
                f"+{int(ship['xp_bonus'] * 100)}% XP\n"
                f"   {ship['description']}\n\n"
            )
        text += "──────────────────\n"
        text += "Only **Captains** can upgrade."
        text += f"\n\n{BOT_NAME}"
        await message.reply(text)
