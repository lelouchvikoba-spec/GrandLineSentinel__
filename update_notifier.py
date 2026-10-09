# update_notifier.py
import json
import os
import time
import asyncio
from datetime import datetime

from config import TIMEZONE, UPDATE_CHANNEL_USERNAME


VERSION_FILE = "data/bot_version.json"


# ==================== VERSION STORAGE ====================
def get_stored_version():
    try:
        with open(VERSION_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": None, "last_start": 0, "last_update": 0}


def save_stored_version(data):
    os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
    with open(VERSION_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ==================== STARTUP NOTIFICATION ====================
async def notify_startup(app, bot_name, version, channel_id):
    """
    Send startup notification.
    Uses UPDATE_CHANNEL_USERNAME first, falls back to channel_id.
    """
    # Resolve target: username takes priority
    target = None
    if UPDATE_CHANNEL_USERNAME:
        target = UPDATE_CHANNEL_USERNAME
    elif channel_id:
        target = channel_id

    if not target:
        print("[Notifier] No update channel configured — skipping")
        return

    stored = get_stored_version()
    old_version = stored.get("version")
    now = time.time()

    is_update = (old_version is not None) and (old_version != version)
    is_first_run = old_version is None

    ts = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    if is_update:
        changelog = ""
        try:
            from config import BOT_CHANGELOG
            if BOT_CHANGELOG:
                changelog = f"\n📝 Changes:\n{BOT_CHANGELOG}\n"
        except Exception:
            pass
        text = (
            f"🚀 **BOT UPDATED!** 🚀\n\n"
            f"🤖 **Bot:** {bot_name}\n"
            f"📦 **Old:** `{old_version}`\n"
            f"📦 **New:** `{version}`\n"
            f"{changelog}\n"
            f"⏰ **Time:** {ts}\n\n"
            f"✅ All systems online.\n\n"
            f"@Grand_Line_Sentinel_bot"
        )
    elif is_first_run:
        text = (
            f"🎉 **BOT IS NOW ONLINE!** 🎉\n\n"
            f"🤖 **Bot:** {bot_name}\n"
            f"📦 **Version:** `{version}`\n"
            f"⏰ **Time:** {ts}\n\n"
            f"✅ First-time startup complete.\n\n"
            f"@Grand_Line_Sentinel_bot"
        )
    else:
        text = (
            f"🔄 **BOT RESTARTED** 🔄\n\n"
            f"🤖 **Bot:** {bot_name}\n"
            f"📦 **Version:** `{version}`\n"
            f"⏰ **Time:** {ts}\n\n"
            f"✅ Back online.\n\n"
            f"@Grand_Line_Sentinel_bot"
        )

    sent = False

    # Try username first
    try:
        await app.send_message(target, text)
        sent = True
        print(f"[Notifier] Startup notification sent to {target}")
    except Exception as e:
        print(f"[Notifier] Failed to send to {target}: {e}")

    # If username failed and we have an ID, try that
    if not sent and target == UPDATE_CHANNEL_USERNAME and channel_id:
        try:
            await app.send_message(channel_id, text)
            sent = True
            print(f"[Notifier] Startup notification sent to {channel_id}")
        except Exception as e:
            print(f"[Notifier] Failed to send to {channel_id}: {e}")

    if sent:
        save_stored_version({
            "version": version,
            "last_start": now,
            "last_update": now if is_update else stored.get("last_update", 0),
        })
    else:
        print("[Notifier] State NOT saved — will retry next startup")


# ==================== GIVEAWAY NOTIFICATION ====================
async def notify_giveaway_started(
    app,
    giveaway_type,
    total_prize,
    winner_count,
    reason,
    time_text,
    duration_text,
    channel_id=None,
    owner_id=None,
    user_data=None,
    main_group_link=None,
    updates_channel_link=None,
    bot_name="Bot",
    dm_min_prize=0,
):
    """Send giveaway announcement to channel, owner, and all users."""
    if giveaway_type == "global":
        header = "🌍 **GLOBAL GIVEAWAY STARTED!** 🌍"
        reqs = (
            f"⚠️ **Requirements:**\n"
            f"• Join Main Group: {main_group_link}\n"
            f"• Join Updates Channel: {updates_channel_link}\n\n"
        )
    else:
        header = "🎉 **GIVEAWAY STARTED!** 🎉"
        reqs = ""

    text = (
        f"{header}\n\n"
        f"📦 **Total Prize:** ฿{total_prize:,}\n"
        f"🎁 **Reason:** {reason}\n"
        f"👥 **Winners:** {winner_count}\n"
        f"⏰ **Duration:** {time_text}\n\n"
        f"{reqs}"
        f"💫 **Join now!**\n\n"
        f"@Grand_Line_Sentinel_bot"
    )

    sent = {"channel": 0, "owner": 0, "users": 0, "failed": 0}

    # Determine channel target (username preferred)
    channel_target = UPDATE_CHANNEL_USERNAME or channel_id

    # 1. Updates channel
    if channel_target:
        try:
            await app.send_message(channel_target, text, disable_web_page_preview=True)
            sent["channel"] = 1
        except Exception as e:
            print(f"[Giveaway] channel failed ({channel_target}): {e}")
            # Fallback to ID
            if channel_target == UPDATE_CHANNEL_USERNAME and channel_id:
                try:
                    await app.send_message(channel_id, text, disable_web_page_preview=True)
                    sent["channel"] = 1
                except Exception as e2:
                    print(f"[Giveaway] channel ID failed: {e2}")

    # 2. Owner DM
    if owner_id:
        try:
            await app.send_message(owner_id, text, disable_web_page_preview=True)
            sent["owner"] = 1
        except Exception as e:
            print(f"[Giveaway] owner DM failed: {e}")

    # 3. All users DM (only if prize >= threshold)
    if user_data and total_prize >= dm_min_prize:
        for uid_str in list(user_data.keys()):
            try:
                uid = int(uid_str)
                if uid == owner_id:
                    continue
                await app.send_message(uid, text, disable_web_page_preview=True)
                sent["users"] += 1
                await asyncio.sleep(0.1)
            except Exception:
                sent["failed"] += 1
    else:
        print(f"[Giveaway] Skipped user DMs (prize < threshold)")

    return sent