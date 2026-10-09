# games.py
import asyncio
import random
import time
import uuid
from pyrogram import filters

from config import BOT_NAME, OWNER_ID
from data_manager import get_player, save_data
from utils import (
    check_cooldown, parse_amount, get_xp_needed,
    get_pattern_result, get_observation_win_rate,
    get_observation_money_mult, get_armament_recovery,
    consume_haki_use, get_haki_use_cost, is_haki_active, is_advanced_haki,
    get_dart_threshold, build_copy_markup,
)
from pvp import (
    send_level_up_notification, send_level_up_group_notification,
    send_level_down_notification, send_level_down_group_notification,
)


# ==================== MINES ====================
MINES_GAMES = {}
MINES_PENDING = {}
RPS_GAMES = {}
MINES_SIZE = 5
MINES_COUNT = 5
MINES_OPTIONS = (3, 5, 8, 10)
MINES_MULTIPLIERS = (
    1.15, 1.35, 1.60, 1.95, 2.40,
    3.00, 3.80, 4.80, 6.20, 8.00,
    10.50, 14.00, 18.00, 23.00, 30.00,
    40.00, 55.00, 75.00, 100.00, 150.00,
)


def mines_multiplier(safe_count, mine_count=MINES_COUNT):
    """Return the cash-out multiplier after a number of safe reveals."""
    if safe_count <= 0:
        return 1.0
    base = MINES_MULTIPLIERS[min(safe_count, len(MINES_MULTIPLIERS)) - 1]
    # More mines mean a greater risk and therefore a higher payout.
    risk_scale = 1.0 + ((int(mine_count) - MINES_COUNT) * 0.18)
    return round(base * max(0.55, risk_scale), 2)


def mines_selection_keyboard(user_id):
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("3", callback_data=f"mines_select_{user_id}_3"),
            InlineKeyboardButton("5", callback_data=f"mines_select_{user_id}_5"),
            InlineKeyboardButton("8", callback_data=f"mines_select_{user_id}_8"),
            InlineKeyboardButton("10", callback_data=f"mines_select_{user_id}_10"),
        ],
        [InlineKeyboardButton("Cancel", callback_data=f"mines_cancel_{user_id}")],
    ])


def mines_keyboard(game):
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = []
    for row in range(MINES_SIZE):
        buttons = []
        for col in range(MINES_SIZE):
            index = row * MINES_SIZE + col
            if index in game["revealed"]:
                label = "💎"
            else:
                label = "⬜"
            buttons.append(InlineKeyboardButton(
                label, callback_data=f"mines_tile_{game['user_id']}_{index}"
            ))
        rows.append(buttons)
    if game["revealed"]:
        payout = int(game["bet"] * mines_multiplier(len(game["revealed"]), game["mine_count"]))
        rows.append([InlineKeyboardButton(
            f"💰 Cash Out ฿{payout:,}",
            callback_data=f"mines_cashout_{game['user_id']}",
        )])
    rows.append([InlineKeyboardButton(
        "❌ End Game",
        callback_data=f"mines_end_{game['user_id']}",
    )])
    return InlineKeyboardMarkup(rows)


def mines_text(game):
    safe = len(game["revealed"])
    payout = int(game["bet"] * mines_multiplier(safe, game["mine_count"]))
    return (
        "💣 **MINES**\n\n"
        f"Bet: ฿{game['bet']:,}\n"
        f"Mines: **{game['mine_count']}** | Safe tiles: **{safe}** / {MINES_SIZE * MINES_SIZE - game['mine_count']}\n"
        f"Current cash-out: **฿{payout:,}**\n\n"
        "Reveal a safe tile or cash out before hitting a mine."
    )


def rps_keyboard(token, accept=False):
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    if accept:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Accept", callback_data=f"rps_accept_{token}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"rps_decline_{token}"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨 Rock", callback_data=f"rps_choice_{token}_rock"),
        InlineKeyboardButton("📄 Paper", callback_data=f"rps_choice_{token}_paper"),
        InlineKeyboardButton("✂️ Scissors", callback_data=f"rps_choice_{token}_scissors"),
    ]])


last_pay_time = {}


# ==================== HAKI OUTCOME HELPER ====================
def _apply_haki_outcome(player, win, amount):
    """
    Apply Observation (better luck) and Armament (recovery) to game outcome.
    Returns (final_win, final_amount, note)
    """
    note = ""

    # Observation: flip a loss to a win at the given rate
    if not win and is_haki_active(player) and player.haki == "obv":
        rate = get_observation_win_rate(player)
        if rate is not None and random.random() < rate:
            win = True
            note = "\n*Observation Haki flipped the odds!*"
            consume_haki_use(player)

    # Observation ADV: 2x money on win
    if win and is_haki_active(player) and player.haki == "obv":
        mult = get_observation_money_mult(player)
        if mult > 1.0:
            amount = int(amount * mult)
            note += f"\n*ADV Observation: x{mult} money!*"

    # Armament: recovery on loss
    if not win and is_haki_active(player) and player.haki == "arm":
        recovery = get_armament_recovery(player)
        if recovery > 0:
            if consume_haki_use(player, cost=get_haki_use_cost(player)):
                refund = int(amount * recovery)
                player.bounty += refund
                note += f"\n*Armament recovered ฿{refund:,} ({int(recovery * 100)}%)!*"
            else:
                note += "\n*Armament couldn’t recover your loss: not enough Haki energy.*"

    return win, amount, note


def _apply_win(player, amount, base_xp):
    player.bounty += amount
    player.xp += base_xp
    old_level = player.level
    while player.xp >= get_xp_needed(player.level) and player.level < 200:
        player.xp -= get_xp_needed(player.level)
        player.level += 1
    if player.level >= 200:
        player.xp = 0
    level_text = f"\n\nLEVEL UP! {old_level} → {player.level}" if player.level > old_level else ""
    return base_xp, old_level, level_text


def _apply_loss(player, amount, base_xp):
    player.bounty -= amount
    player.xp -= base_xp
    old_level = player.level
    level_down_text = ""
    while player.xp < 0 and player.level > 1:
        player.level -= 1
        player.xp += get_xp_needed(player.level)
        level_down_text = f"\n\nLEVEL DOWN! {old_level} → {player.level}"
    if player.xp < 0:
        player.xp = 0
        player.level = 1
    return base_xp, old_level, level_down_text


def _xp_with_bonus(player, base_xp):
    """Apply crew ship XP bonus if available."""
    try:
        from crew import player_crew_bonus
        bonus = player_crew_bonus(player.user_id, "xp_bonus")
        if bonus > 0:
            base_xp = int(base_xp * (1 + bonus))
    except Exception:
        pass
    return max(1, base_xp)


# ==================== SLOT DICE DECODE ====================
# Telegram's animated 🎰 packs three 2-bit reel indices into one value
# in the range 1..64.  Reel order is fixed by the platform
# (core.telegram.org/api/dice + MasterGroosha/telegram-casino-bot):
#     0 = BAR, 1 = 🍇, 2 = 🍋, 3 = 7️⃣
# Three 7️⃣ (jackpot) maps to value 64.
SLOT_REEL_SYMBOLS = ["BAR", "🍇", "🍋", "7️⃣"]


def _decode_slot_reels(value: int):
    """Decode a Telegram 🎰 dice value (1-64) into [center, right, left].

    Telegram sends three 2-bit slots packed as little-endian-base-4.
    Decoding right-to-left (slot0, slot1, slot2) reproduces what the
    client displays left-to-right: [left, center, right]."""
    if not (1 <= value <= 64):
        return ["❓", "❓", "❓"]
    reels = []
    v = value - 1
    for _ in range(3):
        reels.append(SLOT_REEL_SYMBOLS[v % 4])
        v //= 4
    return list(reversed(reels))


def register_games(app):

    # ==================== /mines ====================
    @app.on_message(filters.command("mines"))
    async def mines_cmd(client, message):
        uid = message.from_user.id
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/mines [amount]`\nExample: `/mines 100K`")
            return
        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid bet amount!")
            return
        if uid in MINES_GAMES:
            await message.reply("❌ You already have an active Mines game. Finish it first.")
            return
        if uid in MINES_PENDING:
            await message.reply("❌ Choose the mine count from your current Mines menu first.")
            return
        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"❌ You need ฿{amount:,}, but you only have ฿{p.bounty:,}.")
            return

        MINES_PENDING[uid] = {"bet": amount, "chat_id": message.chat.id}
        await message.reply(
            "💣 **CHOOSE YOUR MINES**\n\n"
            f"Bet: ฿{amount:,}\n"
            "More mines mean greater risk and a higher bounty multiplier.",
            reply_markup=mines_selection_keyboard(uid),
        )

    @app.on_message(filters.command("trackmines"))
    async def track_mines_cmd(client, message):
        if message.from_user.id != OWNER_ID:
            await message.reply("")
            return
        active = list(MINES_GAMES.values())
        replied = message.reply_to_message
        if replied:
            active = [
                game for game in active
                if game.get("chat_id") == replied.chat.id
                and game.get("message_id") == replied.id
            ]
        if not active:
            await message.reply("🛰️ No active Mines game found. Reply to the current Mines board message.")
            return

        lines = ["🛰️ **MINES TRACKER — OWNER VIEW**"]
        for game in active:
            mine_positions = sorted(game.get("mines", set()))
            coords = [f"R{pos // MINES_SIZE + 1}C{pos % MINES_SIZE + 1}" for pos in mine_positions]
            board = []
            for row in range(MINES_SIZE):
                board.append(" ".join(
                    "💣" if row * MINES_SIZE + col in game.get("mines", set())
                    else "💎" if row * MINES_SIZE + col in game.get("revealed", set())
                    else "⬜"
                    for col in range(MINES_SIZE)
                ))
            lines.append(
                f"\nPlayer: `{game.get('user_id')}`\n"
                f"Bet: ฿{game.get('bet', 0):,} | Mines: {game.get('mine_count', 0)}\n"
                f"Locations: {', '.join(coords)}\n\n" + "\n".join(board)
            )
        await message.reply("\n".join(lines))

    # ==================== /basket ====================
    @app.on_message(filters.command("basket"))
    async def basket_cmd(client, message):
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/basket [amount]`\nA score of 4 or 5 wins 2x.")
            return
        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid bet amount!")
            return
        p = get_player(message.from_user.id, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"❌ You need ฿{amount:,}, but have ฿{p.bounty:,}.")
            return
        p.bounty -= amount
        dice = await client.send_dice(message.chat.id, emoji="🏀")
        await asyncio.sleep(2)
        score = dice.dice.value
        if score >= 4:
            payout = amount * 2
            p.bounty += payout
            result = f"🏀 **SCORE {score}! YOU WIN!**\nPayout: ฿{payout:,}"
        else:
            result = f"🏀 **SCORE {score}! YOU LOSE!**\nLost: ฿{amount:,}"
        save_data()
        await message.reply(result + f"\nBalance: ฿{p.bounty:,}")

    # ==================== /rps ====================
    @app.on_message(filters.command("rps"))
    async def rps_cmd(client, message):
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/rps [amount]` (play bot)\nReply to a player with `/rps [amount]` to challenge them.")
            return
        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid bet amount!")
            return
        challenger = get_player(message.from_user.id, user=message.from_user)
        target_msg = message.reply_to_message
        if target_msg and target_msg.from_user and not target_msg.from_user.is_bot:
            if target_msg.from_user.id == message.from_user.id:
                await message.reply("❌ You cannot challenge yourself.")
                return
            if challenger.bounty < amount:
                await message.reply(f"❌ You need ฿{amount:,} to make this challenge.")
                return
            token = uuid.uuid4().hex[:10]
            RPS_GAMES[token] = {"mode": "player", "bet": amount,
                "challenger": message.from_user.id, "target": target_msg.from_user.id,
                "choices": {}, "status": "pending"}
            await message.reply(
                f"✊ **RPS CHALLENGE**\n\n{message.from_user.first_name} challenges {target_msg.from_user.first_name}\n"
                f"Stake: ฿{amount:,}\n\nThe challenged player must accept.",
                reply_markup=rps_keyboard(token, accept=True),
            )
            return
        if challenger.bounty < amount:
            await message.reply(f"❌ You need ฿{amount:,}, but have ฿{challenger.bounty:,}.")
            return
        token = uuid.uuid4().hex[:10]
        challenger.bounty -= amount
        RPS_GAMES[token] = {"mode": "bot", "bet": amount,
            "challenger": message.from_user.id, "target": None,
            "choices": {}, "status": "active"}
        save_data()
        await message.reply(f"✊ **RPS AGAINST BOT**\nStake: ฿{amount:,}\nChoose your move:", reply_markup=rps_keyboard(token))

    # ==================== /bet ====================
    @app.on_message(filters.command("bet"))
    async def bet_cmd(client, message):
        uid = message.from_user.id
        can, rem = check_cooldown(uid, 2)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

        args = message.text.split()
        if len(args) != 3:
            await message.reply("Usage: `/bet [amount] [t/h]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        choice = args[2].lower()
        if choice not in ("t", "h"):
            await message.reply("Choose 't' or 'h'!")
            return

        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(
                f"Need ฿{amount:,}! You have ฿{p.bounty:,}",
                reply_markup=build_copy_markup([
                    ("📋 Copy Bet", f"{int(amount or 0)}"),
                    ("📋 Copy Balance", f"{int(p.bounty or 0)}"),
                ]),
            )
            return

        # Pattern-driven result
        result = get_pattern_result(
            game="bet",
            user_id=uid,
            default_choice_fn=lambda: random.choice(["h", "t"]),
        )

        win = (choice == result)
        display = "HEADS" if result == "h" else "TAILS"

        # Haki outcome
        win, amount, haki_note = _apply_haki_outcome(p, win, amount)

        xp = _xp_with_bonus(p, max(1, min(50, amount // 100_000)))
        if p.boost_end > time.time() and win:
            xp = min(75, int(xp * 1.5))

        if win:
            gained, old_lvl, lt = _apply_win(p, amount, xp)
            save_data()
            if p.level > old_lvl:
                await send_level_up_notification(app, uid, old_lvl, p.level, "game")
                await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"🎉 Coin landed on **{display}**!\n"
                f"✅ **Won ฿{amount:,}!**\n"
                f"⭐ **+{gained} XP**{haki_note}{lt}\n"
                f"Balance: ฿`{p.bounty:,}`",
                reply_markup=build_copy_markup([
                    ("📋 Copy Bet", f"{int(amount or 0)}"),
                    ("📋 Copy Balance", f"{int(p.bounty or 0)}"),
                ]),
            )
        else:
            lost, old_lvl, lt = _apply_loss(p, amount, xp)
            save_data()
            if p.level < old_lvl:
                await send_level_down_notification(app, uid, old_lvl, p.level, "game")
                await send_level_down_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"😢 Coin landed on **{display}**!\n"
                f"❌ **Lost ฿{amount:,}!**\n"
                f"⭐ **-{lost} XP**{haki_note}{lt}\n"
                f"Balance: ฿`{p.bounty:,}`",
                reply_markup=build_copy_markup([
                    ("📋 Copy Bet", f"{int(amount or 0)}"),
                    ("📋 Copy Balance", f"{int(p.bounty or 0)}"),
                ]),
            )

    # ==================== /dice ====================
    @app.on_message(filters.command("dice"))
    async def dice_cmd(client, message):
        uid = message.from_user.id
        can, rem = check_cooldown(uid, 2)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

        args = message.text.split()
        if len(args) != 3:
            await message.reply("Usage: `/dice [amount] [e/o]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        choice = args[2].lower()
        if choice not in ("e", "o"):
            await message.reply("Choose 'e' or 'o'!")
            return

        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"Need ฿{amount:,}! You have ฿{p.bounty:,}")
            return

        pattern_result = get_pattern_result(
            game="dice",
            user_id=uid,
            default_choice_fn=lambda: random.choice(["e", "o"]),
        )

        dice_msg = await client.send_dice(message.chat.id, emoji="🎲")
        await asyncio.sleep(2)
        roll = dice_msg.dice.value

        is_even = (pattern_result == "e")
        win = (choice == "e" and is_even) or (choice == "o" and not is_even)

        win, amount, haki_note = _apply_haki_outcome(p, win, amount)

        xp = _xp_with_bonus(p, max(1, min(50, amount // 100_000)))
        if p.boost_end > time.time() and win:
            xp = min(75, int(xp * 1.5))

        if win:
            gained, old_lvl, lt = _apply_win(p, amount, xp)
            save_data()
            if p.level > old_lvl:
                await send_level_up_notification(app, uid, old_lvl, p.level, "game")
                await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"🎲 Rolled **{roll}** ({pattern_result.upper()})!\n"
                f"✅ Won ฿{amount:,}!\n"
                f"⭐ **+{gained} XP**{haki_note}{lt}"
            )
        else:
            lost, old_lvl, lt = _apply_loss(p, amount, xp)
            save_data()
            if p.level < old_lvl:
                await send_level_down_notification(app, uid, old_lvl, p.level, "game")
                await send_level_down_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"🎲 Rolled **{roll}** ({pattern_result.upper()})!\n"
                f"❌ Lost ฿{amount:,}!\n"
                f"⭐ **-{lost} XP**{haki_note}{lt}"
            )

    # ==================== /dart ====================
    @app.on_message(filters.command("dart"))
    async def dart_cmd(client, message):
        uid = message.from_user.id
        can, rem = check_cooldown(uid, 2)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/dart [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"Need ฿{amount:,}! You have ฿{p.bounty:,}")
            return

        dart_msg = await client.send_dice(message.chat.id, emoji="🎯")
        await asyncio.sleep(2)
        dart_value = dart_msg.dice.value

        threshold = get_dart_threshold(p)
        win = dart_value >= threshold

        # Advanced Observation reroll
        if not win and is_advanced_haki(p) and p.haki == "obv":
            reroll = random.randint(1, 6)
            if reroll >= threshold:
                win = True
                dart_value = reroll

        win, amount, haki_note = _apply_haki_outcome(p, win, amount)

        xp = _xp_with_bonus(p, max(1, min(50, amount // 100_000)))
        if p.boost_end > time.time() and win:
            xp = min(75, int(xp * 1.5))

        if win:
            gained, old_lvl, lt = _apply_win(p, amount, xp)
            save_data()
            if p.level > old_lvl:
                await send_level_up_notification(app, uid, old_lvl, p.level, "game")
                await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            header = "🎯 **BULLSEYE!**" if dart_value == 6 else f"🎯 Scored **{dart_value}**!"
            await message.reply(f"{header}\n+฿{amount:,}!\n⭐ **+{gained} XP**{haki_note}{lt}")
        else:
            lost, old_lvl, lt = _apply_loss(p, amount, xp)
            save_data()
            if p.level < old_lvl:
                await send_level_down_notification(app, uid, old_lvl, p.level, "game")
                await send_level_down_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"💨 **MISSED!**\n"
                f"Scored {dart_value}!\n"
                f"-฿{amount:,}!\n"
                f"⭐ **-{lost} XP**{haki_note}{lt}"
            )

    # ==================== /bowl ====================
    @app.on_message(filters.command("bowl"))
    async def bowl_cmd(client, message):
        uid = message.from_user.id
        can, rem = check_cooldown(uid, 2)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/bowl [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"Need ฿{amount:,}! You have ฿{p.bounty:,}")
            return

        bowl_msg = await client.send_dice(message.chat.id, emoji="🎳")
        await asyncio.sleep(2)
        # ✅ Telegram bowling: value 1-6 = pins KNOCKED (6 = STRIKE)
        pins = bowl_msg.dice.value

        obv_haki = (p.haki == "obv" and p.haki_level >= 3)

        if pins == 6:
            win, result = True, "🎳 **STRIKE!** All 6 pins!"
        elif pins == 5:
            win, result = True, "🎳 **SPARE!** 5 pins!"
        elif pins == 4:
            win, result = True, "🎳 **GOOD!** 4 pins!"
        elif pins == 3:
            win = True if obv_haki else (random.random() < 0.5)
            result = f"🎳 **3 pins!** " + ("Win!" if win else "Lose!")
        elif pins == 2:
            win, result = False, "💨 **WEAK!** Only 2 pins!"
        else:  # 1
            win, result = False, "💨 **GUTTER!** Only 1 pin!"

        win, amount, haki_note = _apply_haki_outcome(p, win, amount)

        xp = _xp_with_bonus(p, max(1, min(50, amount // 100_000)))
        if p.boost_end > time.time() and win:
            xp = min(75, int(xp * 1.5))

        if win:
            gained, old_lvl, lt = _apply_win(p, amount, xp)
            save_data()
            if p.level > old_lvl:
                await send_level_up_notification(app, uid, old_lvl, p.level, "game")
                await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(f"{result}{haki_note}\n+฿{amount:,}!\n⭐ **+{gained} XP**{lt}")
        else:
            lost, old_lvl, lt = _apply_loss(p, amount, xp)
            save_data()
            if p.level < old_lvl:
                await send_level_down_notification(app, uid, old_lvl, p.level, "game")
                await send_level_down_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(f"{result}\n-฿{amount:,}!\n⭐ **-{lost} XP**{haki_note}{lt}")

    # ==================== /soccer ====================
    @app.on_message(filters.command("soccer"))
    async def soccer_cmd(client, message):
        uid = message.from_user.id
        can, rem = check_cooldown(uid, 2)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/soccer [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"Need ฿{amount:,}! You have ฿{p.bounty:,}")
            return

        msg = await client.send_dice(message.chat.id, emoji="⚽")
        await asyncio.sleep(2)
        val = msg.dice.value

        obv_haki = (p.haki == "obv" and p.haki_level >= 3)
        win = val >= (3 if obv_haki else 4)

        win, amount, haki_note = _apply_haki_outcome(p, win, amount)

        xp = _xp_with_bonus(p, max(1, min(50, amount // 100_000)))
        if p.boost_end > time.time() and win:
            xp = min(75, int(xp * 1.5))

        if win:
            gained, old_lvl, lt = _apply_win(p, amount, xp)
            save_data()
            if p.level > old_lvl:
                await send_level_up_notification(app, uid, old_lvl, p.level, "game")
                await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(f"⚽ **GOAL!**{haki_note}\n+฿{amount:,}!\n⭐ **+{gained} XP**{lt}")
        else:
            lost, old_lvl, lt = _apply_loss(p, amount, xp)
            save_data()
            if p.level < old_lvl:
                await send_level_down_notification(app, uid, old_lvl, p.level, "game")
                await send_level_down_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(f"🥅 **MISSED!**\n-฿{amount:,}!\n⭐ **-{lost} XP**{haki_note}{lt}")

    # ==================== /slot ====================
    # Reels are the platform-defined 🎰 values, NOT a local pool — see
    # _decode_slot_reels and SLOT_REEL_SYMBOLS above.  Telegram generates
    # the dice on its own server; the bot just decodes the result and
    # waits for the animation before announcing the payout.
    @app.on_message(filters.command("slot"))
    async def slot_cmd(client, message):
        uid = message.from_user.id
        can, rem = check_cooldown(uid, 2)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

        args = message.text.split()
        if len(args) != 2:
            await message.reply(
                "🎰 **SLOT MACHINE**\n\n"
                "Usage: `/slot [amount]`\n\n"
                "Match **2 or 3** symbols to win:\n"
                "• 2 matching → **1x** your bet — *Normal Win*\n"
                "• 3 matching → **1x** your bet — *Normal Win*\n"
                "• 7️⃣7️⃣7️⃣ → **2x** your bet — *JACKPOT!*"
            )
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        p = get_player(uid, user=message.from_user)
        if p.bounty < amount:
            await message.reply(f"Need ฿{amount:,}! You have ฿{p.bounty:,}")
            return

        # Step 1 — send the 🎰 dice FIRST (as you asked)
        dice_msg = await client.send_dice(message.chat.id, emoji="🎰")
        dice_value = dice_msg.dice.value

        # Step 2 — wait for the spinning animation to finish
        await asyncio.sleep(2.0)

        # Step 3 — decode the actual reels from Telegram's value
        a, b, c = _decode_slot_reels(dice_value)

        # Step 4 — win / loss rules exactly as you described:
        #   2 matching  → Normal Win   (1x)
        #   3 matching  → Normal Win   (1x)
        #   7️⃣7️⃣7️⃣     → JACKPOT      (2x)
        if a == b == c:
            win = True
            if a == "7️⃣":
                mult, result = 2.0, "🎰 **JACKPOT! 7️⃣7️⃣7️⃣ — 2x payout!**"
            else:
                mult, result = 1.0, f"🎰 **TRIPLE {a}! — 1x payout!**"
        elif a == b or b == c or a == c:
            win, mult, result = True, 1.0, "🎰 **DOUBLE MATCH! — 1x payout!**"
        else:
            win, mult, result = False, 0.0, "🎰 **No match!**"

        orig_win = win
        win, amount, haki_note = _apply_haki_outcome(p, win, amount)
        if win:
            payout = int(amount * mult) if orig_win else amount
        else:
            payout = 0

        xp = _xp_with_bonus(p, max(1, min(50, amount // 100_000)))
        if p.boost_end > time.time() and win:
            xp = min(75, int(xp * 1.5))

        reel_line = f"┃ {a} ┃ {b} ┃ {c} ┃"

        if win:
            gained, old_lvl, lt = _apply_win(p, payout, xp)
            save_data()
            if p.level > old_lvl:
                await send_level_up_notification(app, uid, old_lvl, p.level, "game")
                await send_level_up_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"{reel_line}\n{result}\n"
                f"✅ **Won ฿{payout:,}!**\n"
                f"⭐ **+{gained} XP**{haki_note}{lt}"
            )
        else:
            lost, old_lvl, lt = _apply_loss(p, amount, xp)
            save_data()
            if p.level < old_lvl:
                await send_level_down_notification(app, uid, old_lvl, p.level, "game")
                await send_level_down_group_notification(app, message.chat.id, p.name, old_lvl, p.level)
            await message.reply(
                f"{reel_line}\n{result}\n"
                f"❌ **Lost ฿{amount:,}!**\n"
                f"⭐ **-{lost} XP**{haki_note}{lt}"
            )

    # ==================== /pay ====================
    @app.on_message(filters.command("pay"))
    async def pay_cmd(client, message):
        uid = message.from_user.id
        p = get_player(uid, user=message.from_user)

        now = time.time()
        if now - p.pay_cd < 600:
            rem = 600 - (now - p.pay_cd)
            await message.reply(f"⏰ **Cooldown!** Wait {int(rem // 60)}m {int(rem % 60)}s.")
            return

        if not message.reply_to_message:
            await message.reply(
                "**PAY**\n\n"
                "Reply to a user with `/pay [amount]`\n"
                "Max: ฿500,000,000 | Cooldown: 10 min"
            )
            return

        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/pay [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return
        if amount > 500_000_000:
            await message.reply("❌ Max is ฿500,000,000!")
            return

        receiver = get_player(message.reply_to_message.from_user.id, user=message.reply_to_message.from_user)
        if int(p.user_id) == int(receiver.user_id):
            await message.reply("❌ Can't pay yourself!")
            return
        if p.bounty < amount:
            await message.reply(f"❌ Need ฿{amount:,}, have ฿{p.bounty:,}")
            return

        p.bounty -= amount
        receiver.bounty += amount
        p.pay_cd = now
        save_data()

        s_name = p.name or f"User_{p.user_id}"
        r_name = receiver.name or f"User_{receiver.user_id}"
        s_mention = (
            f"[{s_name}](https://t.me/{message.from_user.username})"
            if message.from_user.username else f"[{s_name}](tg://user?id={p.user_id})"
        )
        r_mention = (
            f"[{r_name}](https://t.me/{message.reply_to_message.from_user.username})"
            if message.reply_to_message.from_user.username
            else f"[{r_name}](tg://user?id={receiver.user_id})"
        )

        await message.reply(
            f"**PAYMENT SENT!**\n\n"
            f"From: {s_mention}\n"
            f"To: {r_mention}\n"
            f"Amount: ฿{amount:,}\n\n"
            f"{s_name}: ฿{p.bounty:,}\n"
            f"{r_name}: ฿{receiver.bounty:,}\n\n"
            f"Next payment in 10 min."
        )
        try:
            await client.send_message(
                receiver.user_id,
                f"**Received payment!**\n\n"
                f"From: {s_name}\n"
                f"Amount: ฿{amount:,}\n"
                f"Your bounty: ฿{receiver.bounty:,}"
            )
        except Exception:
            pass
