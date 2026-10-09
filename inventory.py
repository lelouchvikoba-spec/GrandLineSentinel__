# inventory.py
import time
from pyrogram import filters

from config import BOT_NAME
from data_manager import get_player, save_data
from utils import format_time


def register_inventory(app):

    # ==================== /inventory ====================
    @app.on_message(filters.command("inventory"))
    async def inventory_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        text = f"🎒 **YOUR INVENTORY** 🎒\n"
        text += f"──────────────────\n\n"

        # Shields
        text += f"🛡️ **Shields ({len(p.shields)}):**\n"
        if p.shields:
            for i, s in enumerate(p.shields, 1):
                lvl = s.get("level", 1)
                uses = s.get("uses", 0)
                text += f"  {i}. Lv{lvl} — {uses} uses\n"
        else:
            text += f"  *None*\n"

        # XP Boosts
        text += f"\n⚡ **XP Boosts ({len(p.xp_boosts)}):**\n"
        if p.xp_boosts:
            for i, b in enumerate(p.xp_boosts, 1):
                dur = b.get("duration", 900)
                text += f"  {i}. {dur // 60} minutes\n"
        else:
            text += f"  *None*\n"

        # Active effects
        text += f"\n──────────────────\n"
        text += f"**Active effects:**\n"

        active_any = False
        if p.shield_level > 0 and p.shield_uses > 0:
            text += f"  🛡️ Shield Lv{p.shield_level} — {p.shield_uses} uses\n"
            active_any = True
        if p.boost_end > time.time():
            rem = int(p.boost_end - time.time())
            text += f"  ⚡ 2x XP — {format_time(rem)} left\n"
            active_any = True
        if not active_any:
            text += f"  *None*\n"

        text += f"\n──────────────────\n"
        text += f"💡 `/useshield` — Activate a shield\n"
        text += f"💡 `/useboost` — Activate an XP boost\n\n"
        text += f"🤖 @Grand_Line_Sentinel_bot"

        await message.reply(text)

    # ==================== /useshield ====================
    @app.on_message(filters.command("useshield"))
    async def use_shield_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if p.shield_level > 0 and p.shield_uses > 0:
            await message.reply(
                f"⚠️ **You already have an active shield!**\n\n"
                f"🛡️ Lv{p.shield_level} — {p.shield_uses} uses left"
            )
            return

        if not p.shields:
            await message.reply(
                "❌ **You don't have any shields in inventory!**\n\n"
                "💡 Buy one from `/shop`"
            )
            return

        p.shields.sort(key=lambda s: s.get("level", 1), reverse=True)
        chosen = p.shields.pop(0)

        p.shield_level = chosen.get("level", 1)
        p.shield_uses = chosen.get("uses", 3)
        save_data()

        await message.reply(
            f"✅ **Shield Activated!** ✅\n\n"
            f"🛡️ Lv{p.shield_level} — {p.shield_uses} uses\n\n"
            f"⚠️ It will protect you in PVP and rob until it breaks."
        )

    # ==================== /useboost ====================
    @app.on_message(filters.command("useboost"))
    async def use_boost_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if p.boost_end > time.time():
            rem = int(p.boost_end - time.time())
            await message.reply(
                f"⚠️ **You already have an active XP boost!**\n\n"
                f"⚡ {format_time(rem)} left"
            )
            return

        if not p.xp_boosts:
            await message.reply(
                "❌ **You don't have any XP boosts in inventory!**\n\n"
                "💡 Buy one from `/shop` (50M)"
            )
            return

        chosen = p.xp_boosts.pop(0)
        duration = chosen.get("duration", 900)

        p.boost_end = max(p.boost_end, time.time() + duration)
        save_data()

        await message.reply(
            f"✅ **2x XP Boost Activated!** ✅\n\n"
            f"⚡ XP gains doubled for **{duration // 60} minutes**\n\n"
            f"💪 Go earn some XP!"
        )