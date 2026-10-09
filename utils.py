# utils.py
import os
import time
import random

# Safe PIL import
PIL_AVAILABLE = True
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    from io import BytesIO
except ImportError:
    PIL_AVAILABLE = False

from config import FONTS_DIR, WANTED_IMAGE


last_command_time = {}


# ==================== BASIC HELPERS ====================
def check_cooldown(user_id, cooldown_seconds=2):
    now = time.time()
    if user_id in last_command_time:
        elapsed = now - last_command_time[user_id]
        if elapsed < cooldown_seconds:
            return False, round(cooldown_seconds - elapsed, 1)
    last_command_time[user_id] = now
    return True, 0


def parse_amount(amount_str):
    try:
        cleaned = amount_str.replace(",", "").strip()
        if not cleaned:
            return None
        return int(float(cleaned))
    except (ValueError, AttributeError, TypeError):
        return None


# ==================== NUMBER ABBREVIATION ====================
_AMOUNT_UNITS = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc"]


def format_short_amount(value):
    """Abbreviate a big number so it always stays short:
    999 -> '999', 1500000 -> '1M', 2500000000000 -> '2T', 10**18 -> '1Qi'.
    Uses 1000-based suffixes (K, M, B, T, Qa, Qi, ...) so even a
    quadrillion / quintillion bounty is only 2-4 characters long."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "0"
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a < 1000:
        return f"{sign}{a:,}"
    i = 0
    while a >= 1000 and i < len(_AMOUNT_UNITS) - 1:
        a //= 1000
        i += 1
    return f"{sign}{a:,}{_AMOUNT_UNITS[i]}"


# ==================== ONE-TAP COPY BUTTONS ====================
def build_copy_markup(pairs):
    """Build an inline keyboard of one-tap copy buttons.

    Copy buttons need Telegram 7.11+ AND a Pyrogram build that exposes
    InlineKeyboardButton(copy_text=...).  When either is missing this simply
    returns None, so the caller keeps sending a normal message with no
    broken/empty buttons."""
    try:
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        InlineKeyboardButton("copy", copy_text="0")
    except Exception:
        return None
    try:
        rows = [
            [InlineKeyboardButton(label, copy_text=str(value))]
            for label, value in pairs
            if value not in (None, "")
        ]
        return InlineKeyboardMarkup(rows) if rows else None
    except Exception:
        return None


def get_xp_needed(level):
    return 100 + (level * 10)


def get_rank(level):
    if level <= 10: return "🏴‍☠️ Rookie Pirate"
    if level <= 25: return "🧹 Cabin Boy"
    if level <= 40: return "⚓ Pirate Apprentice"
    if level <= 60: return "🎯 Bounty Hunter"
    if level <= 80: return "🗺️ Grand Line Traveler"
    if level <= 100: return "💥 Supernova"
    if level <= 125: return "⚔️ Warlord of the Sea"
    if level <= 150: return "👑 Yonko Commander"
    if level <= 180: return "🌊 Marine Admiral"
    if level < 200: return "🏴‍☠️ Pirate King Candidate"
    return "👑🔥 Pirate King"


def get_random_fruit(tier):
    from config import DEVIL_FRUITS
    if tier == 1:
        category = random.choice(["Bad", "Medium"])
    elif tier == 2:
        category = random.choices(["Bad", "Medium", "Good"], weights=[30, 40, 30])[0]
    else:
        category = random.choices(["Medium", "Good"], weights=[30, 70])[0]
    pool = DEVIL_FRUITS[category]
    return random.choice(pool), category


def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


# ==================== MENTIONS ====================
def _sanitize_md(text):
    if not text:
        return text
    for ch in ("[", "]", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text


def build_mention(user_id, name=None, username=None):
    safe_name = _sanitize_md((name or f"User {user_id}").strip())
    if username:
        uname = username.lstrip("@")
        return f"[{safe_name}](https://t.me/{uname})"
    return f"[{safe_name}](tg://user?id={user_id})"


def display_name(player, fallback_prefix="User"):
    if not player:
        return "Unknown"
    if player.name:
        return player.name
    if player.username:
        return f"@{player.username}"
    return f"{fallback_prefix} {player.user_id}"


# ==================== FONT LOADING ====================
def load_name_font(size, text=None):
    if not PIL_AVAILABLE:
        return None
    text = str(text or "")
    has_myanmar = any("\u1000" <= ch <= "\u109f" for ch in text)
    has_non_latin = any(ord(ch) > 0x024f for ch in text)
    font_paths = []
    if has_myanmar:
        font_paths.extend([
            os.path.join(FONTS_DIR, "NotoSansMyanmar-Regular.ttf"),
            os.path.join(FONTS_DIR, "Padauk-Regular.ttf"),
        ])
    elif has_non_latin:
        font_paths.append(os.path.join(FONTS_DIR, "NotoSans-Regular.ttf"))
    font_paths.extend([
        os.path.join(FONTS_DIR, "times_new_roman_extra_bold.ttf"),
        os.path.join(FONTS_DIR, "TimesNewRomanExtraBold.ttf"),
        os.path.join(FONTS_DIR, "TimesNewRoman-Bold.ttf"),
        os.path.join(FONTS_DIR, "times.ttf"),
        os.path.join(FONTS_DIR, "arial.ttf"),
    ])
    for path in font_paths:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def load_bounty_font(size):
    if not PIL_AVAILABLE:
        return None
    font_paths = [
        os.path.join(FONTS_DIR, "Vrinda.ttf"),
        os.path.join(FONTS_DIR, "vrinda.ttf"),
        os.path.join(FONTS_DIR, "Vrinda Regular.ttf"),
        os.path.join(FONTS_DIR, "arial.ttf"),
    ]
    for path in font_paths:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


# ==================== PATTERN HELPERS ====================
def get_pattern_result(game, user_id, default_choice_fn):
    """Get a game result based on current pattern."""
    from data_manager import (
        get_current_pattern, get_sequence_position, advance_sequence,
    )
    from config import PATTERNS

    pattern = get_current_pattern()
    info = PATTERNS.get(pattern)

    if info and info.get("mode") == "sequence":
        seqs = info.get("sequences", {})
        seq = seqs.get(game)
        if seq:
            pos = get_sequence_position(user_id, game)
            result = seq[pos % len(seq)]
            advance_sequence(user_id, game, len(seq))
            return result

    return default_choice_fn()


# ==================== HAKI BAR ====================
def _regen_haki_bar(player):
    from config import HAKI_REGEN_NORMAL, HAKI_REGEN_ADVANCED, HAKI_BAR_MAX
    import time as _t

    if player.haki_bar >= HAKI_BAR_MAX:
        player.haki_bar = HAKI_BAR_MAX
        return

    if player.haki_bar_updated == 0:
        player.haki_bar_updated = _t.time()
        return

    now = _t.time()
    elapsed = now - player.haki_bar_updated

    regen_time = HAKI_REGEN_ADVANCED if player.haki_is_advanced else HAKI_REGEN_NORMAL
    seconds_per_block = regen_time / HAKI_BAR_MAX
    blocks_restored = int(elapsed // seconds_per_block)

    if blocks_restored > 0:
        player.haki_bar = min(HAKI_BAR_MAX, player.haki_bar + blocks_restored)
        player.haki_bar_updated += blocks_restored * seconds_per_block
        if player.haki_bar >= HAKI_BAR_MAX:
            player.haki_bar = HAKI_BAR_MAX
            player.haki_bar_updated = now


def get_haki_bar(player):
    _regen_haki_bar(player)
    return player.haki_bar or 0


def get_haki_bar_visual(player):
    bar = get_haki_bar(player)
    filled = int(bar)
    return "█" * filled + "░" * (10 - filled)


def consume_haki_use(player, cost=None):
    from config import HAKI_BAR_PER_USE
    _regen_haki_bar(player)
    cost = HAKI_BAR_PER_USE if cost is None else max(1, int(cost))
    if player.haki_bar < cost:
        return False
    player.haki_bar -= cost
    import time as _t
    if player.haki_bar_updated == 0:
        player.haki_bar_updated = _t.time()
    return True


def seconds_until_full(player):
    from config import HAKI_REGEN_NORMAL, HAKI_REGEN_ADVANCED, HAKI_BAR_MAX
    import time as _t
    _regen_haki_bar(player)
    missing = HAKI_BAR_MAX - player.haki_bar
    if missing <= 0:
        return 0
    regen = HAKI_REGEN_ADVANCED if player.haki_is_advanced else HAKI_REGEN_NORMAL
    return int((regen / HAKI_BAR_MAX) * missing)


# ==================== HAKI EFFECTS ====================
def get_haki_level(player, haki_type):
    if not player or player.haki != haki_type:
        return 0
    if not getattr(player, "haki_active", False):
        return 0
    if getattr(player, "haki_is_advanced", False):
        return 4
    return min(player.haki_level or 0, 3)


def is_haki_active(player):
    return bool(player and getattr(player, "haki_active", False))


def is_advanced_haki(player):
    return bool(player and getattr(player, "haki_is_advanced", False))


def get_haki_use_cost(player):
    from config import HAKI_BAR_PER_USE, ADV_ARMAMENT_RECOVERY_BAR_COST
    if player and getattr(player, "haki", None) == "arm" and is_advanced_haki(player):
        return ADV_ARMAMENT_RECOVERY_BAR_COST
    return HAKI_BAR_PER_USE


def get_observation_win_rate(player):
    from config import OBSERVATION_WIN_RATES
    lvl = get_haki_level(player, "obv")
    return OBSERVATION_WIN_RATES.get(lvl)


def get_observation_money_mult(player):
    from config import OBSERVATION_ADV_MONEY_MULTIPLIER
    if get_haki_level(player, "obv") >= 4:
        return OBSERVATION_ADV_MONEY_MULTIPLIER
    return 1.0


def get_armament_recovery(player):
    from config import ARMAMENT_RECOVERY
    lvl = get_haki_level(player, "arm")
    return ARMAMENT_RECOVERY.get(lvl, 0.0)


def get_conq_shield_bypass(player):
    from config import CONQ_SHIELD_BYPASS
    lvl = get_haki_level(player, "conq")
    return CONQ_SHIELD_BYPASS.get(lvl, 0)


def can_bypass_pvp_off(player):
    from config import CONQ_PVP_BYPASS_LEVEL
    return get_haki_level(player, "conq") >= CONQ_PVP_BYPASS_LEVEL


def can_bypass_level_restriction(player):
    from config import CONQ_LEVEL_BYPASS_LEVEL
    return get_haki_level(player, "conq") >= CONQ_LEVEL_BYPASS_LEVEL


def get_conq_level(player):
    return get_haki_level(player, "conq")


def get_dart_threshold(player):
    from config import OBSERVATION_THRESHOLDS
    lvl = get_haki_level(player, "obv")
    return OBSERVATION_THRESHOLDS.get(lvl, 4)


def get_armament_multiplier(player):
    from config import ARMAMENT_MULTIPLIERS
    lvl = get_haki_level(player, "arm")
    return ARMAMENT_MULTIPLIERS.get(lvl, 1.0)


def get_armament_shield_ignore(player):
    from config import ARMAMENT_ADV_SHIELD_IGNORE
    if get_haki_level(player, "arm") >= 3:
        return ARMAMENT_ADV_SHIELD_IGNORE
    return 0.0


def get_conq_autowin_chance(player):
    from config import CONQ_AUTOWIN_CHANCE
    lvl = get_haki_level(player, "conq")
    return CONQ_AUTOWIN_CHANCE.get(lvl, 0.0)


# ==================== SHIELD PENETRATION ====================
def can_penetrate_shield(attacker, target):
    from config import SHIELD_PENETRATION

    target_shield = target.shield_level or 0
    if target_shield == 0:
        return True, "no shield", True

    # Armament Lv.3 smashes shield Lv.3
    if target_shield >= 3 and get_haki_level(attacker, "arm") >= 3:
        return True, "Armament Lv.3 shattered the shield", True

    attacker_bypass = get_conq_shield_bypass(attacker)

    if attacker_bypass == 0:
        return False, (
            f"You need Conqueror's Haki to bypass Shield Lv.{target_shield}"
        ), False

    if attacker_bypass >= target_shield:
        is_full = attacker_bypass >= 99
        return True, (
            f"Conq Lv.{get_conq_level(attacker)} bypassed Shield Lv.{target_shield}"
            + (" (full bounty)" if is_full else " (reduced bounty)")
        ), is_full

    return False, (
        f"Shield Lv.{target_shield} blocks Conq Lv.{get_conq_level(attacker)}"
    ), False


# ==================== ROB HELPERS ====================
def get_rob_level_range(attacker_level):
    from config import ROB_LEVEL_RANGES
    for low, high, diff in ROB_LEVEL_RANGES:
        if low <= attacker_level <= high:
            return diff
    return 30


def can_rob_by_level(attacker_level, target_level):
    max_diff = get_rob_level_range(attacker_level)
    return abs(attacker_level - target_level) <= max_diff


def calc_rob_percent(attacker, target):
    from config import ROB_BASE_PERCENT, ROB_CONQ_BONUS_PER_LEVEL, ROB_MAX_PERCENT

    target_shield = target.shield_level or 0
    attacker_conq = get_conq_level(attacker)

    pct = ROB_BASE_PERCENT
    if target_shield > 0:
        excess = max(0, attacker_conq - target_shield)
        pct += excess * ROB_CONQ_BONUS_PER_LEVEL
    else:
        pct += attacker_conq * ROB_CONQ_BONUS_PER_LEVEL

    return min(pct, ROB_MAX_PERCENT)
