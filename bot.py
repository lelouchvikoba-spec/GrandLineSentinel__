# bot.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import random
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.types import (
    InlineQueryResultArticle, InlineQueryResultPhoto, InlineQueryResultCachedPhoto,
    InlineQueryResultVideo, InlineQueryResultCachedVideo,
    InputTextMessageContent, InlineKeyboardMarkup,
    InlineKeyboardButton, ChatPermissions,
)

from config import (
    API_ID, API_HASH, BOT_TOKEN, BOT_NAME, OWNER_ID, MAIN_GROUP_ID,
    UPDATE_CHANNEL_USERNAME, UPDATE_CHANNEL_ID, BOT_VERSION, TIMEZONE,
    STORAGE_CHANNEL_ID,
)
from data_manager import (
    load_data, save_data, user_data, normal_characters, mythical_characters, exalted_characters,
    active_challenges, message_count, pending_trades, GBANNED, TEMP_BANNED,
    ADMINS, bot_groups, save_bot_groups, banned_players_info,
    get_banned_player_info, check_temp_bans, get_player, get_rarity_emoji, get_character_rarities,
    get_world_boss_active, get_group_drop_count, create_json_backup,
)
from utils import check_cooldown, parse_amount, get_xp_needed, get_rank
from models import Player

# ==================== CORE MODULES ====================
from commands import register_commands
from games import register_games
from pvp import register_pvp, start_world_boss, end_world_boss
from shop import register_shop
from fishing import register_fishing
from giveaway import register_giveaway
from admin import register_admin
from callbacks import register_callbacks

# ==================== OPTIONAL NEW MODULES ====================
try:
    from haki_commands import register_haki
    HAKI_AVAILABLE = True
except ImportError:
    HAKI_AVAILABLE = False
    print("[bot] haki_commands.py not found — skipping")

try:
    from crew import register_crew, reload_crews
    CREW_AVAILABLE = True
except ImportError:
    CREW_AVAILABLE = False
    print("[bot] crew.py not found — skipping")

try:
    from inventory import register_inventory
    INVENTORY_AVAILABLE = True
except ImportError:
    INVENTORY_AVAILABLE = False
    print("[bot] inventory.py not found — skipping")

try:
    from update_notifier import notify_startup
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False
    print("[bot] update_notifier.py not found — skipping")


# ==================== INIT BOT ====================
app = Client("grandline_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# ==================== GROUP ADMIN GATE ====================
# The bot must be an administrator before it reacts to group messages.
# `/start` is deliberately allowed through so a player can register in a
# group even before an administrator promotes the bot.
_bot_group_admin_cache = {}
_BOT_GROUP_ADMIN_CACHE_SECONDS = 30


async def _bot_is_group_admin(client, chat_id):
    now = time.time()
    cached = _bot_group_admin_cache.get(chat_id)
    if cached and now - cached[0] < _BOT_GROUP_ADMIN_CACHE_SECONDS:
        return cached[1]

    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
        status = str(member.status).split(".")[-1].upper()
        is_admin = status in {"ADMINISTRATOR", "OWNER", "CREATOR"}
    except Exception as exc:
        # A failed membership lookup must fail closed for group gameplay.
        print(f"[group admin gate] {chat_id}: {exc}")
        is_admin = False

    _bot_group_admin_cache[chat_id] = (now, is_admin)
    return is_admin


@app.on_message(filters.group, group=-100)
async def require_group_admin(client, message):
    """Stop every group reaction unless the bot is an administrator.

    `/start` is passed to the registration handler as the one intentional
    exception. Private chats are not affected by this guard.
    """
    command = ""
    try:
        if message.command:
            command = str(message.command[0]).split("@", 1)[0].lstrip("/").lower()
        elif message.text:
            command = message.text.split(maxsplit=1)[0].split("@", 1)[0].lstrip("/").lower()
    except Exception:
        command = ""

    if command == "start":
        message.continue_propagation()
        return

    if command == "bgiveaway":
        # Let the owner giveaway handler report target-chat permission errors.
        message.continue_propagation()
        return
    if command == "setnextdrop":
        # This owner-only setting command does not require the bot to be an admin.
        message.continue_propagation()
        return

    if await _bot_is_group_admin(client, message.chat.id):
        message.continue_propagation()
    # No propagation here: all later group handlers stay silent.

# Register handlers
register_commands(app)
register_games(app)
register_pvp(app)
register_shop(app)
register_fishing(app)
register_giveaway(app)
register_admin(app)
register_callbacks(app)

if HAKI_AVAILABLE:
    register_haki(app)
if CREW_AVAILABLE:
    register_crew(app)
if INVENTORY_AVAILABLE:
    register_inventory(app)


# ==================== AUTO NAME UPDATE ====================
_last_name_save = {}
_reply_rewarded = set()
_save_task = None


def _request_action_save():
    """Debounce writes so the latest command action is persisted to users.json."""
    global _save_task
    if _save_task and not _save_task.done():
        _save_task.cancel()
    _save_task = asyncio.create_task(_delayed_action_save())


async def _delayed_action_save():
    try:
        await asyncio.sleep(0.75)
        save_data()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[auto-save] {e}")


@app.on_message(filters.all, group=-3)
async def auto_update_name(client, message):
    try:
        u = message.from_user
        if not u or u.is_bot:
            message.continue_propagation()
            return

        p = get_player(u.id, u)
        now = time.time()

        last = _last_name_save.get(u.id, 0)
        if now - last > 30:
            save_data()
            _last_name_save[u.id] = now
    except Exception:
        pass

    message.continue_propagation()


# ==================== POSITIVE REPLY REWARD ====================
@app.on_message(filters.text & filters.group, group=-2)
async def positive_reply_reward(client, message):
    """Reward the replied-to player for a short positive reaction once per message."""
    try:
        if not message.reply_to_message or not message.from_user:
            return
        if message.from_user.is_bot:
            return
        target_user = message.reply_to_message.from_user
        if not target_user or target_user.is_bot or target_user.id == message.from_user.id:
            return

        raw_text = (message.text or "").strip()
        if raw_text.startswith("/"):
            return
        text = raw_text.casefold()
        text = re.sub(r"[^a-z]+", "", text)
        if text not in {"gg", "good", "nice"}:
            return

        reward_key = (message.chat.id, message.reply_to_message.id, text)
        if reward_key in _reply_rewarded:
            return
        _reply_rewarded.add(reward_key)

        reward = random.randint(1_000, 2_500)
        target = get_player(target_user.id, user=target_user)
        target.bounty += reward
        save_data()
        await message.reply(
            f"👏 **Nice reply!** {target_user.first_name} receives **฿{reward:,}** bounty!"
        )
    except Exception as e:
        print(f"[reply reward] {e}")


@app.on_message(filters.all, group=100)
async def persist_after_action(client, message):
    """Persist profile mutations after command/game messages finish processing."""
    try:
        if message.from_user and not message.from_user.is_bot:
            _request_action_save()
    except Exception as e:
        print(f"[auto-save request] {e}")


@app.on_callback_query(group=100)
async def persist_after_callback(client, callback_query):
    """Persist profile mutations made by shop, game, and menu buttons."""
    try:
        if callback_query.from_user and not callback_query.from_user.is_bot:
            _request_action_save()
    except Exception as e:
        print(f"[callback auto-save request] {e}")


# ==================== FILE ID HELPERS ====================
@app.on_message(filters.photo & filters.private, group=1)
async def get_file_id(client, message):
    try:
        file_id = message.photo.file_id
        await message.reply(
            f"**File ID (PHOTO)**\n\n"
            f"**File ID:**\n<code>{file_id}</code>\n\n"
            f"**Info:**\n"
            f"Size: {message.photo.width}x{message.photo.height}\n"
            f"Bytes: {message.photo.file_size}\n\n"
            f"Use with `send_photo` / `reply_photo`.",
            quote=True,
        )
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


@app.on_message(filters.document & filters.private, group=1)
async def get_document_file_id(client, message):
    try:
        file_id = message.document.file_id
        await message.reply(
            f"**File ID (DOCUMENT)**\n\n"
            f"**File ID:**\n<code>{file_id}</code>\n\n"
            f"Name: {message.document.file_name}\n"
            f"Bytes: {message.document.file_size}\n\n"
            f"Use with `send_document` / `reply_document`.",
            quote=True,
        )
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


@app.on_message(filters.animation & filters.private, group=1)
async def get_animation_file_id(client, message):
    try:
        file_id = message.animation.file_id
        await message.reply(
            f"**File ID (ANIMATION)**\n\n"
            f"**File ID:**\n<code>{file_id}</code>\n\n"
            f"Name: {message.animation.file_name}\n"
            f"Bytes: {message.animation.file_size}\n"
            f"Duration: {message.animation.duration}s\n\n"
            f"Use with `send_animation` / `reply_animation`.",
            quote=True,
        )
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


# ==================== INLINE QUERY ====================
def _inline_image_for_char(char):
    """Return a stored image or recover it from the master character lists."""
    image = char.get("image")
    if isinstance(image, str) and image.strip():
        return image.strip()
    char_id = char.get("id")
    name = char.get("name")
    for master in normal_characters + mythical_characters + exalted_characters:
        if (char_id is not None and master.get("id") == char_id) or (
            name and master.get("name") == name
        ):
            return master.get("image")
    return None


def _inline_media_result(result_id, title, description, image, caption, media_type="photo"):
    """Build a cached or URL-backed inline photo/video result."""
    is_video = str(media_type).lower() == "video"
    if isinstance(image, str) and image.startswith(("http://", "https://")):
        if is_video:
            return InlineQueryResultVideo(
                id=result_id, video_url=image, mime_type="video/mp4",
                thumb_url=image, title=title, description=description,
                caption=caption,
            )
        return InlineQueryResultPhoto(
            id=result_id, photo_url=image, thumb_url=image,
            title=title, description=description, caption=caption,
        )
    if isinstance(image, str) and image.strip():
        if is_video:
            return InlineQueryResultCachedVideo(
                id=result_id, video_file_id=image.strip(), title=title,
                description=description, caption=caption,
            )
        return InlineQueryResultCachedPhoto(
            id=result_id, photo_file_id=image.strip(), title=title,
            description=description, caption=caption,
        )
    return None


@app.on_inline_query()
async def inline_character_search(client, inline_query):
    from data_manager import get_player as _get_player

    query = (inline_query.query or "").strip()
    parts_split = query.split(maxsplit=1)
    head_lc = (parts_split[0].lower() if parts_split else "")
    rest_q = (parts_split[1] if len(parts_split) > 1 else "").strip()
    try:
        offset_val = int(inline_query.offset or "0") if (inline_query.offset or "").isdigit() else 0
    except ValueError:
        offset_val = 0

    # ==================== "mychar" / "mychar.<uid>" PERSONAL ====================
    if head_lc == "mychar" or head_lc.startswith("mychar."):
        if head_lc == "mychar":
            owner_id_param = inline_query.from_user.id
        else:
            try:
                owner_id_param = int(head_lc.split(".", 1)[1])
            except (ValueError, IndexError):
                owner_id_param = inline_query.from_user.id

        player_m = _get_player(owner_id_param)
        if not player_m.captured_chars:
            await inline_query.answer([InlineQueryResultArticle(
                id="my_no_chars",
                title="mychar",
                description="No characters captured yet",
                input_message_content=InputTextMessageContent(
                    f"**{player_m.name or owner_id_param} has no captured characters!**"
                ),
            )], cache_time=5, is_personal=True)
            return

        seen_map = {}
        for ch in player_m.captured_chars:
            cid_local = ch.get("id")
            if cid_local in seen_map:
                seen_map[cid_local]["count"] += 1
                continue
            seen_map[cid_local] = {
                "id": cid_local, "name": ch.get("name", "Unknown"),
                "image": _inline_image_for_char(ch), "rarity": ch.get("rarity", "NORMAL"),
                "media_type": ch.get("media_type", "photo"),
                "count": 1,
            }
        coll = list(seen_map.values())
        if rest_q:
            coll = [c for c in coll if rest_q.lower() in c["name"].lower()]
        rarity_order = {"EXALTED": 0, "MYTHICAL": 1, "NORMAL": 2}
        coll.sort(key=lambda c: (rarity_order.get(c["rarity"], 3), c["name"].lower()))

        page_local = coll[offset_val: offset_val + 50]
        next_off_local = str(offset_val + 50) if (offset_val + 50) < len(coll) else ""

        results_local = []
        for idx, char in enumerate(page_local):
            name = char["name"]; img = _inline_image_for_char(char)
            rarity = char.get("rarity", "NORMAL")
            emoji = get_rarity_emoji(rarity)
            text = (
                f"{emoji} **{name}**\n"
                f"(RARITY: {rarity})\n\n"
                f"Owner: {player_m.name or owner_id_param}\n"
                f"Character ID: {char['id']}\n"
                f"Captured: {char['count']}x\n\n"
                f"@Grand_Line_Sentinel_bot"
            )
            rid_local = f"my_{owner_id_param}_{char['id']}_{offset_val + idx}"
            media_result = _inline_media_result(
                rid_local, f"{emoji} {name}", f"Captured {char['count']}x",
                img, text, char.get("media_type", "photo"),
            )
            if media_result:
                results_local.append(media_result)
        if not results_local:
            results_local.append(InlineQueryResultArticle(
                id="my_no_match", title="mychar",
                description=f"No '{rest_q}' found",
                input_message_content=InputTextMessageContent(
                    f"**No '{rest_q}' found in your collection!**"
                ),
            ))
        await inline_query.answer(
            results_local, cache_time=5, is_personal=True, next_offset=next_off_local,
        )
        return

    # Player-specific mode (legacy "character.<uid> <name>")
    if query.startswith("character."):
        rest = query[len("character."):]
        parts = rest.split(" ", 1)
        try:
            player_id = int(parts[0])
        except (ValueError, IndexError):
            await inline_query.answer([], cache_time=5)
            return
        search_term = parts[1] if len(parts) > 1 else ""

        player = _get_player(player_id)
        if not player.captured_chars:
            await inline_query.answer([InlineQueryResultArticle(
                id="no_chars",
                title=f"character.{player_id}",
                description="No characters captured yet",
                input_message_content=InputTextMessageContent(
                    f"**{player.name or player_id} has no captured characters!**"
                ),
            )], cache_time=5)
            return

        matches = []
        for char in player.captured_chars:
            name = char.get("name", "")
            if not search_term or search_term.lower() in name.lower():
                matches.append(char)
        if not matches:
            await inline_query.answer([InlineQueryResultArticle(
                id="no_match",
                title=f"character.{player_id}",
                description=f"No '{search_term}' found",
                input_message_content=InputTextMessageContent(
                    f"**No '{search_term}' found in collection!**"
                ),
            )], cache_time=5)
            return

        results = []
        seen = set()
        for char in matches[:50]:
            name = char.get("name", "Unknown")
            if name in seen:
                continue
            seen.add(name)
            count = sum(1 for c in player.captured_chars if c.get("name") == name)
            img = _inline_image_for_char(char)
            rarity = char.get("rarity", "NORMAL")
            emoji = get_rarity_emoji(rarity)
            text = (
                f"{emoji} **{name}**\n"
                f"(RARITY: {rarity})\n\n"
                f"Owner: {player.name or player_id}\n"
                f"Character ID: {char.get('id')}\n"
                f"Captured: {count}x\n\n"
                f"@Grand_Line_Sentinel_bot"
            )
            media_result = _inline_media_result(
                f"p_{player_id}_{name}", f"{emoji} {name}",
                f"Captured {count}x", img, text, char.get("media_type", "photo"),
            )
            if media_result:
                results.append(media_result)
        await inline_query.answer(results, cache_time=5)
        return

    # Global mode — paginated via next_offset, scroll until last character
    all_chars = [{"char": c, "type": c.get("rarity", "NORMAL")} for c in normal_characters]
    all_chars += [{"char": c, "type": c.get("rarity", "MYTHICAL")} for c in mythical_characters]
    all_chars += [{"char": c, "type": c.get("rarity", "EXALTED")} for c in exalted_characters]
    if query:
        all_chars = [
            x for x in all_chars
            if query.lower() in x["char"].get("name", "").lower()
        ]
    all_chars.sort(key=lambda x: (
        get_character_rarities().index(x["type"]) if x["type"] in get_character_rarities() else 999,
        x["char"].get("name", "").lower(),
    ))

    page_size = 50
    page = all_chars[offset_val: offset_val + page_size]
    next_off = str(offset_val + page_size) if (offset_val + page_size) < len(all_chars) else ""

    results = []
    capturer_cache = {}
    for idx, item in enumerate(page):
        char = item["char"]; ctype = item["type"]
        name = char.get("name", "Unknown"); img = _inline_image_for_char(char); cid = char.get("id")

        if name in capturer_cache:
            total, top = capturer_cache[name]
        else:
            total = 0; capturers = {}
            for p in user_data.values():
                for c in p.captured_chars:
                    if c.get("name") == name:
                        total += 1
                        capturers.setdefault(p.user_id, {"name": p.name, "count": 0})
                        capturers[p.user_id]["count"] += 1
            top = sorted(capturers.values(), key=lambda x: x["count"], reverse=True)[:10]
            capturer_cache[name] = (total, top)
        lines = [f"{i}. {c['name'] or 'User'} - {c['count']}x" for i, c in enumerate(top, 1)]
        cap_text = "\n".join(lines) if lines else "No captures yet."

        emoji = get_rarity_emoji(ctype)
        text = (
            f"{emoji} **{name}**\n"
            f"(RARITY: {ctype})\n"
            f"Character ID: {cid}\n\n"
            f"GLOBAL CAPTURES: {total}\n\n"
            f"TOP CAPTURERS:\n{cap_text}\n\n"
            f"@Grand_Line_Sentinel_bot"
        )
        rid = f"g_{ctype}_{cid}_{offset_val + idx}"
        media_result = _inline_media_result(
            rid, f"{emoji} {name}", f"Global: {total} captures", img,
            text, char.get("media_type", "photo"),
        )
        if media_result:
            results.append(media_result)

    if not results:
        results.append(InlineQueryResultArticle(
            id="no_chars", title="No Characters Found",
            description=f"Search: '{query}'",
            input_message_content=InputTextMessageContent(
                f"**No characters found**\n\n"
                f"Normal: {len(normal_characters)}\n"
                f"Mythical: {len(mythical_characters)}\n"
                f"Exalted: {len(exalted_characters)}"
            ),
        ))

    await inline_query.answer(
        results,
        cache_time=5,
        is_personal=bool(query),
        next_offset=next_off,
    )


# ==================== SCHEDULERS ====================
async def world_boss_scheduler():
    while True:
        try:
            now = datetime.now(TIMEZONE)
            target = now.replace(hour=22, minute=0, second=0, microsecond=0)
            if now.hour >= 22:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            await asyncio.sleep(max(1, wait))
            try:
                await start_world_boss(app, MAIN_GROUP_ID)
            except Exception as e:
                print(f"[world_boss] start failed: {e}")
            await asyncio.sleep(1800)
            if get_world_boss_active():
                try:
                    await end_world_boss(app, MAIN_GROUP_ID)
                except Exception as e:
                    print(f"[world_boss] end failed: {e}")
        except Exception as e:
            print(f"[world_boss] scheduler error: {e}")
            await asyncio.sleep(60)


async def despawn_checker():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired = []
        for chat_id, ch in list(active_challenges.items()):
            if now - ch.get("spawn_time", 0) >= 300:
                expired.append(chat_id)
        for chat_id in expired:
            try:
                char = active_challenges[chat_id].get("char", {})
                name = char.get("name", "Character")
                await app.send_message(chat_id, f"**{name}** has left the island!")
            except Exception:
                pass
            active_challenges.pop(chat_id, None)


async def automatic_backup_scheduler():
    """Create a full JSON snapshot every six hours while the bot is running."""
    interval = 6 * 60 * 60
    while True:
        await asyncio.sleep(interval)
        try:
            save_data()
            result = create_json_backup("automatic")
            print(
                f"[auto-backup] {result['timestamp']}: "
                f"{len(result['saved'])} saved, {len(result['failed'])} failed"
            )
        except Exception as e:
            print(f"[auto-backup] failed: {e}")


# ==================== MESSAGE COUNTER ====================
SPAM_LIMIT = 25
SPAM_WINDOW_SECONDS = 60
SPAM_MUTE_SECONDS = 10 * 60
_spam_message_times = defaultdict(deque)
_spam_muted_until = {}


@app.on_message(filters.group, group=-1)
async def message_counter(client, message):
    if message.from_user and not message.from_user.is_bot:
        gid = message.chat.id
        uid = message.from_user.id
        now = time.time()
        # Persist every group we ever receive a message from, so /groups can
        # list all of them (the bot API cannot enumerate chats on its own).
        if gid not in bot_groups:
            bot_groups.add(gid)
            try:
                save_bot_groups()
            except Exception:
                pass

        spam_key = (gid, uid)
        muted_until = _spam_muted_until.get(spam_key, 0)
        if muted_until > now:
            # The restriction can fail (for example, if the bot lacks the
            # restrict-members right); in either case never count these messages.
            try:
                await message.delete()
            except Exception:
                pass
            return
        if muted_until:
            _spam_muted_until.pop(spam_key, None)
            _spam_message_times.pop(spam_key, None)

        timestamps = _spam_message_times[spam_key]
        timestamps.append(now)
        while timestamps and now - timestamps[0] > SPAM_WINDOW_SECONDS:
            timestamps.popleft()
        if len(timestamps) >= SPAM_LIMIT:
            _spam_muted_until[spam_key] = now + SPAM_MUTE_SECONDS
            timestamps.clear()
            try:
                await client.restrict_chat_member(
                    gid,
                    uid,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=datetime.fromtimestamp(now + SPAM_MUTE_SECONDS, tz=timezone.utc),
                )
            except Exception as e:
                print(f"[spam mute] could not restrict {uid} in {gid}: {e}")
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await client.send_message(
                    gid,
                    f"🔇 {message.from_user.mention} was muted for 10 minutes "
                    f"after sending {SPAM_LIMIT} messages within {SPAM_WINDOW_SECONDS} seconds. "
                    "Their messages will not count toward character drops during the mute.",
                )
            except Exception:
                pass
            return

        command = (message.text or "").split(maxsplit=1)[0].split("@", 1)[0].lstrip("/").lower()
        if command != "setnextdrop":
            message_count[gid] = message_count.get(gid, 0) + 1
            if message_count[gid] >= get_group_drop_count(gid):
                message_count[gid] = 0
                if gid not in active_challenges:
                    from admin import spawn_character
                    try:
                        await spawn_character(app, gid, message.chat.title or "Group")
                    except Exception as e:
                        print(f"[spawn] failed: {e}")
    message.continue_propagation()


# ==================== BAN CHECK ====================
_last_temp_ban_check = 0
_banned_reply_cache = {}


@app.on_message(filters.all, group=-20)
async def check_banned(client, message):
    global _last_temp_ban_check
    if not message.from_user:
        return
    uid = message.from_user.id

    cmd = ""
    if message.text:
        cmd = message.text.split()[0].split("@")[0]
    if cmd == "/info":
        message.continue_propagation()
        return

    now = time.time()
    if now - _last_temp_ban_check > 30:
        check_temp_bans()
        _last_temp_ban_check = now

    if uid in GBANNED:
        if _banned_reply_cache.get(uid, 0) > now - 60:
            message.stop_propagation()
            return
        _banned_reply_cache[uid] = now

        info = get_banned_player_info(uid)
        try:
            await message.reply(
                f"**YOU ARE GLOBALLY BANNED!**\n\n"
                f"Reason: {info.get('reason', 'Unknown')}\n"
                f"By: {info.get('banned_by_name', 'Unknown')}\n"
                f"Date: {info.get('banned_at_str', 'Unknown')}\n\n"
                f"You can only use /info."
            )
        except Exception:
            pass
        message.stop_propagation()
        return

    if uid in TEMP_BANNED:
        t = TEMP_BANNED[uid]
        if t > now:
            remaining = int(t - now)
            h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
            if _banned_reply_cache.get(uid, 0) > now - 30:
                message.stop_propagation()
                return
            _banned_reply_cache[uid] = now
            try:
                await message.reply(
                    f"**YOU ARE TEMPORARILY BANNED!**\n\n"
                    f"Time left: **{h}h {m}m {s}s**"
                )
            except Exception:
                pass
            message.stop_propagation()
            return
        else:
            del TEMP_BANNED[uid]
            from data_manager import save_temp_banned
            save_temp_banned()

    message.continue_propagation()


# ==================== GROUP TRACKING ====================
@app.on_chat_member_updated()
async def track_groups(client, update):
    try:
        if update.new_chat_member and update.new_chat_member.user.id == client.me.id:
            status = update.new_chat_member.status
            if status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
                bot_groups.add(update.chat.id)
                save_bot_groups()
                print(f"[groups] Bot added: {update.chat.id} — {update.chat.title}")

        if update.old_chat_member and update.old_chat_member.user.id == client.me.id:
            old_status = update.old_chat_member.status
            if old_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                if update.chat.id in bot_groups:
                    bot_groups.discard(update.chat.id)
                    save_bot_groups()
                    print(f"[groups] Bot removed: {update.chat.id}")
    except Exception as e:
        print(f"[track_groups] {e}")


@app.on_message(filters.group & filters.new_chat_members)
async def on_bot_added(client, message):
    try:
        for member in message.new_chat_members:
            if member.id == client.me.id:
                gid = message.chat.id
                if gid not in bot_groups:
                    bot_groups.add(gid)
                    save_bot_groups()
                    print(f"[groups] Bot added via message: {gid}")
                    await message.reply(
                        "**Thanks for adding me!**\n\nUse `/help` to see commands!"
                    )
                break
    except Exception as e:
        print(f"[on_bot_added] {e}")


# ==================== MAIN ====================
async def _post_start(app):
    """Runs inside the client's event loop after app.start()."""

    # ============ CHANNEL STORAGE ============
    if STORAGE_CHANNEL_ID:
        try:
            from channel_storage import sync_all_from_channel
            from data_manager import set_channel_client

            set_channel_client(app)
            await asyncio.sleep(2)

            print("[ChannelStorage] Syncing from Telegram...")
            await sync_all_from_channel(app)

            load_data()
            if CREW_AVAILABLE:
                try:
                    reload_crews()
                except Exception as e:
                    print(f"[crew] reload after sync failed: {e}")

            print("[ChannelStorage] Ready ✅")
        except Exception as e:
            print(f"[ChannelStorage] Sync failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("[ChannelStorage] STORAGE_CHANNEL_ID not set — skipping")

    # ============ STARTUP NOTIFICATION ============
    if NOTIFIER_AVAILABLE and UPDATE_CHANNEL_ID:
        try:
            await notify_startup(app, BOT_NAME, BOT_VERSION, UPDATE_CHANNEL_ID)
        except Exception as e:
            print(f"[startup notifier] {e}")

    # ============ BACKGROUND TASKS ============
    asyncio.create_task(world_boss_scheduler())
    asyncio.create_task(despawn_checker())
    asyncio.create_task(automatic_backup_scheduler())


if __name__ == "__main__":
    print("=" * 50)
    print("GRAND LINE SENTINEL BOT")
    print("=" * 50)
    print(f"{BOT_NAME} v{BOT_VERSION} is running...")
    print("=" * 50)

    load_data()

    if CREW_AVAILABLE:
        try:
            reload_crews()
        except Exception as e:
            print(f"[crew] reload failed: {e}")

    # 1. Start client
    app.start()
    print("[DEBUG] Bot started. Listening...")

    # 2. Schedule post-start tasks INSIDE the client's loop
    app.loop.create_task(_post_start(app))

    # 3. Keep alive
    from pyrogram import idle
    idle()

    # 4. Cleanup
    app.stop()
