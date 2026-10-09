# haki_commands.py
import time
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    BOT_NAME, HAKI_NAMES, HAKI_MAX_LEVEL,
    HAKI_BASE_PRICE, HAKI_UPGRADE_COSTS, HAKI_SELL_REFUND,
    ADVANCED_REQUIRES_COIN, ADVANCED_BOUNTY_COST,
    HAKI_BAR_MAX, HAKI_BAR_PER_USE,
    ARMAMENT_RECOVERY, OBSERVATION_WIN_RATES, CONQ_AUTOWIN_CHANCE,
)
from data_manager import get_player, save_data
from utils import (
    get_haki_bar, get_haki_bar_visual, seconds_until_full, format_time,
    get_haki_use_cost, is_advanced_haki, is_haki_active,
)


def haki_upgrade_cost(current_level):
    from config import HAKI_UPGRADE_COSTS
    return HAKI_UPGRADE_COSTS.get(current_level)


def register_haki(app):

    # ==================== /upgradehaki ====================
    @app.on_message(filters.command("upgradehaki"))
    async def upgrade_haki_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if not p.haki:
            await message.reply(
                "❌ **You don't have any Haki!**\n\n"
                "Buy one from `/shop` first."
            )
            return

        if is_advanced_haki(p):
            await message.reply("✅ Your Haki is already **ADVANCED** (max)!")
            return

        # Normal level up
        if p.haki_level < HAKI_MAX_LEVEL:
            cost = haki_upgrade_cost(p.haki_level)
            if cost is None:
                await message.reply("❌ Upgrade not available.")
                return

            name = HAKI_NAMES.get(p.haki, p.haki)
            next_lvl = p.haki_level + 1

            if p.bounty < cost:
                await message.reply(
                    f"❌ **Not enough bounty!**\n\n"
                    f"{name} Lv.{p.haki_level} → Lv.{next_lvl}\n"
                    f"Cost: ฿{cost:,}\n"
                    f"You have: ฿{p.bounty:,}\n"
                    f"Need: ฿{cost - p.bounty:,} more"
                )
                return

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"Confirm Upgrade (฿{cost:,})",
                    callback_data=f"confirm_upgrade_haki_{p.haki}",
                )],
                [InlineKeyboardButton("Cancel", callback_data="noop")],
            ])

            await message.reply(
                f"**HAKI UPGRADE**\n\n"
                f"**{name}** Lv.{p.haki_level} → **Lv.{next_lvl}**\n\n"
                f"Cost: ฿{cost:,}\n"
                f"Your Bounty: ฿{p.bounty:,}\n\n"
                f"Confirm?",
                reply_markup=kb,
            )
            return

        # At Lv.3 → offer ADV upgrade
        if p.haki_level >= HAKI_MAX_LEVEL:
            coin_req = ADVANCED_REQUIRES_COIN
            bounty_req = ADVANCED_BOUNTY_COST
            name = HAKI_NAMES.get(p.haki, p.haki)

            if p.advanced_token < coin_req:
                await message.reply(
                    f"❌ **ADV upgrade requires:**\n\n"
                    f"Advanced Coin: **{coin_req}** (you have {p.advanced_token})\n"
                    f"Bounty: ฿{bounty_req:,}\n\n"
                    f"Earn Advanced Coins from World Boss top-3."
                )
                return

            if p.bounty < bounty_req:
                await message.reply(
                    f"❌ **Not enough bounty!**\n\n"
                    f"Need: ฿{bounty_req:,}\n"
                    f"Have: ฿{p.bounty:,}"
                )
                return

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"Confirm ADV ({coin_req} coin + ฿{bounty_req:,})",
                    callback_data=f"confirm_adv_haki_{p.haki}",
                )],
                [InlineKeyboardButton("Cancel", callback_data="noop")],
            ])

            await message.reply(
                f"**ADVANCED HAKI UPGRADE**\n\n"
                f"**{name}** Lv.3 → **ADV**\n\n"
                f"**Requirements:**\n"
                f"Advanced Coin: **{coin_req}**\n"
                f"Bounty: ฿{bounty_req:,}\n\n"
                f"**Advanced perks:**\n"
                f"Regen: 1h 30m → **3h**\n"
                f"Maxed effects\n\n"
                f"Confirm?",
                reply_markup=kb,
            )

    # ==================== /sell_haki ====================
    @app.on_message(filters.command("sell_haki"))
    async def sell_haki_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)
        if not p.haki:
            await message.reply("❌ **You don't have any Haki!**")
            return

        name = HAKI_NAMES.get(p.haki, p.haki)
        refund = HAKI_SELL_REFUND

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"Confirm Sell (฿{refund:,})",
                callback_data=f"confirm_sell_haki_{p.haki}",
            )],
            [InlineKeyboardButton("Cancel", callback_data="noop")],
        ])

        await message.reply(
            f"**SELL HAKI**\n\n"
            f"{name} {'ADV' if is_advanced_haki(p) else f'Lv.{p.haki_level}'}\n"
            f"Refund: ฿{refund:,} (base only)\n\n"
            f"You lose this Haki and its levels!\n\n"
            f"Confirm?",
            reply_markup=kb,
        )

    # ==================== /haki ====================
    @app.on_message(filters.command("haki"))
    async def haki_info_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if not p.haki:
            await message.reply(
                "❌ **You don't have any Haki!**\n\n"
                "Buy one from `/shop` (฿25M each)."
            )
            return

        name = HAKI_NAMES.get(p.haki, p.haki)
        lvl = "ADV" if is_advanced_haki(p) else f"Lv.{p.haki_level}"
        active = "Active" if p.haki_active else "Inactive"
        bar = get_haki_bar_visual(p)
        bar_raw = get_haki_bar(p)

        wait_full = seconds_until_full(p)
        wait_text = "Full" if wait_full == 0 else format_time(wait_full)

        uses_left = bar_raw // get_haki_use_cost(p)

        await message.reply(
            f"**HAKI INFO**\n\n"
            f"**{name}** — {lvl}\n"
            f"Status: {active}\n\n"
            f"Bar: `{bar}` ({bar_raw}/{HAKI_BAR_MAX})\n"
            f"Uses left: {uses_left}\n"
            f"Full in: {wait_text}\n\n"
            f"`/activehaki` — Activate\n"
            f"`/disactivehaki` — Deactivate\n"
            f"`/upgradehaki` — Level up\n"
            f"`/sell_haki` — Sell"
        )

    # ==================== /activehaki ====================
    @app.on_message(filters.command("activehaki"))
    async def activate_haki_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if not p.haki:
            await message.reply(
                "❌ **You don't have any Haki!**\n\n"
                "Buy one from `/shop` first."
            )
            return

        if p.haki_active:
            name = HAKI_NAMES.get(p.haki, p.haki)
            bar = get_haki_bar_visual(p)
            await message.reply(
                f"ℹ️ **{name} Haki is already active!**\n\n"
                f"Bar: `{bar}`"
            )
            return

        bar = get_haki_bar(p)
        if bar <= 0:
            wait = seconds_until_full(p)
            await message.reply(
                f"❌ **Haki bar is empty!**\n\n"
                f"Refill in **{format_time(wait)}**"
            )
            return

        p.haki_active = True
        save_data()

        name = HAKI_NAMES.get(p.haki, p.haki)
        lvl = "ADV" if is_advanced_haki(p) else f"Lv.{p.haki_level}"
        bar_visual = get_haki_bar_visual(p)

        await message.reply(
            f"✅ **{name} Haki ACTIVATED!**\n\n"
            f"Level: **{lvl}**\n"
            f"Bar: `{bar_visual}`\n\n"
            f"Deactivate with `/disactivehaki`\n"
            f"Check info with `/haki`"
        )

    # ==================== /disactivehaki ====================
    @app.on_message(filters.command("disactivehaki"))
    async def deactivate_haki_cmd(client, message):
        p = get_player(message.from_user.id, user=message.from_user)

        if not p.haki:
            await message.reply("❌ You don't have any Haki!")
            return

        if not p.haki_active:
            await message.reply("Haki is already inactive.")
            return

        p.haki_active = False
        save_data()

        name = HAKI_NAMES.get(p.haki, p.haki)
        await message.reply(
            f"**{name} Haki DEACTIVATED.**\n\n"
            f"Re-activate with `/activehaki`"
        )
