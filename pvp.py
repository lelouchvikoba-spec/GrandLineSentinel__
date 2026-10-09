# pvp.py
import asyncio
import random
import time
import uuid
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    BOT_NAME, MAIN_GROUP_ID, IMU_IMAGE,
    WIN_GIF, WIN_IMAGE, LOSE_GIF, LOSE_IMAGE,
    LEVEL_UP_IMAGE, LEVEL_UP_GIF, LEVEL_UP_GROUP_IMAGE, LEVEL_UP_GROUP_GIF,
    LEVEL_DOWN_IMAGE, LEVEL_DOWN_GIF, LEVEL_DOWN_GROUP_IMAGE, LEVEL_DOWN_GROUP_GIF,
    PVP_VICTORY_GIF, PVP_VICTORY_IMAGE, PVP_DEFEAT_GIF, PVP_DEFEAT_IMAGE,
    SHIELD_NAMES, ROB_COOLDOWN,
)
from data_manager import (
    get_player, save_data, user_data, active_challenges,
    add_trade, get_trade, remove_trade, pending_trades, get_character_by_id,
    get_rarity_emoji, get_rarity_reward_range,
    set_world_boss_active, get_world_boss_active,
    set_world_boss_hp, get_world_boss_hp,
    add_world_boss_damage, get_world_boss_damage, clear_world_boss_damage,
)
from utils import (
    check_cooldown, parse_amount, get_xp_needed, get_rank,
    can_rob_by_level, can_penetrate_shield, calc_rob_percent,
    get_conq_level, get_rob_level_range, can_bypass_pvp_off,
    can_bypass_level_restriction,
    get_armament_multiplier, get_armament_shield_ignore,
    get_conq_autowin_chance, build_mention,
)


# ==================== LEVEL UP / DOWN NOTIFICATIONS ====================
async def send_level_up_notification(app, user_id, old_level, new_level, source="game"):
    try:
        if new_level >= 200:
            medal, title = "👑🔥", "PIRATE KING!"
        elif new_level >= 180:
            medal, title = "🌊", "ADMIRAL!"
        elif new_level >= 150:
            medal, title = "👑", "YONKO COMMANDER!"
        elif new_level >= 125:
            medal, title = "⚔️", "WARLORD!"
        elif new_level >= 100:
            medal, title = "💥", "SUPERNOVA!"
        elif new_level >= 80:
            medal, title = "🗺️", "GRAND LINE TRAVELER!"
        elif new_level >= 60:
            medal, title = "🎯", "BOUNTY HUNTER!"
        elif new_level >= 40:
            medal, title = "⚓", "PIRATE APPRENTICE!"
        elif new_level >= 25:
            medal, title = "🧹", "CABIN BOY!"
        else:
            medal, title = "🏴‍☠️", "ROOKIE!"

        rank = get_rank(new_level)

        source_map = {
            "pvp_win": "PVP VICTORY",
            "pvp_loss": "PVP REVENGE",
            "game": "GAME WIN",
            "daily": "DAILY REWARD",
            "weekly": "WEEKLY REWARD",
            "claim": "CLAIM REWARD",
            "challenge": "CHARACTER DEFEATED",
            "world_boss": "WORLD BOSS",
        }
        source_label = source_map.get(source, "LEVEL UP")

        player = get_player(user_id)
        player_name = player.name or f"User {user_id}"

        caption = (
            f"{medal} **LEVEL UP!** {medal}\n\n"
            f"**{old_level}** ➜ **{new_level}**\n"
            f"Rank: {rank}\n"
            f"Title: {title}\n\n"
            f"Keep going, {player_name}!\n\n"
            f"{BOT_NAME}"
        )

        # Try static image first
        if LEVEL_UP_IMAGE:
            try:
                await app.send_photo(user_id, LEVEL_UP_IMAGE, caption=caption)
                return
            except Exception as e:
                print(f"[level up image] {e}")

        if LEVEL_UP_GIF:
            try:
                await app.send_animation(user_id, LEVEL_UP_GIF, caption=caption)
                return
            except Exception as e:
                print(f"[level up gif] {e}")

        await app.send_message(user_id, caption)
    except Exception as e:
        print(f"[level up DM] {e}")


async def send_level_up_group_notification(app, chat_id, user_name, old_level, new_level):
    try:
        caption = (
            f"🎉 **{user_name}** reached **Lv.{new_level}**! 🎉\n\n"
            f"{old_level} ➜ {new_level}"
        )

        if LEVEL_UP_GROUP_IMAGE:
            try:
                await app.send_photo(chat_id, LEVEL_UP_GROUP_IMAGE, caption=caption)
                return
            except Exception:
                pass

        if LEVEL_UP_GROUP_GIF:
            try:
                await app.send_animation(chat_id, LEVEL_UP_GROUP_GIF, caption=caption)
                return
            except Exception:
                pass
    except Exception:
        pass


async def send_level_down_notification(app, user_id, old_level, new_level, source="pvp_loss"):
    try:
        if new_level >= 180:
            medal = "🌊"
        elif new_level >= 150:
            medal = "👑"
        elif new_level >= 125:
            medal = "⚔️"
        elif new_level >= 100:
            medal = "💥"
        elif new_level >= 80:
            medal = "🗺️"
        elif new_level >= 60:
            medal = "🎯"
        elif new_level >= 40:
            medal = "⚓"
        elif new_level >= 25:
            medal = "🧹"
        else:
            medal = "🏴‍☠️"

        rank = get_rank(new_level)
        source_map = {
            "pvp_loss": "PVP DEFEAT",
            "game": "GAME LOSS",
            "challenge": "CHARACTER DEFEATED YOU",
        }
        source_label = source_map.get(source, "LEVEL DOWN")

        player = get_player(user_id)
        player_name = player.name or f"User {user_id}"

        caption = (
            f"💀 **LEVEL DOWN!** 💀\n\n"
            f"**{old_level}** ➜ **{new_level}**\n"
            f"Rank: {rank}\n\n"
            f"Train harder, {player_name}!\n\n"
            f"{BOT_NAME}"
        )

        if LEVEL_DOWN_IMAGE:
            try:
                await app.send_photo(user_id, LEVEL_DOWN_IMAGE, caption=caption)
                return
            except Exception:
                pass

        if LEVEL_DOWN_GIF:
            try:
                await app.send_animation(user_id, LEVEL_DOWN_GIF, caption=caption)
                return
            except Exception:
                pass

        await app.send_message(user_id, caption)
    except Exception as e:
        print(f"[level down DM] {e}")


async def send_level_down_group_notification(app, chat_id, user_name, old_level, new_level):
    try:
        caption = (
            f"💀 **{user_name}** dropped to **Lv.{new_level}**! 💀\n\n"
            f"{old_level} ➜ {new_level}"
        )

        if LEVEL_DOWN_GROUP_IMAGE:
            try:
                await app.send_photo(chat_id, LEVEL_DOWN_GROUP_IMAGE, caption=caption)
                return
            except Exception:
                pass

        if LEVEL_DOWN_GROUP_GIF:
            try:
                await app.send_animation(chat_id, LEVEL_DOWN_GROUP_GIF, caption=caption)
                return
            except Exception:
                pass
    except Exception:
        pass


# ==================== WORLD BOSS ====================
async def start_world_boss(app, main_group_id):
    set_world_boss_active(True)
    set_world_boss_hp(100_000_000_000)
    clear_world_boss_damage()

    msg = (
        "🌑 **WORLD BOSS APPEARED!** 🌑\n\n"
        "👑 **IMU HAS AWAKENED!** 👑\n\n"
        "💀 **HP:** 100,000,000,000\n"
        "⚔️ **Use `/battle` to attack!**"
    )
    if IMU_IMAGE:
        try:
            await app.send_photo(main_group_id, IMU_IMAGE, caption=msg)
            return
        except Exception:
            pass
    await app.send_message(main_group_id, msg)


async def end_world_boss(app, main_group_id):
    if not get_world_boss_active():
        return
    set_world_boss_active(False)

    hp = get_world_boss_hp()
    damage = get_world_boss_damage()

    if hp <= 0:
        top = sorted(damage.items(), key=lambda x: x[1], reverse=True)[:3]
        text = "🎉 **IMU DEFEATED!** 🎉\n\n**Top Damage Dealers:**\n"
        for i, (uid, dmg) in enumerate(top, 1):
            p = get_player(uid)
            p.advanced_token += 1
            text += f"{i}. `{uid}` — {dmg:,} damage +1 token\n"
        save_data()
        await app.send_message(main_group_id, text)
    else:
        await app.send_message(main_group_id, "🌑 Imu escaped! Better luck next time!")


# ==================== DM HELPERS ====================
async def _send_dm_with_gif(app, user_id, text, kind):
    if kind == "win":
        gif = PVP_VICTORY_GIF
        img = PVP_VICTORY_IMAGE
    else:
        gif = PVP_DEFEAT_GIF
        img = PVP_DEFEAT_IMAGE

    if gif:
        try:
            await app.send_animation(user_id, gif, caption=text)
            return True
        except Exception:
            pass
    if img:
        try:
            await app.send_photo(user_id, img, caption=text)
            return True
        except Exception:
            pass
    try:
        await app.send_message(user_id, text)
        return True
    except Exception:
        return False


async def send_pvp_victory_dm(app, user_id, attacker_name, target_name, steal_amount,
                              new_bounty, old_level, new_level, target_id=None,
                              target_username=None):
    try:
        target_mention = (
            build_mention(target_id, target_name, target_username)
            if target_id else target_name
        )
        text = (
            f"⚔️ **VICTORY!** ⚔️\n\n"
            f"You defeated {target_mention}! 💥\n\n"
            f"Stolen: ฿{steal_amount:,}\n"
            f"Your Bounty: ฿{new_bounty:,}\n\n"
            f"Keep going!\n\n"
            f"{BOT_NAME}"
        )
        await _send_dm_with_gif(app, user_id, text, "win")
    except Exception as e:
        print(f"[pvp victory DM] {e}")


async def send_pvp_defeat_dm(app, user_id, attacker_name, target_name, lost_amount,
                             new_bounty, old_level, new_level, attacker_id=None,
                             attacker_username=None):
    try:
        attacker_mention = (
            build_mention(attacker_id, attacker_name, attacker_username)
            if attacker_id else attacker_name
        )
        text = (
            f"💀 **DEFEAT!** 💀\n\n"
            f"You were defeated by {attacker_mention}! 💀\n\n"
            f"Lost: ฿{lost_amount:,}\n"
            f"Your Bounty: ฿{new_bounty:,}\n\n"
            f"Train harder!\n\n"
            f"{BOT_NAME}"
        )
        await _send_dm_with_gif(app, user_id, text, "lose")
    except Exception as e:
        print(f"[pvp defeat DM] {e}")


async def send_rob_attacker_dm(app, user_id, victim_id, victim_name, victim_username,
                               steal_amount, new_bounty, was_full_steal=True):
    try:
        victim_mention = build_mention(victim_id, victim_name, victim_username)
        text = (
            f"💰 **ROBBERY SUCCESSFUL!** 💰\n\n"
            f"You robbed {victim_mention}! 🏴‍☠️\n\n"
            f"Stolen: ฿{steal_amount:,}\n"
            f"Your Bounty: ฿{new_bounty:,}\n"
        )
        if not was_full_steal:
            text += f"\n*Their shield absorbed some of the blow.*"
        text += f"\n\nKeep going!\n\n{BOT_NAME}"
        await _send_dm_with_gif(app, user_id, text, "win")
    except Exception as e:
        print(f"[rob attacker DM] {e}")


async def send_rob_failed_dm(app, user_id, victim_id, victim_name, victim_username,
                             lost_amount, new_bounty):
    try:
        victim_mention = build_mention(victim_id, victim_name, victim_username)
        text = (
            f"💀 **ROBBERY FAILED!** 💀\n\n"
            f"{victim_mention} defended themselves! 🛡️\n\n"
            f"Lost: ฿{lost_amount:,}\n"
            f"Your Bounty: ฿{new_bounty:,}\n\n"
            f"Regroup and try again!\n\n"
            f"{BOT_NAME}"
        )
        await _send_dm_with_gif(app, user_id, text, "lose")
    except Exception as e:
        print(f"[rob failed DM] {e}")


async def send_rob_victim_dm(app, user_id, attacker_id, attacker_name, attacker_username,
                             steal_amount, new_bounty, pvp_was_off=False, conq_level=0):
    try:
        attacker_mention = build_mention(attacker_id, attacker_name, attacker_username)
        text = (
            f"💸 **YOU WERE ROBBED!** 💸\n\n"
            f"🏴‍☠️ {attacker_mention} **stole ฿{steal_amount:,}** from you!\n\n"
            f"Lost: ฿{steal_amount:,}\n"
            f"New Bounty: ฿{new_bounty:,}\n"
        )
        if pvp_was_off and conq_level >= 2:
            text += (
                f"\n👑 Their **Conqueror's Haki Lv.{conq_level}** "
                f"bypassed your PVP-OFF protection!"
            )
        text += f"\n\nRebuild and get revenge!\n\n{BOT_NAME}"
        await _send_dm_with_gif(app, user_id, text, "lose")
    except Exception as e:
        print(f"[rob victim DM] {e}")


async def send_defended_dm(app, user_id, attacker_id, attacker_name, attacker_username,
                           amount_won, new_bounty):
    try:
        attacker_mention = build_mention(attacker_id, attacker_name, attacker_username)
        text = (
            f"🛡️ **YOU DEFENDED YOURSELF!** 🛡️\n\n"
            f"{attacker_mention} tried to rob you — and failed!\n\n"
            f"Won: ฿{amount_won:,}\n"
            f"New Bounty: ฿{new_bounty:,}\n\n"
            f"Well defended!\n\n"
            f"{BOT_NAME}"
        )
        await _send_dm_with_gif(app, user_id, text, "win")
    except Exception as e:
        print(f"[defended DM] {e}")


# ==================== SHARED EXECUTOR ====================
async def _execute_pvp(client, message, *, is_rob: bool):
    uid = message.from_user.id
    cmd_label = "rob" if is_rob else "attack"

    if is_rob:
        attacker_pre = get_player(uid, user=message.from_user)
        now = time.time()
        if now - (attacker_pre.rob_cd or 0) < ROB_COOLDOWN:
            remaining = ROB_COOLDOWN - (now - attacker_pre.rob_cd)
            await message.reply(
                f"⏰ **Rob cooldown!**\n\n"
                f"Wait **{int(remaining // 60)}m {int(remaining % 60)}s**."
            )
            return
    else:
        can, rem = check_cooldown(uid, 25)
        if not can:
            await message.reply(f"⏰ Slow down! Wait {rem}s!")
            return

    if not message.reply_to_message:
        await message.reply(f"Reply to someone to `/{cmd_label}`!")
        return

    attacker = get_player(uid, user=message.from_user)
    target = get_player(
        message.reply_to_message.from_user.id,
        user=message.reply_to_message.from_user,
    )

    if int(attacker.user_id) == int(target.user_id):
        await message.reply("❌ Can't target yourself!")
        return

    if not attacker.pvp_enabled:
        await message.reply("❌ **Your PVP is OFF!** Enable with `/pvp`.")
        return

    pvp_bypass = False
    if not target.pvp_enabled:
        if is_rob and can_bypass_pvp_off(attacker):
            pvp_bypass = True
        else:
            hint = (
                "Conqueror's Haki Lv.2+ can bypass this."
                if is_rob else "Use `/rob` with Conq Lv.2+ to bypass."
            )
            await message.reply(
                f"❌ **{target.name or 'They'}** has PVP OFF.\n\n{hint}"
            )
            return

    if is_rob:
        if not can_rob_by_level(attacker.level, target.level):
            if not can_bypass_level_restriction(attacker):
                max_diff = get_rob_level_range(attacker.level)
                await message.reply(
                    f"❌ **Level restriction!**\n\n"
                    f"You: Lv.{attacker.level}\n"
                    f"Target: Lv.{target.level}\n"
                    f"Allowed: ±{max_diff} levels "
                    f"(Lv.{max(1, attacker.level - max_diff)}–{attacker.level + max_diff})"
                )
                return

    was_full_steal = True
    if is_rob:
        shield_ok, shield_reason, was_full_steal = can_penetrate_shield(attacker, target)
        if not shield_ok:
            target_shield = target.shield_level or 0
            attacker_conq = get_conq_level(attacker)
            await message.reply(
                f"🛡️ **Shield Blocked!**\n\n"
                f"{target.name or 'Target'} has **Shield Lv.{target_shield}** "
                f"({SHIELD_NAMES.get(target_shield, 'Unknown')})\n"
                f"Your Conq Haki: **Lv.{attacker_conq}**\n\n"
                f"{shield_reason}\n\n"
                f"Conq Lv.3 or Armament Lv.3 can smash any shield."
            )
            return

    a_name = attacker.name or f"User_{attacker.user_id}"
    t_name = target.name or f"User_{target.user_id}"
    a_mention = build_mention(attacker.user_id, a_name, attacker.username)
    t_mention = build_mention(target.user_id, t_name, target.username)

    label = "ROBBERY" if is_rob else "BATTLE"
    emoji = "💰" if is_rob else "⚔️"

    fight_msg = await message.reply(
        f"{emoji} **{label} STARTED!** {emoji}\n\n"
        f"{a_mention} vs {t_mention}\n\n"
        f"Calculating...",
        disable_web_page_preview=True,
    )
    await asyncio.sleep(0.5)

    ap = attacker.level
    tp = target.level
    ap = int(ap * get_armament_multiplier(attacker))
    tp = int(tp * get_armament_multiplier(target))

    # Crew bonus
    try:
        from crew import get_player_crew, crew_level, crew_ship_bonus
        atk_crew = get_player_crew(attacker.user_id)
        if atk_crew:
            bonus = crew_level(atk_crew) * 0.05
            bonus += crew_ship_bonus(atk_crew, "pvp_damage_bonus")
            ap = int(ap * (1 + bonus))
    except Exception:
        pass

    # Conq auto-win
    conq_chance = get_conq_autowin_chance(attacker)
    conq_note = ""
    if conq_chance > 0 and random.random() < conq_chance:
        is_victory = True
        conq_note = (
            f"\n\n👑 **{a_name}'s Conqueror's Haki "
            f"Lv.{attacker.haki_level} flared!** 👑"
        )
    else:
        is_victory = ap > tp

    pvp_bypass_note = ""
    if pvp_bypass:
        pvp_bypass_note = (
            f"\n\n👑 **Conq Lv.{get_conq_level(attacker)}** "
            f"overwhelmed {t_name}'s PVP-OFF protection!"
        )

    a_old = attacker.level
    t_old = target.level

    # ============ WIN ============
    if is_victory:
        if is_rob:
            pct = calc_rob_percent(attacker, target)
            if not was_full_steal:
                pct = 0.02
        else:
            pct = 0.10

        shield_msg = ""
        if target.passive_enabled and target.shield_level > 0 and target.shield_uses > 0:
            target.shield_uses -= 1
            shield_ignore = get_armament_shield_ignore(attacker)
            if shield_ignore >= 0.5:
                pct = 0.10
                shield_msg = f"\n\n💥 **{a_name}'s Armament Lv.3 SHATTERED the shield!**"
            else:
                pct = max(0.02, pct - 0.05)
                shield_msg = f"\n\n🛡️ **{t_name}'s SHIELD absorbed part of the blow!**"
                if target.shield_uses == 0:
                    target.shield_level = 0
                    shield_msg += f"\n💔 **Shield broke!**"

        steal = int(target.bounty * pct) if target.bounty > 0 else 0
        if steal > target.bounty:
            steal = target.bounty

        attacker.bounty += steal
        target.bounty -= steal

        xp_gain = max(0, min(50, steal // (200_000 if is_rob else 100_000))) if steal > 0 else 0
        if attacker.boost_end > time.time() and xp_gain > 0:
            xp_gain = min(75, int(xp_gain * 1.5))
        attacker.xp += xp_gain
        while attacker.xp >= get_xp_needed(attacker.level) and attacker.level < 200:
            attacker.xp -= get_xp_needed(attacker.level)
            attacker.level += 1
        if attacker.level >= 200:
            attacker.xp = 0

        xp_loss = max(0, min(50, steal // 200_000)) if steal > 0 else 0
        target.xp -= xp_loss
        while target.xp < 0 and target.level > 1:
            target.level -= 1
            target.xp += get_xp_needed(target.level)
        if target.xp < 0:
            target.xp = 0
            target.level = 1

        if is_rob:
            attacker.rob_cd = time.time()

        save_data()

        a_lt = f"\n\nLEVEL UP! {a_old} → {attacker.level}" if attacker.level > a_old else ""
        t_lt = f"\n\n{t_name} LEVEL DOWN! {t_old} → {target.level}" if target.level < t_old else ""

        result = (
            f"🎉 **{'ROBBERY SUCCESSFUL' if is_rob else 'VICTORY'}!** "
            f"{'💰' if is_rob else '⚔️'}"
            f"{conq_note}{pvp_bypass_note}{shield_msg}\n\n"
            f"{a_mention} defeated {t_mention}!\n\n"
            f"Stolen: ฿{steal:,}\n"
            f"XP: +{xp_gain}\n"
            f"Your bounty: ฿{attacker.bounty:,}"
            f"{a_lt}{t_lt}"
        )

        await fight_msg.delete()
        sent = False
        if WIN_GIF:
            try:
                await message.reply_animation(WIN_GIF, caption=result)
                sent = True
            except Exception:
                pass
        if not sent and WIN_IMAGE:
            try:
                await message.reply_photo(WIN_IMAGE, caption=result)
                sent = True
            except Exception:
                pass
        if not sent:
            await message.reply(result)

        # DMs
        if is_rob:
            asyncio.create_task(send_rob_attacker_dm(
                client, attacker.user_id, target.user_id, t_name, target.username,
                steal, attacker.bounty, was_full_steal,
            ))
            asyncio.create_task(send_rob_victim_dm(
                client, target.user_id, attacker.user_id, a_name, attacker.username,
                steal, target.bounty, pvp_bypass, get_conq_level(attacker),
            ))
        else:
            asyncio.create_task(send_pvp_victory_dm(
                client, attacker.user_id, a_name, t_name, steal,
                attacker.bounty, a_old, attacker.level,
                target_id=target.user_id, target_username=target.username,
            ))
            asyncio.create_task(send_pvp_defeat_dm(
                client, target.user_id, a_name, t_name, steal,
                target.bounty, t_old, target.level,
                attacker_id=attacker.user_id, attacker_username=attacker.username,
            ))

        if attacker.level > a_old:
            asyncio.create_task(send_level_up_notification(
                client, attacker.user_id, a_old, attacker.level, "pvp_win"
            ))
            asyncio.create_task(send_level_up_group_notification(
                client, message.chat.id, a_name, a_old, attacker.level
            ))
        if target.level < t_old:
            asyncio.create_task(send_level_down_notification(
                client, target.user_id, t_old, target.level, "pvp_loss"
            ))
            asyncio.create_task(send_level_down_group_notification(
                client, message.chat.id, t_name, t_old, target.level
            ))

    # ============ LOSS ============
    else:
        pct = 0.05 if is_rob else 0.10

        shield_msg = ""
        if attacker.passive_enabled and attacker.shield_level > 0 and attacker.shield_uses > 0:
            attacker.shield_uses -= 1
            shield_ignore = get_armament_shield_ignore(target)
            if shield_ignore >= 0.5:
                pct = 0.10
                shield_msg = f"\n\n💥 **{t_name}'s Armament Lv.3 SHATTERED your shield!**"
            else:
                pct = max(0.02, pct - 0.05)
                shield_msg = f"\n\n🛡️ **Your SHIELD absorbed part of the blow!**"
                if attacker.shield_uses == 0:
                    attacker.shield_level = 0
                    shield_msg += "\n💔 **Shield broke!**"

        steal = int(attacker.bounty * pct) if attacker.bounty > 0 else 0
        if steal > attacker.bounty:
            steal = attacker.bounty

        target.bounty += steal
        attacker.bounty -= steal

        xp_loss = max(0, min(50, steal // (200_000 if is_rob else 100_000))) if steal > 0 else 0
        attacker.xp -= xp_loss
        while attacker.xp < 0 and attacker.level > 1:
            attacker.level -= 1
            attacker.xp += get_xp_needed(attacker.level)
        if attacker.xp < 0:
            attacker.xp = 0
            attacker.level = 1

        xp_gain = max(0, min(50, steal // 200_000)) if steal > 0 else 0
        if target.boost_end > time.time() and xp_gain > 0:
            xp_gain = min(75, int(xp_gain * 1.5))
        target.xp += xp_gain
        while target.xp >= get_xp_needed(target.level) and target.level < 200:
            target.xp -= get_xp_needed(target.level)
            target.level += 1
        if target.level >= 200:
            target.xp = 0

        if is_rob:
            attacker.rob_cd = time.time()

        save_data()

        a_lt = f"\n\nLEVEL DOWN! {a_old} → {attacker.level}" if attacker.level < a_old else ""
        t_lt = f"\n\n{t_name} LEVEL UP! {t_old} → {target.level}" if target.level > t_old else ""

        result = (
            f"💀 **{'ROBBERY FAILED' if is_rob else 'DEFEAT'}!** 💀"
            f"{conq_note}{pvp_bypass_note}{shield_msg}\n\n"
            f"{a_mention} lost to {t_mention}!\n\n"
            f"Lost: ฿{steal:,}\n"
            f"XP lost: -{xp_loss}\n"
            f"Your bounty: ฿{attacker.bounty:,}"
            f"{a_lt}{t_lt}"
        )

        await fight_msg.delete()
        sent = False
        if LOSE_GIF:
            try:
                await message.reply_animation(LOSE_GIF, caption=result)
                sent = True
            except Exception:
                pass
        if not sent and LOSE_IMAGE:
            try:
                await message.reply_photo(LOSE_IMAGE, caption=result)
                sent = True
            except Exception:
                pass
        if not sent:
            await message.reply(result)

        if is_rob:
            asyncio.create_task(send_rob_failed_dm(
                client, attacker.user_id, target.user_id, t_name, target.username,
                steal, attacker.bounty,
            ))
            asyncio.create_task(send_defended_dm(
                client, target.user_id, attacker.user_id, a_name, attacker.username,
                steal, target.bounty,
            ))
        else:
            asyncio.create_task(send_pvp_defeat_dm(
                client, attacker.user_id, t_name, a_name, steal,
                attacker.bounty, a_old, attacker.level,
                attacker_id=target.user_id, attacker_username=target.username,
            ))
            asyncio.create_task(send_pvp_victory_dm(
                client, target.user_id, t_name, a_name, steal,
                target.bounty, t_old, target.level,
                target_id=attacker.user_id, target_username=attacker.username,
            ))

        if attacker.level < a_old:
            asyncio.create_task(send_level_down_notification(
                client, attacker.user_id, a_old, attacker.level, "pvp_loss"
            ))
            asyncio.create_task(send_level_down_group_notification(
                client, message.chat.id, a_name, a_old, attacker.level
            ))
        if target.level > t_old:
            asyncio.create_task(send_level_up_notification(
                client, target.user_id, t_old, target.level, "pvp_win"
            ))
            asyncio.create_task(send_level_up_group_notification(
                client, message.chat.id, t_name, t_old, target.level
            ))


# ==================== REGISTER ====================
def register_pvp(app):

    @app.on_message(filters.command("attack"))
    async def attack_cmd(client, message):
        await _execute_pvp(client, message, is_rob=False)

    @app.on_message(filters.command("rob"))
    async def rob_cmd(client, message):
        await _execute_pvp(client, message, is_rob=True)

    # ==================== /battle (World Boss) ====================
    @app.on_message(filters.command("battle"))
    async def battle_cmd(client, message):
        if not get_world_boss_active():
            await message.reply("🌑 No active World Boss! Next raid at 10 PM.")
            return
        if get_world_boss_hp() <= 0:
            await message.reply("World Boss already defeated!")
            return

        p = get_player(message.from_user.id, user=message.from_user)
        dmg = p.level * 1000
        if p.haki == "arm":
            dmg = int(dmg * (1 + p.haki_level * 0.3))
        if p.devil_fruit and p.fruit_category == "Good":
            dmg = int(dmg * 1.5)

        new_hp = get_world_boss_hp() - dmg
        set_world_boss_hp(new_hp)
        add_world_boss_damage(message.from_user.id, dmg)

        old_lvl = p.level
        xp = max(1, min(50, dmg // 10_000))
        p.xp += xp
        while p.xp >= get_xp_needed(p.level) and p.level < 200:
            p.xp -= get_xp_needed(p.level)
            p.level += 1
        if p.level >= 200:
            p.xp = 0

        save_data()

        lt = f"\n\nLEVEL UP! {old_lvl} → {p.level}" if p.level > old_lvl else ""
        if p.level > old_lvl:
            asyncio.create_task(send_level_up_notification(
                client, message.from_user.id, old_lvl, p.level, "world_boss"
            ))
            asyncio.create_task(send_level_up_group_notification(
                client, message.chat.id, p.name, old_lvl, p.level
            ))

        await message.reply(
            f"⚔️ **You attacked IMU!**\n"
            f"Damage: {dmg:,}\n"
            f"XP: +{xp}\n"
            f"Boss HP: {max(0, new_hp):,}{lt}"
        )

        if new_hp <= 0:
            await end_world_boss(client, MAIN_GROUP_ID)

    # ==================== /challenge ====================
    @app.on_message(filters.command("challenge"))
    async def challenge_cmd(client, message):
        chat_id = message.chat.id
        uid = message.from_user.id

        if chat_id not in active_challenges:
            await message.reply("❌ **No character here!** Wait for one to spawn (every 150 messages).")
            return

        challenge = active_challenges[chat_id]
        if challenge.get("challenger") is not None:
            await message.reply("Someone is already challenging this character!")
            return

        args = message.text.split()
        if len(args) < 2:
            await message.reply("Type `/challenge `[name]!")
            return

        guessed = " ".join(args[1:]).lower().strip()
        actual = challenge["char"].get("name", "").lower()
        parts = actual.split()

        is_match = False
        if guessed == actual:
            is_match = True
        elif guessed in parts:
            is_match = True
        elif len(guessed) >= 3 and (
            actual.startswith(guessed)
            or actual.endswith(guessed)
            or guessed in actual
        ):
            is_match = True

        if not is_match:
            time_left = max(0, 300 - (time.time() - challenge["spawn_time"]))
            await message.reply(
                f"❌ **Wrong guess!**\n"
                f"{int(time_left // 60)}m {int(time_left % 60)}s left"
            )
            return

        challenge["challenger"] = uid

        p = get_player(uid, user=message.from_user)
        char_name = challenge["char"].get("name", "?")
        challenged_char = challenge.get("char", {})
        char_id = challenged_char.get("id")
        prior_count = sum(
            1 for c in p.captured_chars
            if (c.get("id") == char_id if char_id is not None else c.get("name") == char_name)
        )

        await message.reply(
            f"⚔️ **{message.from_user.first_name}** challenges **{char_name}**!\n"
            f"Fighting..."
        )
        await asyncio.sleep(1.5)

        challenge_rarity = str(challenge.get("rarity", "MYTHICAL" if challenge.get("is_mythical") else "NORMAL")).upper()
        configured_chance = challenged_char.get("win_chance")
        if configured_chance is not None:
            try:
                win_chance = max(0.0, min(1.0, float(configured_chance) / 100))
            except (TypeError, ValueError):
                configured_chance = None
        if configured_chance is None:
            if challenge_rarity == "MYTHICAL":
                win_chance = min(0.8, 0.1 + (p.level / 500) + (p.haki_level * 0.05))
            else:
                win_chance = min(0.95, 0.4 + (p.level / 200) + (p.haki_level * 0.05))
        if challenge_rarity == "MYTHICAL":
            reward_xp = 5000
            reward_token = 1
        else:
            reward_xp = random.randint(50, 500)
            reward_token = 0
        reward_min, reward_max = get_rarity_reward_range(challenge_rarity)
        reward_bounty = random.randint(reward_min, reward_max)

        win = random.random() < win_chance
        new_count = prior_count + (1 if win else 0)

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"Challenged {char_name} x{new_count}",
                callback_data="noop",
            )
        ]])

        if win:
            full = get_character_by_id(char_id) if char_id is not None else None
            if not full:
                active_challenges.pop(chat_id, None)
                await message.reply(
                    f"❌ **{char_name}** is no longer available, so it was not captured."
                )
                return
            char_name = full.get("name", char_name)
            challenge_rarity = str(full.get("rarity", challenge_rarity)).upper()
            p.captured_chars.append({
                "id": full.get("id"),
                "name": full["name"],
                "image": full.get("image"),
                "media_type": full.get("media_type", "photo"),
                "rarity": full.get("rarity", challenge_rarity),
                "captured_at": time.time(),
            })

            p.bounty += reward_bounty
            p.xp += min(50, reward_xp)
            p.advanced_token += reward_token

            old_lvl = p.level
            while p.xp >= get_xp_needed(p.level) and p.level < 200:
                p.xp -= get_xp_needed(p.level)
                p.level += 1
            if p.level >= 200:
                p.xp = 0

            save_data()

            if p.level > old_lvl:
                await send_level_up_notification(client, uid, old_lvl, p.level, "challenge")
                await send_level_up_group_notification(client, message.chat.id, p.name, old_lvl, p.level)

            reward_txt = f"Bounty: +฿{reward_bounty:,}\nXP: +{min(50, reward_xp)}"
            if reward_token:
                reward_txt += f"\nToken: +{reward_token}"
            lt = f"\n\nLEVEL UP! {old_lvl} → {p.level}" if p.level > old_lvl else ""

            await message.reply(
                f"🎉 **VICTORY!** 🎉\n\n"
                f"Defeated **{char_name}**!\n"
                f"🆔 Character ID: `{char_id}`\n\n"
                f"**Rewards:**\n{reward_txt}{lt}",
                reply_markup=kb,
            )
        else:
            xp_loss = max(1, min(50, reward_xp // 2))
            p.xp -= xp_loss
            old_lvl = p.level
            while p.xp < 0 and p.level > 1:
                p.level -= 1
                p.xp += get_xp_needed(p.level)
            if p.xp < 0:
                p.xp = 0
                p.level = 1
            save_data()

            if p.level < old_lvl:
                await send_level_down_notification(client, uid, old_lvl, p.level, "challenge")
                await send_level_down_group_notification(client, message.chat.id, p.name, old_lvl, p.level)

            lt = f"\n\nLEVEL DOWN! {old_lvl} → {p.level}" if p.level < old_lvl else ""
            await message.reply(
                f"💀 **DEFEAT!**\n\n"
                f"Defeated by **{char_name}**!\n"
                f"-{xp_loss} XP{lt}",
                reply_markup=kb,
            )

        active_challenges.pop(chat_id, None)

    # ==================== /timeleft ====================
    @app.on_message(filters.command("timeleft"))
    async def timeleft_cmd(client, message):
        chat_id = message.chat.id
        if chat_id not in active_challenges:
            await message.reply("❌ No active character!")
            return

        ch = active_challenges[chat_id]
        left = max(0, 300 - (time.time() - ch["spawn_time"]))
        status_rarity = ch.get("rarity", "MYTHICAL" if ch.get("is_mythical") else "NORMAL")
        await message.reply(
            f"**Character Status**\n\n"
            f"{get_rarity_emoji(status_rarity)} {ch['char'].get('name', '?')}\n"
            f"{status_rarity}\n\n"
            f"{int(left // 60)}m {int(left % 60)}s left\n\n"
            f"`/challenge `[name]"
        )

   # ==================== /trade ====================
    @app.on_message(filters.command("trade"))
    async def trade_cmd(client, message):
        uid = message.from_user.id

        if not message.reply_to_message:
            await message.reply(
                "**TRADE**\n\n"
                "Buyer replies to a seller with `/trade [price]`\n\n"
                "1. Seller accepts or cancels\n"
                "2. Buyer chooses a character from the seller\n"
                "3. Seller reviews and confirms the final trade\n\n"
                f"{BOT_NAME}"
            )
            return

        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: `/trade [amount]`")
            return

        amount = parse_amount(args[1])
        if amount is None or amount <= 0:
            await message.reply("❌ Invalid amount!")
            return

        buyer = get_player(uid, user=message.from_user)
        seller = get_player(
            message.reply_to_message.from_user.id,
            user=message.reply_to_message.from_user,
        )

        if int(seller.user_id) == int(buyer.user_id):
            await message.reply("❌ Can't trade with yourself!")
            return

        if not seller.captured_chars:
            await message.reply("❌ The seller doesn't have any characters to sell!")
            return

        if buyer.bounty < amount:
            await message.reply(
                f"❌ Buyer needs ฿{amount:,}!\nThey have ฿{buyer.bounty:,}"
            )
            return

        trade_id = uuid.uuid4().hex[:12]

        for char in seller.captured_chars:
            if not char.get("id"):
                master = get_character_by_name(char.get("name", ""))
                if master:
                    char["id"] = master.get("id")

        trade_data = {
            "seller_id": seller.user_id,
            "buyer_id": buyer.user_id,
            "amount": amount,
            "chars": [],
            "selected_char": None,
            "selected_index": None,
            "seller_accepted": False,
            "timestamp": time.time(),
        }
        add_trade(trade_id, trade_data)

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Accept", callback_data=f"trade_accept_{trade_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"trade_cancel_{trade_id}"),
        ]])

        s_name = seller.name or f"User_{seller.user_id}"
        b_name = buyer.name or f"User_{buyer.user_id}"

        await message.reply(
            f"**TRADE OFFER**\n\n"
            f"Seller: {s_name}\n"
            f"Buyer: {b_name}\n"
            f"Price: ฿{amount:,}\n"
            f"Seller, accept or cancel this offer.\n\n"
            f"Expires in 2 min",
            reply_markup=kb,
        )
