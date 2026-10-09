# giveaway.py
import asyncio
import random
import re
import time
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    BOT_NAME, MAIN_GROUP_ID, MAIN_GROUP_LINK, UPDATE_CHANNEL_LINK,
    UPDATE_CHANNEL_USERNAME, UPDATE_CHANNEL_ID, OWNER_ID,
    GIVEAWAY_DM_MIN_PRIZE,
)
from data_manager import (
    get_player, save_data, active_giveaways, user_data,
    get_global_giveaway, set_global_giveaway, clear_global_giveaway,
    get_bot_groups, is_admin_or_owner, normal_characters, mythical_characters,
    exalted_characters, get_character_rarities, get_character_by_id,
    get_rarity_emoji,
)
from utils import parse_amount
from update_notifier import notify_giveaway_started


def _giveaway_key(chat_id, msg_id):
    return f"{chat_id}_{msg_id}"


def _giveaway_prize_label(giveaway):
    if giveaway.get("prize_type") == "character":
        return giveaway.get("prize_description", "One random character")
    return f"฿{giveaway.get('total_prize', 0):,}"


async def _blink_reply(message, text, seconds=5):
    """Send a brief command response and remove it after a short display."""
    try:
        sent = await message.reply(text)
    except Exception as e:
        print(f"[giveaway blink reply] {e}")
        return None

    async def delete_later():
        await asyncio.sleep(seconds)
        try:
            await sent.delete()
        except Exception:
            pass

    asyncio.create_task(delete_later())
    return sent


def calculate_tiered_prizes(total_prize, winner_count):
    """
    Distribution always adds up to 100% of total_prize.
    """
    prizes = {}
    if winner_count <= 0:
        return prizes

    if winner_count == 1:
        prizes[1] = total_prize
    elif winner_count == 2:
        prizes[1] = int(total_prize * 0.60)
        prizes[2] = total_prize - prizes[1]
    elif winner_count == 3:
        prizes[1] = int(total_prize * 0.50)
        prizes[2] = int(total_prize * 0.30)
        prizes[3] = total_prize - prizes[1] - prizes[2]
    else:
        prizes[1] = int(total_prize * 0.50)
        prizes[2] = int(total_prize * 0.20)
        prizes[3] = int(total_prize * 0.10)
        remaining = total_prize - prizes[1] - prizes[2] - prizes[3]
        remaining_winners = winner_count - 3
        per_winner = remaining // remaining_winners
        for i in range(4, winner_count + 1):
            prizes[i] = per_winner
        given = sum(prizes.values())
        leftover = total_prize - given
        if leftover > 0 and 4 in prizes:
            prizes[4] += leftover
    return prizes


def register_giveaway(app):

    @app.on_message(filters.command(["charitygiveaway", "chargiveaway"]))
    async def start_character_giveaway(client, message):
        if not message.from_user or message.from_user.id != OWNER_ID:
            await _blink_reply(message, "⛔ Owner only.")
            return
        pieces = (message.text or "").split(maxsplit=1)
        target_chat_id = message.chat.id
        target_chat = message.chat
        if len(pieces) < 2:
            await _blink_reply(
                message,
                "**CHARACTER GIVEAWAY**\n\n"
                "Format: `/charitygiveaway [rarity name] [players] [duration]`\n"
                "Example: `/charitygiveaway Mythical 3 10m`\n"
                "From private chat, include the target group ID first: `/charitygiveaway -1001234567890 Mythical 3 10m`\n"
                "Each selected player gets one random character from that rarity.\n"
                "Players default to 1; duration defaults to 10m. Duration: `30s`, `5m`, `1h`, or `1d`."
            )
            return

        tokens = pieces[1].strip().split()
        if message.chat.id > 0:
            if not tokens:
                await _blink_reply(message, "Include the target group ID before the rarity when using this command in private chat.")
                return
            try:
                target_chat_id = int(tokens.pop(0))
            except ValueError:
                await _blink_reply(message, "❌ In private chat, start with the target group ID, e.g. `/charitygiveaway -1001234567890 Mythical 3 10m`.")
                return
            if target_chat_id >= 0:
                await _blink_reply(message, "❌ The target must be a group or supergroup ID (usually starts with `-100`).")
                return
            try:
                target_chat = await client.get_chat(target_chat_id)
            except Exception as exc:
                print(f"[character giveaway target] {target_chat_id}: {exc}")
                await _blink_reply(message, "❌ I can’t access that group. Check the group ID and make sure the bot is an administrator there.")
                return
        if not tokens:
            await _blink_reply(message, "Usage: `/charitygiveaway [rarity name] [players] [duration]`")
            return
        duration_text = "10m"
        if tokens and re.fullmatch(r"\d+[smhd]", tokens[-1].lower()):
            duration_text = tokens.pop().lower()
        winner_count = 1
        if tokens and re.fullmatch(r"\d+", tokens[-1]):
            winner_count = int(tokens.pop())
        if not tokens:
            await _blink_reply(message, "Usage: `/charitygiveaway [rarity name] [players] [duration]`")
            return
        if not 1 <= winner_count <= 300:
            await _blink_reply(message, "❌ Player count must be between 1 and 300.")
            return

        rarity_text = " ".join(tokens)
        rarity = " ".join(rarity_text.strip().upper().split())
        if rarity not in get_character_rarities():
            await _blink_reply(message, "❌ Rarity not found. Check available rarities with `/rarities`.")
            return

        rarity_lists = (
            (normal_characters, "NORMAL"),
            (mythical_characters, "MYTHICAL"),
            (exalted_characters, "EXALTED"),
        )
        pool_by_id = {}
        for characters, default_rarity in rarity_lists:
            for character in characters:
                char_id = character.get("id")
                if char_id is None:
                    continue
                if str(character.get("rarity", default_rarity)).strip().upper() == rarity:
                    pool_by_id[str(char_id)] = character
        pool = list(pool_by_id.values())
        if not pool:
            await _blink_reply(message, f"❌ No characters are currently assigned to **{rarity}**.")
            return

        match = re.fullmatch(r"(\d+)([smhd])", duration_text)
        if not match:
            await _blink_reply(message, "❌ Invalid duration. Use `30s`, `5m`, `1h`, or `1d`.")
            return
        amount, unit = int(match.group(1)), match.group(2)
        duration = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        if duration < 10:
            await _blink_reply(message, "❌ Minimum giveaway duration is 10 seconds.")
            return

        prize_description = f"{winner_count} player(s) — one random {rarity} character each"
        time_text = f"{amount}{unit}"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Giveaway", callback_data="join_tgiveaway")],
            [InlineKeyboardButton("Participants", callback_data="view_tparticipants")],
        ])
        announcement = (
            f"🎉 **CHARACTER GIVEAWAY!** 🎉\n\n"
            f"Prize: {get_rarity_emoji(rarity)} one random **{rarity}** character per winner\n"
            f"Winners: **{winner_count} players**\n"
            f"Ends in: {time_text}\n\nClick below to join!"
        )
        try:
            if target_chat_id == message.chat.id:
                sent = await message.reply(announcement, reply_markup=markup)
            else:
                sent = await client.send_message(target_chat_id, announcement, reply_markup=markup)
        except Exception as exc:
            print(f"[character giveaway send] {target_chat_id}: {exc}")
            await _blink_reply(message, "❌ I couldn’t post the giveaway there. Make sure I’m an administrator in the target group and can send messages.")
            return
        key = _giveaway_key(target_chat_id, sent.id)
        active_giveaways[key] = {
            "chat_id": target_chat_id,
            "message_id": sent.id,
            "total_prize": 0,
            "description": f"Character giveaway: {winner_count} {rarity} winner(s)",
            "prize_description": prize_description,
            "prize_type": "character",
            "rarity": rarity,
            "character_ids": [character.get("id") for character in pool],
            "end_time": time.time() + duration,
            "participants": [],
            "winner_count": winner_count,
            "prizes": {},
            "started_by": message.from_user.id,
            "is_tiered": True,
            "duration": duration,
            "chat_title": getattr(target_chat, "title", None) or "Group",
        }
        asyncio.create_task(end_tiered_giveaway_task(app, key, duration))
        await _blink_reply(message, f"✅ Character giveaway started in {getattr(target_chat, 'title', None) or 'the selected group'} for {winner_count} winner(s).")

    # ==================== /tgiveaway ====================
    @app.on_message(filters.command("tgiveaway") & filters.group)
    async def start_tiered_giveaway(client, message):
        if not is_admin_or_owner(message.from_user.id):
            await message.reply("⛔ You are not allowed to use this command.")
            return

        args = message.text.split(maxsplit=5)
        if len(args) < 4:
            await message.reply(
                "**TIERED GIVEAWAY**\n\n"
                "Format:\n"
                "`/tgiveaway [time] [amount] [players] [reason]`\n\n"
                "Example:\n"
                "`/tgiveaway 10m 10000000 10 Grand Prize`\n\n"
                "Time: `30s`, `5m`, `1h`, `1d`\n"
                "Players: 1-300"
            )
            return

        time_str = args[1].lower()
        total_prize = parse_amount(args[2])
        try:
            winner_count = int(args[3])
        except ValueError:
            await message.reply("❌ Invalid player count!")
            return
        reason = args[4] if len(args) > 4 else "Tiered Giveaway!"

        if total_prize is None or total_prize <= 0:
            await message.reply("❌ Invalid prize amount!")
            return
        winner_count = max(1, min(300, winner_count))

        time_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit = time_str[-1] if time_str else ""
        if unit not in time_map:
            await message.reply("❌ Invalid time format!")
            return
        try:
            duration = int(time_str[:-1]) * time_map[unit]
        except ValueError:
            await message.reply("❌ Invalid time value!")
            return
        if duration < 10:
            await message.reply("❌ Minimum 10 seconds!")
            return

        end_time = time.time() + duration
        prizes = calculate_tiered_prizes(total_prize, winner_count)

        prize_lines = ["**PRIZE DISTRIBUTION**\n"]
        for pos in (1, 2, 3):
            if pos in prizes:
                emoji = {1: "🥇", 2: "🥈", 3: "🥉"}[pos]
                suffix = {1: "1st", 2: "2nd", 3: "3rd"}[pos]
                prize_lines.append(f"{emoji} **{suffix}:** ฿{prizes[pos]:,}")
        if winner_count > 3 and 4 in prizes:
            prize_lines.append(f"🎖️ **4th-{winner_count}th:** ~฿{prizes[4]:,} each")
        prize_text = "\n".join(prize_lines)

        unit_names = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        n = int(time_str[:-1])
        time_text = f"{n} {unit_names[unit]}"

        giveaway_text = (
            f"🎉 **TIERED GIVEAWAY!** 🎉\n\n"
            f"Total Prize: ฿{total_prize:,}\n"
            f"Reason: {reason}\n"
            f"Winners: {winner_count}\n"
            f"Ends in: {time_text}\n\n"
            f"{prize_text}\n\n"
            f"Click below to join!"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Giveaway", callback_data="join_tgiveaway")],
            [InlineKeyboardButton("Participants", callback_data="view_tparticipants")],
        ])

        sent = await message.reply(giveaway_text, reply_markup=kb)
        key = _giveaway_key(message.chat.id, sent.id)

        active_giveaways[key] = {
            "chat_id": message.chat.id,
            "message_id": sent.id,
            "total_prize": total_prize,
            "description": reason,
            "end_time": end_time,
            "participants": [],
            "winner_count": winner_count,
            "prizes": prizes,
            "started_by": message.from_user.id,
            "is_tiered": True,
            "duration": duration,
            "chat_title": message.chat.title or "Group",
        }

        asyncio.create_task(
            end_tiered_giveaway_task(app, key, duration)
        )

        asyncio.create_task(notify_giveaway_started(
            app=client,
            giveaway_type="group",
            total_prize=total_prize,
            winner_count=winner_count,
            reason=f"{reason} (in {message.chat.title or 'a group'})",
            time_text=time_text,
            duration_text=time_text,
            channel_id=UPDATE_CHANNEL_ID,
            owner_id=OWNER_ID,
            user_data=user_data,
            main_group_link=MAIN_GROUP_LINK,
            updates_channel_link=UPDATE_CHANNEL_LINK,
            bot_name=BOT_NAME,
            dm_min_prize=GIVEAWAY_DM_MIN_PRIZE,
        ))

    # ==================== /bgiveaway ====================
    @app.on_message(filters.command("bgiveaway"))
    async def start_owner_bounty_giveaway(client, message):
        """Owner starts a bounty giveaway in this group or a selected group."""
        if not message.from_user or message.from_user.id != OWNER_ID:
            await _blink_reply(message, "⛔ Owner only.")
            return

        args = (message.text or "").split(maxsplit=5)
        tokens = args[1:]
        target_chat = message.chat
        target_chat_id = message.chat.id
        needs_group_id = message.chat.id > 0
        has_target_id = bool(tokens and re.fullmatch(r"-\d+", tokens[0]))
        if needs_group_id or has_target_id:
            if not tokens:
                await message.reply(
                    "Usage in private chat: `/bgiveaway [group_id] [time] [total bounty] [winners] [reason]`"
                )
                return
            try:
                target_chat_id = int(tokens.pop(0))
            except ValueError:
                await message.reply("❌ In private chat, put the target group ID first.")
                return
            if target_chat_id >= 0:
                await message.reply("❌ The target must be a group/supergroup ID (usually starts with `-100`).")
                return
            try:
                target_chat = await client.get_chat(target_chat_id)
            except Exception as exc:
                print(f"[bounty giveaway target] {target_chat_id}: {exc}")
                await message.reply("❌ I can’t access that group. Check the ID and make sure the bot is in the group and can post.")
                return

        if len(tokens) < 3:
            await message.reply(
                "**BOUNTY GIVEAWAY**\n\n"
                "In a group: `/bgiveaway [time] [total bounty] [winners] [reason]`\n"
                "From private chat: `/bgiveaway [group_id] [time] [total bounty] [winners] [reason]`\n"
                "Example: `/bgiveaway 10m 5M 3 Celebration`\n"
                "Time: `30s`, `5m`, `1h`, or `1d`; winners: 1–300."
            )
            return

        time_text, amount_text, winner_text = tokens[:3]
        reason = " ".join(tokens[3:]) or "Owner Bounty Giveaway"
        total_prize = parse_amount(amount_text)
        if total_prize is None:
            shorthand = re.fullmatch(r"(\d+(?:\.\d+)?)([kmbt])", amount_text.strip(), re.IGNORECASE)
            if shorthand:
                multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "t": 1_000_000_000_000}
                total_prize = int(float(shorthand.group(1)) * multiplier[shorthand.group(2).lower()])
        try:
            winner_count = int(winner_text)
        except ValueError:
            winner_count = 0
        if total_prize is None or total_prize <= 0:
            await message.reply("❌ Prize must be a positive bounty amount.")
            return
        if not 1 <= winner_count <= 300:
            await message.reply("❌ Winner count must be between 1 and 300.")
            return
        match = re.fullmatch(r"(\d+)([smhd])", time_text.lower())
        if not match:
            await message.reply("❌ Invalid duration. Use `30s`, `5m`, `1h`, or `1d`.")
            return
        value, unit = int(match.group(1)), match.group(2)
        duration = value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        if duration < 10:
            await message.reply("❌ Minimum giveaway duration is 10 seconds.")
            return

        prizes = calculate_tiered_prizes(total_prize, winner_count)
        shown_time = f"{value}{unit}"
        prize_lines = [f"{pos}. ฿{prize:,}" for pos, prize in prizes.items() if pos <= 3]
        if winner_count > 3 and 4 in prizes:
            prize_lines.append(f"4th–{winner_count}th: about ฿{prizes[4]:,} each")
        text = (
            f"🎉 **BOUNTY GIVEAWAY!** 🎉\n\n"
            f"Total bounty: ฿{total_prize:,}\n"
            f"Reason: {reason}\nWinners: {winner_count}\nEnds in: {shown_time}\n\n"
            f"**Prize distribution**\n" + "\n".join(prize_lines) + "\n\nJoin below!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Giveaway", callback_data="join_tgiveaway")],
            [InlineKeyboardButton("Participants", callback_data="view_tparticipants")],
        ])
        try:
            if target_chat_id == message.chat.id:
                sent = await message.reply(text, reply_markup=kb)
            else:
                sent = await client.send_message(target_chat_id, text, reply_markup=kb)
        except Exception as exc:
            print(f"[bounty giveaway send] {target_chat_id}: {exc}")
            await message.reply("❌ I couldn’t post there. Make sure the bot is in the target group and has permission to send messages.")
            return

        key = _giveaway_key(target_chat_id, sent.id)
        active_giveaways[key] = {
            "chat_id": target_chat_id,
            "message_id": sent.id,
            "total_prize": total_prize,
            "description": reason,
            "end_time": time.time() + duration,
            "participants": [],
            "winner_count": winner_count,
            "prizes": prizes,
            "started_by": message.from_user.id,
            "is_tiered": True,
            "duration": duration,
            "chat_title": getattr(target_chat, "title", None) or "Group",
        }
        asyncio.create_task(end_tiered_giveaway_task(app, key, duration))
        if target_chat_id != message.chat.id:
            await message.reply(f"✅ Bounty giveaway started in **{getattr(target_chat, 'title', None) or target_chat_id}**.")

    # ==================== /join ====================
    @app.on_message(filters.command("join"))
    async def join_giveaway_by_command(client, message):
        regular = None
        for key, g in active_giveaways.items():
            if g["chat_id"] == message.chat.id:
                regular = (key, g)
                break

        if regular:
            key, g = regular
            uid = message.from_user.id
            if uid in g["participants"]:
                await message.reply("Already joined!")
                return
            g["participants"].append(uid)
            await message.reply(
                f"**Joined!**\n"
                f"Prize: {_giveaway_prize_label(g)}\n"
                f"Total: {len(g['participants'])}"
            )
            return

        gg = get_global_giveaway()
        if gg is not None:
            if message.chat.id != MAIN_GROUP_ID:
                await message.reply(
                    f"❌ **Global giveaway is only joinable in the main group!**\n\n"
                    f"{MAIN_GROUP_LINK}"
                )
                return
            uid = message.from_user.id
            if uid in gg["participants"]:
                await message.reply("Already joined!")
                return

            main_ok = False
            updates_ok = False
            try:
                m = await client.get_chat_member(MAIN_GROUP_ID, uid)
                if str(m.status).split(".")[-1].upper() in (
                    "MEMBER", "ADMINISTRATOR", "OWNER", "CREATOR"
                ):
                    main_ok = True
            except Exception:
                pass
            try:
                m = await client.get_chat_member(UPDATE_CHANNEL_USERNAME, uid)
                if str(m.status).split(".")[-1].upper() in (
                    "MEMBER", "ADMINISTRATOR", "OWNER", "CREATOR"
                ):
                    updates_ok = True
            except Exception:
                updates_ok = False

            if not main_ok or not updates_ok:
                missing = []
                if not main_ok:
                    missing.append("Main Group")
                if not updates_ok:
                    missing.append("Updates Channel")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Main Group", url=MAIN_GROUP_LINK)],
                    [InlineKeyboardButton("Join Updates", url=UPDATE_CHANNEL_LINK)],
                    [InlineKeyboardButton("Verify & Join", callback_data="verify_global_giveaway")],
                ])
                await message.reply(
                    f"❌ **Join first: {', '.join(missing)}**",
                    reply_markup=kb,
                )
                return

            gg["participants"].append(uid)
            await message.reply(
                f"**Joined Global Giveaway!**\n"
                f"Prize: ฿{gg['total_prize']:,}\n"
                f"Total: {len(gg['participants'])}"
            )
            return

        await message.reply("❌ No active giveaway in this chat!")

    # ==================== /cancelgiveaway ====================
    @app.on_message(filters.command("cancelgiveaway") & filters.group)
    async def cancel_giveaway_cmd(client, message):
        if not is_admin_or_owner(message.from_user.id):
            await message.reply("⛔ You are not allowed to use this command.")
            return
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/cancelgiveaway [message_id]`")
            return
        try:
            msg_id = int(args[1])
        except ValueError:
            await message.reply("❌ Invalid ID!")
            return

        key = _giveaway_key(message.chat.id, msg_id)
        if key not in active_giveaways:
            await message.reply("❌ Giveaway not found!")
            return

        g = active_giveaways[key]
        if g.get("prize_type") == "character" and message.from_user.id != OWNER_ID:
            await _blink_reply(message, "⛔ Only the owner can manage a character giveaway.")
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, cancel", callback_data=f"confirm_cancel_giveaway_{key}")],
            [InlineKeyboardButton("No, keep", callback_data="cancel_cancel_giveaway")],
        ])
        await message.reply(
            f"**CANCEL GIVEAWAY?**\n\n"
            f"Prize: {_giveaway_prize_label(g)}\n"
            f"Participants: {len(g['participants'])}\n\n"
            f"Are you sure?",
            reply_markup=kb,
        )

    # ==================== /endgiveaway ====================
    @app.on_message(filters.command("endgiveaway") & filters.group)
    async def end_giveaway_early_cmd(client, message):
        if not is_admin_or_owner(message.from_user.id):
            await message.reply("⛔ You are not allowed to use this command.")
            return
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/endgiveaway [message_id]`")
            return
        try:
            msg_id = int(args[1])
        except ValueError:
            await message.reply("❌ Invalid ID!")
            return
        key = _giveaway_key(message.chat.id, msg_id)
        if key not in active_giveaways:
            await message.reply("❌ Giveaway not found!")
            return
        g = active_giveaways[key]
        if g.get("prize_type") == "character" and message.from_user.id != OWNER_ID:
            await _blink_reply(message, "⛔ Only the owner can manage a character giveaway.")
            return
        if not g["participants"]:
            await message.reply("❌ No participants!")
            del active_giveaways[key]
            return
        await _finish_tiered_giveaway(app, key)

    # ==================== /activegiveaways ====================
    @app.on_message(filters.command("activegiveaways"))
    async def active_giveaways_cmd(client, message):
        if not is_admin_or_owner(message.from_user.id):
            await message.reply("⛔ You are not allowed to use this command.")
            return

        text = "**ACTIVE GIVEAWAYS**\n\n"
        has = False
        for key, g in list(active_giveaways.items())[:5]:
            has = True
            left = max(0, int(g["end_time"] - time.time()))
            text += (
                f"{g.get('chat_title', 'Unknown')}\n"
                f"   Prize: {_giveaway_prize_label(g)}\n"
                f"   Participants: {len(g['participants'])}\n"
                f"   Time left: {left // 60}m\n"
                f"   Key: `{key}`\n\n"
            )

        gg = get_global_giveaway()
        if gg is not None:
            has = True
            left = max(0, int(gg["end_time"] - time.time()))
            text += (
                f"**GLOBAL**\n"
                f"   Prize: ฿{gg['total_prize']:,}\n"
                f"   Participants: {len(gg['participants'])}\n"
                f"   Time left: {left // 60}m\n"
                f"   Reason: {gg.get('description', 'N/A')}\n\n"
            )

        if not has:
            text += "*No active giveaways.*"

        await message.reply(text)

    # ==================== /agiveaway ====================
    @app.on_message(filters.command("agiveaway"))
    async def start_global_giveaway(client, message):
        if message.from_user.id != OWNER_ID:
            await message.reply("⛔ You are not allowed to use this command.")
            return
        if message.chat.id != MAIN_GROUP_ID:
            await message.reply(f"❌ Must be in main group!\n{MAIN_GROUP_LINK}")
            return
        if get_global_giveaway() is not None:
            await message.reply("❌ Global giveaway already active!")
            return

        args = message.text.split(maxsplit=5)
        if len(args) < 4:
            await message.reply(
                "**GLOBAL GIVEAWAY**\n\n"
                "Format: `/agiveaway [time] [amount] [players] [reason]`\n"
                "Time: `30s`, `5m`, `1h`, `1d`"
            )
            return

        time_str = args[1].lower()
        total_prize = parse_amount(args[2])
        try:
            winner_count = int(args[3])
        except ValueError:
            await message.reply("❌ Invalid player count!")
            return
        reason = args[4] if len(args) > 4 else "Global Giveaway!"

        if total_prize is None or total_prize <= 0:
            await message.reply("❌ Invalid prize!")
            return
        winner_count = max(1, min(300, winner_count))

        time_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit = time_str[-1] if time_str else ""
        if unit not in time_map:
            await message.reply("❌ Invalid time format!")
            return
        try:
            duration = int(time_str[:-1]) * time_map[unit]
        except ValueError:
            await message.reply("❌ Invalid time value!")
            return
        if duration < 10:
            await message.reply("❌ Minimum 10 seconds!")
            return

        end_time = time.time() + duration
        prizes = calculate_tiered_prizes(total_prize, winner_count)

        unit_names = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        n = int(time_str[:-1])
        time_text = f"{n} {unit_names[unit]}"

        giveaway_data = {
            "chat_id": message.chat.id,
            "total_prize": total_prize,
            "description": reason,
            "end_time": end_time,
            "participants": [],
            "winner_count": winner_count,
            "prizes": prizes,
            "started_by": message.from_user.id,
            "time_text": time_text,
            "duration": duration,
        }
        set_global_giveaway(giveaway_data)

        prize_lines = ["**PRIZE DISTRIBUTION**\n"]
        for pos in (1, 2, 3):
            if pos in prizes:
                emoji = {1: "🥇", 2: "🥈", 3: "🥉"}[pos]
                suffix = {1: "1st", 2: "2nd", 3: "3rd"}[pos]
                prize_lines.append(f"{emoji} **{suffix}:** ฿{prizes[pos]:,}")
        if winner_count > 3 and 4 in prizes:
            prize_lines.append(f"🎖️ **4th-{winner_count}th:** ~฿{prizes[4]:,} each")
        prize_text = "\n".join(prize_lines)

        announcement = (
            f"🌍 **GLOBAL GIVEAWAY!** 🌍\n\n"
            f"Total Prize: ฿{total_prize:,}\n"
            f"Reason: {reason}\n"
            f"Winners: {winner_count}\n"
            f"Ends in: {time_text}\n\n"
            f"{prize_text}\n\n"
            f"**Requirements:**\n"
            f"Join Main Group: {MAIN_GROUP_LINK}\n"
            f"Join Updates: {UPDATE_CHANNEL_LINK}\n\n"
            f"Click below to join!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Global Giveaway", callback_data="join_global_giveaway")],
            [InlineKeyboardButton("Join Updates", url=UPDATE_CHANNEL_LINK)],
            [InlineKeyboardButton("Join Main Group", url=MAIN_GROUP_LINK)],
        ])
        try:
            await client.send_message(
                MAIN_GROUP_ID,
                announcement,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e:
            print(f"[agiveaway] main group send: {e}")

        group_text = (
            f"🌍 **GLOBAL GIVEAWAY!** 🌍\n\n"
            f"Prize: ฿{total_prize:,}\n"
            f"Reason: {reason}\n"
            f"Winners: {winner_count}\n"
            f"Ends in: {time_text}\n\n"
            f"Join the main group to participate!\n"
            f"{MAIN_GROUP_LINK}"
        )
        groups_sent = 0
        for gid in list(get_bot_groups()):
            if gid == MAIN_GROUP_ID:
                continue
            try:
                await client.send_message(gid, group_text, disable_web_page_preview=True)
                groups_sent += 1
                await asyncio.sleep(0.3)
            except Exception:
                pass

        asyncio.create_task(notify_giveaway_started(
            app=client,
            giveaway_type="global",
            total_prize=total_prize,
            winner_count=winner_count,
            reason=reason,
            time_text=time_text,
            duration_text=time_text,
            channel_id=UPDATE_CHANNEL_ID,
            owner_id=OWNER_ID,
            user_data=user_data,
            main_group_link=MAIN_GROUP_LINK,
            updates_channel_link=UPDATE_CHANNEL_LINK,
            bot_name=BOT_NAME,
            dm_min_prize=0,
        ))

        await message.reply(
            f"**GLOBAL GIVEAWAY STARTED!**\n\n"
            f"{time_text}\n"
            f"฿{total_prize:,}\n"
            f"{winner_count} winners\n"
            f"Sent to main + {groups_sent} groups"
        )

        asyncio.create_task(end_global_giveaway_task(app, duration))

    # ==================== /cancelagiveaway ====================
    @app.on_message(filters.command("cancelagiveaway"))
    async def cancel_global_giveaway_cmd(client, message):
        if message.from_user.id != OWNER_ID:
            await message.reply("⛔ You are not allowed to use this command.")
            return
        if message.chat.id != MAIN_GROUP_ID:
            await message.reply("❌ Must be in main group!")
            return
        gg = get_global_giveaway()
        if gg is None:
            await message.reply("❌ No active global giveaway!")
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, cancel", callback_data="confirm_cancel_global_giveaway")],
            [InlineKeyboardButton("No, keep", callback_data="cancel_cancel_global_giveaway")],
        ])
        await message.reply(
            f"**CANCEL GLOBAL GIVEAWAY?**\n\n"
            f"฿{gg['total_prize']:,}\n"
            f"{len(gg['participants'])} participants\n\n"
            f"Are you sure?",
            reply_markup=kb,
        )


# ==================== TASK HELPERS ====================
async def _finish_tiered_giveaway(app, key):
    g = active_giveaways.get(key)
    if not g:
        return
    participants = g["participants"]
    if not participants:
        try:
            await app.send_message(
                g["chat_id"],
                f"❌ **Giveaway ended with no participants!**\n\n"
                f"Prize: {_giveaway_prize_label(g)}"
            )
        except Exception:
            pass
        active_giveaways.pop(key, None)
        return

    if g.get("prize_type") == "character":
        ids = g.get("character_ids") or []
        if not ids and g.get("character"):
            ids = [g["character"].get("id")]
        candidates_by_id = {}
        for char_id in ids:
            character = get_character_by_id(char_id)
            if character and character.get("id") is not None:
                candidates_by_id[str(character["id"])] = character
        candidates = list(candidates_by_id.values())

        if not candidates:
            result = (
                "❌ **CHARACTER GIVEAWAY ENDED**\n\n"
                "No prize characters from the selected rarity are available now, so no award was made."
            )
        else:
            shuffled_participants = participants.copy()
            random.shuffle(shuffled_participants)
            requested_winners = max(1, int(g.get("winner_count", 1)))
            winners = shuffled_participants[:min(requested_winners, len(shuffled_participants))]

            random.shuffle(candidates)
            awarded = []
            for index, winner_id in enumerate(winners):
                character = candidates[index] if index < len(candidates) else random.choice(candidates)
                try:
                    player = get_player(winner_id)
                    player.captured_chars.append({
                        "id": character.get("id"),
                        "name": character.get("name", "Unknown"),
                        "image": character.get("image"),
                        "media_type": character.get("media_type", "photo"),
                        "rarity": character.get("rarity", g.get("rarity", "NORMAL")),
                        "captured_at": time.time(),
                    })
                    awarded.append((winner_id, character))
                except Exception as e:
                    print(f"[character giveaway award] user {winner_id}: {e}")
            if awarded:
                save_data()

            lines = []
            for position, (winner_id, character) in enumerate(awarded[:10], 1):
                try:
                    user = await app.get_users(winner_id)
                    mention = (
                        f"[{user.first_name}](https://t.me/{user.username})"
                        if user.username else f"[{user.first_name}](tg://user?id={winner_id})"
                    )
                except Exception:
                    mention = f"User `{winner_id}`"
                rarity = str(character.get("rarity", g.get("rarity", "NORMAL"))).upper()
                lines.append(
                    f"{position}. {mention} — {get_rarity_emoji(rarity)} "
                    f"**{character.get('name', 'Unknown')}** (ID `{character.get('id', 'N/A')}`)"
                )
            if len(awarded) > 10:
                lines.append(f"\n🎁 **+{len(awarded) - 10} more winners**")
            winner_text = "\n".join(lines) if lines else "No awards could be completed."
            result = (
                f"🎊 **CHARACTER GIVEAWAY ENDED!** 🎊\n\n"
                f"Rarity: **{g.get('rarity', 'Random')}**\n"
                f"Participants: {len(participants)} • Winners: {len(awarded)}/{requested_winners}\n\n"
                f"**WINNERS:**\n{winner_text}\n\nCongratulations!"
            )
        try:
            await app.send_message(g["chat_id"], result, disable_web_page_preview=True)
        except Exception as e:
            print(f"[character giveaway end] {e}")
        active_giveaways.pop(key, None)
        return

    winner_count = min(g["winner_count"], len(participants))
    prizes = g["prizes"]

    shuffled = participants.copy()
    random.shuffle(shuffled)
    winners = shuffled[:winner_count]

    lines = []
    for pos, wid in enumerate(winners, 1):
        amt = prizes.get(pos, 0)
        if amt > 0:
            p = get_player(wid)
            p.bounty += amt
            save_data()
        try:
            u = await app.get_users(wid)
            mention = (f"[{u.first_name}](https://t.me/{u.username})"
                       if u.username else u.first_name)
        except Exception:
            mention = f"User `{wid}`"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, "🎖️")
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(pos, "th")
        if pos <= 10:
            lines.append(f"{medal} **{pos}{suffix}** — {mention} → ฿{amt:,}")

    if winner_count > 10:
        lines.append(f"\n🎁 **+{winner_count - 10} more winners!**")

    result = (
        f"🎊 **GIVEAWAY ENDED!** 🎊\n\n"
        f"Prize: {_giveaway_prize_label(g)}\n"
        f"Reason: {g['description']}\n"
        f"Participants: {len(participants)}\n\n"
        f"**WINNERS:**\n" + "\n".join(lines) +
        f"\n\nCongratulations!"
    )

    try:
        await app.send_message(g["chat_id"], result, disable_web_page_preview=True)
    except Exception as e:
        print(f"[tgiveaway end] {e}")
    active_giveaways.pop(key, None)


async def end_tiered_giveaway_task(app, key, duration):
    await asyncio.sleep(duration)
    await _finish_tiered_giveaway(app, key)


async def end_global_giveaway_task(app, duration):
    await asyncio.sleep(duration)
    gg = get_global_giveaway()
    if gg is None:
        return

    participants = gg["participants"]
    if not participants:
        text = (
            f"🌍 **GLOBAL GIVEAWAY ENDED!**\n\n"
            f"฿{gg['total_prize']:,}\n"
            f"{gg['description']}\n"
            f"No participants."
        )
        try:
            await app.send_message(MAIN_GROUP_ID, text)
        except Exception:
            pass
        for gid in list(get_bot_groups()):
            if gid == MAIN_GROUP_ID:
                continue
            try:
                await app.send_message(gid, text)
                await asyncio.sleep(0.3)
            except Exception:
                pass
        clear_global_giveaway()
        return

    winner_count = min(gg["winner_count"], len(participants))
    prizes = gg["prizes"]

    shuffled = participants.copy()
    random.shuffle(shuffled)
    winners = shuffled[:winner_count]

    lines = []
    for pos, wid in enumerate(winners, 1):
        amt = prizes.get(pos, 0)
        if amt > 0:
            p = get_player(wid)
            p.bounty += amt
            save_data()
        try:
            u = await app.get_users(wid)
            mention = (f"[{u.first_name}](https://t.me/{u.username})"
                       if u.username else u.first_name)
        except Exception:
            mention = f"User `{wid}`"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, "🎖️")
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(pos, "th")
        if pos <= 10:
            lines.append(f"{medal} **{pos}{suffix}** — {mention} → ฿{amt:,}")

    if winner_count > 10:
        lines.append(f"\n🎁 **+{winner_count - 10} more!**")

    result = (
        f"🎊 **GLOBAL GIVEAWAY ENDED!** 🎊\n\n"
        f"Prize: ฿{gg['total_prize']:,}\n"
        f"Reason: {gg['description']}\n"
        f"Participants: {len(participants)}\n\n"
        f"**WINNERS:**\n" + "\n".join(lines) +
        f"\n\nCongratulations!"
    )

    try:
        await app.send_message(MAIN_GROUP_ID, result, disable_web_page_preview=True)
    except Exception:
        pass
    for gid in list(get_bot_groups()):
        if gid == MAIN_GROUP_ID:
            continue
        try:
            await app.send_message(gid, result, disable_web_page_preview=True)
            await asyncio.sleep(0.3)
        except Exception:
            pass

    clear_global_giveaway()
