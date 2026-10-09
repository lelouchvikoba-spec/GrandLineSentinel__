# data_manager.py
import json
import os
import tempfile
import threading
import time
from datetime import datetime
import asyncio
from collections import defaultdict

from config import (
    USERS_FILE, NORMAL_CHARS_FILE, MYTHICAL_CHARS_FILE, EXALTED_CHARS_FILE, RARITIES_FILE,
    GBANNED_FILE, TEMP_BANNED_FILE, ADMINS_FILE, OWNER_ID, DATA_DIR,
    DEFAULT_PATTERN, TIMEZONE,
)
from models import Player

# ==================== GLOBAL STATE ====================
user_data = {}
normal_characters = []
mythical_characters = []
exalted_characters = []
custom_rarities = []
rarity_settings = {
    "NORMAL": {"emoji": "💠", "chance": 90.0, "reward_min": 10_000, "reward_max": 500_000},
    "MYTHICAL": {"emoji": "👹", "chance": 10.0, "reward_min": 10_000_000_000, "reward_max": 10_000_000_000},
    "EXALTED": {"emoji": "👑", "chance": 0.0, "reward_min": 25_000_000_000, "reward_max": 50_000_000_000},
}
active_challenges = {}
message_count = defaultdict(int)
pending_trades = {}
GBANNED = set()
TEMP_BANNED = {}
ADMINS = set()
bot_groups = set()
banned_players_info = {}

# World Boss
world_boss_active = False
world_boss_hp = 0
world_boss_damage = defaultdict(int)

# Giveaways
active_giveaways = {}
active_global_giveaway = None

# Pending forwards
pending_forwards = {}

# Pattern state
current_pattern = DEFAULT_PATTERN

pattern_override = {
    "active": False,
    "pattern": None,
    "expires_at": 0,
}

sequence_positions = {
    "__global__": {"bet": 0, "dice": 0},
}

# Files
PATTERN_STATE_FILE = os.path.join(DATA_DIR, "pattern_state.json")
CHAR_ID_COUNTER_FILE = os.path.join(DATA_DIR, "char_id_counter.json")
GROUP_CACHE_FILE = os.path.join(DATA_DIR, "group_cache.json")

_char_id_lock = threading.Lock()
group_cache = {}

# Per-group character-drop thresholds (messages between spawns)
group_settings = {}
GROUP_SETTINGS_FILE = os.path.join(DATA_DIR, "group_settings.json")
DEFAULT_DROP_COUNT = 150
ALLOWED_DROP_COUNTS = (50, 100, 150, 200)


# ==================== CHANNEL STORAGE HOOK ====================
_channel_client = None
_last_sync = {}
SYNC_COOLDOWN = 60  # seconds between uploads of the same file


def set_channel_client(client):
    """Called from bot.py at startup to enable channel sync."""
    global _channel_client
    _channel_client = client


async def _do_upload(client, path, fname):
    """Upload + cleanup in one go."""
    try:
        from channel_storage import upload_gzipped, delete_old_from_channel
        await upload_gzipped(client, path, fname)
        await delete_old_from_channel(client, fname, keep=3)
    except Exception as e:
        print(f"[data_manager] upload error ({fname}): {e}")


def _sync_to_channel(fname):
    """Trigger a background upload of a file to the storage channel."""
    if not _channel_client:
        return
    now = time.time()
    if now - _last_sync.get(fname, 0) < SYNC_COOLDOWN:
        return
    _last_sync[fname] = now

    try:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = getattr(_channel_client, "loop", None)
            if loop is None:
                return

        loop.create_task(_do_upload(_channel_client, path, fname))
    except Exception as e:
        print(f"[data_manager] sync error ({fname}): {e}")


# ==================== ATOMIC WRITE ====================
def _atomic_json_write(path, payload):
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_name, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


# ==================== PATTERN STATE ====================
def save_pattern_state():
    try:
        _atomic_json_write(PATTERN_STATE_FILE, {
            "current_pattern": current_pattern,
            "pattern_override": pattern_override,
            "sequence_positions": sequence_positions,
        })
        _sync_to_channel("pattern_state.json")
    except Exception as e:
        print(f"[pattern] save failed: {e}")


def load_pattern_state():
    global current_pattern, pattern_override, sequence_positions
    try:
        with open(PATTERN_STATE_FILE, "r") as f:
            data = json.load(f)

        current_pattern = data.get("current_pattern", DEFAULT_PATTERN)

        # Mutate in place so imported references stay valid
        new_override = data.get("pattern_override", {
            "active": False, "pattern": None, "expires_at": 0,
        })
        pattern_override.clear()
        pattern_override.update(new_override)

        new_seq = data.get("sequence_positions", {
            "__global__": {"bet": 0, "dice": 0},
        })
        sequence_positions.clear()
        sequence_positions.update(new_seq)

        print(f"[DEBUG] Loaded pattern state: {current_pattern}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[pattern] load failed: {e}")


def get_current_pattern():
    import time as _t
    from config import TIME_SCHEDULE, AUTO_SWITCH_ENABLED
    from datetime import datetime

    if pattern_override.get("active"):
        if _t.time() < pattern_override.get("expires_at", 0):
            return pattern_override["pattern"]
        pattern_override["active"] = False
        pattern_override["pattern"] = None
        pattern_override["expires_at"] = 0
        save_pattern_state()

    if AUTO_SWITCH_ENABLED:
        hour = datetime.now().hour
        auto = TIME_SCHEDULE.get(hour)
        if auto:
            return auto

    return DEFAULT_PATTERN


def set_current_pattern(p, manual=False):
    global current_pattern
    import time as _t

    if p not in ("pattern1", "pattern2", "pattern3", "pattern4"):
        return False

    if manual:
        from config import PATTERN_OVERRIDE_HOURS
        pattern_override["active"] = True
        pattern_override["pattern"] = p
        pattern_override["expires_at"] = _t.time() + (PATTERN_OVERRIDE_HOURS * 3600)
    else:
        current_pattern = p

    save_pattern_state()
    return True


def clear_pattern_override():
    pattern_override["active"] = False
    pattern_override["pattern"] = None
    pattern_override["expires_at"] = 0
    save_pattern_state()


def get_pattern_override():
    return pattern_override


def get_override_status():
    import time as _t
    if not pattern_override.get("active"):
        return {"active": False}
    remaining = max(0, int(pattern_override.get("expires_at", 0) - _t.time()))
    return {
        "active": True,
        "pattern": pattern_override.get("pattern"),
        "remaining_seconds": remaining,
    }


def get_sequence_position(user_id, game):
    key = str(user_id) if user_id else "__global__"
    if key not in sequence_positions:
        sequence_positions[key] = {}
    return sequence_positions[key].get(game, 0)


def advance_sequence(user_id, game, sequence_length):
    key = str(user_id) if user_id else "__global__"
    if key not in sequence_positions:
        sequence_positions[key] = {}
    pos = sequence_positions[key].get(game, 0)
    sequence_positions[key][game] = (pos + 1) % sequence_length
    save_pattern_state()
    return pos


def reset_sequence(user_id=None):
    if user_id is None:
        sequence_positions.clear()
        sequence_positions["__global__"] = {"bet": 0, "dice": 0}
    else:
        key = str(user_id)
        if key in sequence_positions:
            del sequence_positions[key]
    save_pattern_state()


# ==================== GROUP CACHE ====================
def load_group_cache():
    global group_cache
    try:
        with open(GROUP_CACHE_FILE, "r") as f:
            data = json.load(f)
        group_cache.clear()
        group_cache.update(data)
    except (FileNotFoundError, json.JSONDecodeError):
        group_cache.clear()


def save_group_cache():
    try:
        _atomic_json_write(GROUP_CACHE_FILE, group_cache)
        _sync_to_channel("group_cache.json")
    except Exception as e:
        print(f"[group_cache] save failed: {e}")


# ==================== GROUP DROP SETTINGS ====================
def load_group_settings():
    global group_settings
    try:
        with open(GROUP_SETTINGS_FILE, "r") as f:
            data = json.load(f)
        group_settings.clear()
        group_settings.update(data)
    except (FileNotFoundError, json.JSONDecodeError):
        group_settings.clear()


def save_group_settings():
    try:
        _atomic_json_write(GROUP_SETTINGS_FILE, group_settings)
        _sync_to_channel("group_settings.json")
    except Exception as e:
        print(f"[group_settings] save failed: {e}")


def get_group_drop_count(gid):
    """Messages required before a character drops in this group."""
    try:
        return int(group_settings.get(str(gid), {}).get("drop_count", DEFAULT_DROP_COUNT))
    except (ValueError, TypeError):
        return DEFAULT_DROP_COUNT


def set_group_drop_count(gid, count):
    """Set the drop threshold; only 50/100/150/200 are allowed."""
    try:
        count = int(count)
    except (ValueError, TypeError):
        return False
    if count not in ALLOWED_DROP_COUNTS:
        return False
    group_settings.setdefault(str(gid), {})["drop_count"] = count
    save_group_settings()
    return True


def get_group_next_drop_rarity(gid):
    """Return this group's queued one-time rarity override, if any."""
    value = group_settings.get(str(gid), {}).get("next_drop_rarity")
    return str(value).strip().upper() if value else None


def set_group_next_drop_rarity(gid, rarity):
    """Queue one rarity for the next character spawn in this group only."""
    value = " ".join(str(rarity or "").strip().upper().split())
    if value not in get_character_rarities():
        return False
    group_settings.setdefault(str(gid), {})["next_drop_rarity"] = value
    save_group_settings()
    return True


def clear_group_next_drop_rarity(gid):
    """Clear this group's queued next-drop rarity."""
    settings = group_settings.get(str(gid), {})
    existed = settings.pop("next_drop_rarity", None) is not None
    if settings:
        group_settings[str(gid)] = settings
    else:
        group_settings.pop(str(gid), None)
    if existed:
        save_group_settings()
    return existed


def get_cached_group(gid):
    import time as _t
    entry = group_cache.get(str(gid))
    if not entry:
        return None
    if _t.time() - entry.get("cached_at", 0) > 86400:
        return None
    return entry


def set_cached_group(gid, title, username, invite_link):
    import time as _t
    group_cache[str(gid)] = {
        "title": title,
        "username": username,
        "invite_link": invite_link,
        "cached_at": _t.time(),
    }
    save_group_cache()


# ==================== CHARACTER ID ====================
def get_next_char_id():
    """Smallest available ID (reuses deleted IDs)."""
    with _char_id_lock:
        used_ids = set()
        for c in normal_characters:
            cid = c.get("id")
            try:
                cid = int(cid)
                if cid > 0:
                    used_ids.add(cid)
            except (TypeError, ValueError):
                pass
        for c in mythical_characters:
            cid = c.get("id")
            try:
                cid = int(cid)
                if cid > 0:
                    used_ids.add(cid)
            except (TypeError, ValueError):
                pass
        for c in exalted_characters:
            cid = c.get("id")
            try:
                cid = int(cid)
                if cid > 0:
                    used_ids.add(cid)
            except (TypeError, ValueError):
                pass

        next_id = 1
        while next_id in used_ids:
            next_id += 1

        try:
            _atomic_json_write(CHAR_ID_COUNTER_FILE, {"last_assigned": next_id})
            _sync_to_channel("char_id_counter.json")
        except Exception:
            pass

        return next_id


def reset_char_id_counter():
    with _char_id_lock:
        _atomic_json_write(CHAR_ID_COUNTER_FILE, {"next_id": 1})
        _sync_to_channel("char_id_counter.json")


# ==================== CHARACTER LOOKUP ====================
def get_character_by_id(char_id):
    if char_id is None:
        return None
    target_id = str(char_id)
    for c in normal_characters:
        if c.get("id") is not None and str(c.get("id")) == target_id:
            return c
    for c in mythical_characters:
        if c.get("id") is not None and str(c.get("id")) == target_id:
            return c
    for c in exalted_characters:
        if c.get("id") is not None and str(c.get("id")) == target_id:
            return c
    return None


def get_character_by_name(name):
    if not name or not isinstance(name, str):
        return None
    target = name.strip().lower()
    if not target:
        return None
    for c in normal_characters:
        cname = c.get("name", "")
        if isinstance(cname, str) and cname.lower() == target:
            return c
    for c in mythical_characters:
        cname = c.get("name", "")
        if isinstance(cname, str) and cname.lower() == target:
            return c
    for c in exalted_characters:
        cname = c.get("name", "")
        if isinstance(cname, str) and cname.lower() == target:
            return c
    return None


# ==================== ADMIN CHECK ====================
def is_admin_or_owner(user_id):
    try:
        return int(user_id) == int(OWNER_ID) or int(user_id) in ADMINS
    except (ValueError, TypeError):
        return False


# ==================== PLAYER ====================
def get_player(uid, user=None):
    uid_str = str(uid)
    if uid_str not in user_data:
        user_data[uid_str] = Player(uid)

    p = user_data[uid_str]

    if user is not None:
        try:
            if getattr(user, "first_name", None):
                p.name = user.first_name
            if getattr(user, "username", None):
                p.username = user.username
        except Exception:
            pass

    return p


# ==================== SAVE ====================
def save_data():
    try:
        data = {uid: p.to_dict() for uid, p in user_data.items()}
        _atomic_json_write(USERS_FILE, data)
        _sync_to_channel("users.json")
    except Exception as e:
        print(f"[DEBUG] Error saving users: {e}")


def create_json_backup(source="manual"):
    """Write a timestamped snapshot of all mutable bot JSON data."""
    ts = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(DATA_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    files = {
        "users.json": {uid: p.to_dict() for uid, p in user_data.items()},
        "normal_chars.json": normal_characters,
        "mythical_chars.json": mythical_characters,
        "exalted_chars.json": exalted_characters,
        "rarities.json": {"rarities": custom_rarities, "settings": rarity_settings},
        "gbanned.json": list(GBANNED),
        "temp_banned.json": {str(k): v for k, v in TEMP_BANNED.items()},
        "admins.json": list(ADMINS),
        "bot_groups.json": list(bot_groups),
        "group_settings.json": group_settings,
        "pattern_state.json": {
            "current_pattern": current_pattern,
            "pattern_override": pattern_override,
            "sequence_positions": sequence_positions,
        },
    }

    sticker_path = os.path.join(DATA_DIR, "fishing_sticker.json")
    try:
        with open(sticker_path, "r", encoding="utf-8") as fh:
            files["fishing_sticker.json"] = json.load(fh)
    except FileNotFoundError:
        files["fishing_sticker.json"] = {}
    except (OSError, ValueError) as exc:
        print(f"[backup:{source}] fishing_sticker.json: {exc}")

    try:
        from crew import CREW_STORE
        files["crews.json"] = CREW_STORE
    except Exception:
        pass

    saved = []
    failed = []
    for fname, payload in files.items():
        try:
            _atomic_json_write(os.path.join(backup_dir, f"{ts}_{fname}"), payload)
            saved.append(fname)
        except Exception as e:
            print(f"[backup:{source}] {fname}: {e}")
            failed.append(fname)

    return {
        "timestamp": ts,
        "source": source,
        "saved": saved,
        "failed": failed,
        "directory": backup_dir,
    }


def save_normal_chars():
    try:
        _atomic_json_write(NORMAL_CHARS_FILE, normal_characters)
        _sync_to_channel("normal_chars.json")
    except Exception as e:
        print(f"[DEBUG] Error saving normal chars: {e}")


def save_mythical_chars():
    try:
        _atomic_json_write(MYTHICAL_CHARS_FILE, mythical_characters)
        _sync_to_channel("mythical_chars.json")
    except Exception as e:
        print(f"[DEBUG] Error saving mythical chars: {e}")


def save_exalted_chars():
    try:
        _atomic_json_write(EXALTED_CHARS_FILE, exalted_characters)
        _sync_to_channel("exalted_chars.json")
    except Exception as e:
        print(f"[DEBUG] Error saving exalted chars: {e}")


def save_rarities():
    try:
        _atomic_json_write(RARITIES_FILE, {
            "rarities": custom_rarities,
            "settings": rarity_settings,
        })
        _sync_to_channel("rarities.json")
    except Exception as e:
        print(f"[DEBUG] Error saving rarities: {e}")


def add_custom_rarity(name):
    value = " ".join(str(name).strip().upper().split())
    if not value or value in {"NORMAL", "MYTHICAL", "EXALTED"}:
        return False
    if value not in custom_rarities:
        custom_rarities.append(value)
        rarity_settings[value] = {"emoji": "💠", "chance": 0.0, "reward_min": 10_000, "reward_max": 500_000}
        save_rarities()
    return value


def delete_custom_rarity(name):
    value = " ".join(str(name).strip().upper().split())
    if value not in custom_rarities:
        return False
    custom_rarities.remove(value)
    rarity_settings.pop(value, None)
    # Characters remain available, but fall back to NORMAL if their rarity is removed.
    for character in normal_characters + mythical_characters + exalted_characters:
        if str(character.get("rarity", "")).upper() == value:
            character["rarity"] = "NORMAL"
    for player in user_data.values():
        for captured in player.captured_chars:
            if str(captured.get("rarity", "")).upper() == value:
                captured["rarity"] = "NORMAL"
    for challenge in active_challenges.values():
        if str(challenge.get("rarity", "")).upper() == value:
            challenge["rarity"] = "NORMAL"
            challenge["is_mythical"] = False
    save_normal_chars()
    save_mythical_chars()
    save_exalted_chars()
    save_data()
    save_rarities()
    return value


def rename_custom_rarity(old_name, new_name):
    """Rename a custom rarity everywhere while retaining its settings."""
    old = " ".join(str(old_name).strip().upper().split())
    new = " ".join(str(new_name).strip().upper().split())
    if old not in custom_rarities or not new or new in {"NORMAL", "MYTHICAL", "EXALTED"}:
        return False
    if old == new:
        return old
    if new in get_character_rarities():
        return False

    custom_rarities[custom_rarities.index(old)] = new
    rarity_settings[new] = rarity_settings.pop(
        old, {"emoji": "💠", "chance": 0.0, "reward_min": 10_000, "reward_max": 500_000}
    )
    for character in normal_characters + mythical_characters + exalted_characters:
        if str(character.get("rarity", "")).strip().upper() == old:
            character["rarity"] = new
    for player in user_data.values():
        for captured in player.captured_chars:
            if str(captured.get("rarity", "")).strip().upper() == old:
                captured["rarity"] = new
    for challenge in active_challenges.values():
        if str(challenge.get("rarity", "")).strip().upper() == old:
            challenge["rarity"] = new
            challenge["is_mythical"] = False

    save_normal_chars()
    save_mythical_chars()
    save_exalted_chars()
    save_data()
    save_rarities()
    return new


def get_character_rarities():
    return ["NORMAL", "MYTHICAL", "EXALTED"] + list(custom_rarities)


def get_rarity_emoji(rarity):
    return rarity_settings.get(str(rarity).upper(), {}).get("emoji", "💠")


def get_rarity_chance(rarity):
    try:
        return max(0.0, float(rarity_settings.get(str(rarity).upper(), {}).get("chance", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def get_rarity_reward_range(rarity):
    settings = rarity_settings.get(str(rarity).upper(), {})
    try:
        low = max(0, int(settings.get("reward_min", 10_000)))
        high = max(low, int(settings.get("reward_max", low)))
        return low, high
    except (TypeError, ValueError):
        return 10_000, 500_000


def set_rarity_reward_range(rarity, minimum, maximum):
    value = str(rarity).strip().upper()
    try:
        low, high = int(minimum), int(maximum)
    except (TypeError, ValueError):
        return False
    if value not in get_character_rarities() or low < 0 or high < 0:
        return False
    low, high = sorted((low, high))
    rarity_settings.setdefault(value, {"emoji": "💠", "chance": 0.0})
    rarity_settings[value]["reward_min"] = low
    rarity_settings[value]["reward_max"] = high
    save_rarities()
    return low, high


def set_rarity_emoji(rarity, emoji):
    value = str(rarity).strip().upper()
    if value not in get_character_rarities() or not str(emoji).strip():
        return False
    rarity_settings.setdefault(value, {"emoji": "💠", "chance": 0.0})["emoji"] = str(emoji).strip()
    save_rarities()
    return rarity_settings[value]["emoji"]


def set_rarity_chance(rarity, chance):
    value = str(rarity).strip().upper()
    try:
        chance_value = float(chance)
    except (TypeError, ValueError):
        return False
    if value not in get_character_rarities() or not 0 <= chance_value <= 100:
        return False
    rarity_settings.setdefault(value, {"emoji": "💠", "chance": 0.0})["chance"] = chance_value
    save_rarities()
    return chance_value


def save_banned():
    try:
        _atomic_json_write(GBANNED_FILE, list(GBANNED))
        _sync_to_channel("gbanned.json")
    except Exception as e:
        print(f"[DEBUG] Error saving global bans: {e}")


def save_temp_banned():
    try:
        data = {uid: unban_time for uid, unban_time in TEMP_BANNED.items()}
        _atomic_json_write(TEMP_BANNED_FILE, data)
        _sync_to_channel("temp_banned.json")
    except Exception as e:
        print(f"[DEBUG] Error saving temp bans: {e}")


def save_admins():
    try:
        _atomic_json_write(ADMINS_FILE, list(ADMINS))
        _sync_to_channel("admins.json")
    except Exception as e:
        print(f"[DEBUG] Error saving admins: {e}")


def save_bot_groups():
    try:
        f = os.path.join(DATA_DIR, "bot_groups.json")
        _atomic_json_write(f, list(bot_groups))
        _sync_to_channel("bot_groups.json")
    except Exception as e:
        print(f"[DEBUG] Error saving bot groups: {e}")


def save_banned_players_info():
    try:
        f = os.path.join(DATA_DIR, "banned_players_info.json")
        _atomic_json_write(f, banned_players_info)
        _sync_to_channel("banned_players_info.json")
    except Exception as e:
        print(f"Error saving banned players info: {e}")


# ==================== LOAD ====================
def load_data():
    global user_data, normal_characters, mythical_characters, exalted_characters
    global GBANNED, TEMP_BANNED, ADMINS, banned_players_info, bot_groups

    print("[DEBUG] Loading data...")

    # Users — mutate in place
    try:
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("users.json root must be a dict")
        user_data.clear()
        for uid, pdata in data.items():
            try:
                user_data[str(uid)] = Player.from_dict(int(uid), pdata)
            except (ValueError, TypeError):
                try:
                    user_data[str(uid)] = Player.from_dict(uid, pdata)
                except Exception as e:
                    print(f"[DEBUG] Skipping bad user {uid}: {e}")
        print(f"[DEBUG] Loaded {len(user_data)} users")
    except FileNotFoundError:
        user_data.clear()
        save_data()
    except Exception as e:
        print(f"[DEBUG] Error loading users: {e}")
        user_data.clear()

    # Normal characters — mutate in place
    try:
        with open(NORMAL_CHARS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = []
        normal_characters.clear()
        normal_characters.extend(data)
        print(f"[DEBUG] Loaded {len(normal_characters)} normal characters")
    except FileNotFoundError:
        normal_characters.clear()
        save_normal_chars()
    except Exception as e:
        print(f"[DEBUG] Error loading normal chars: {e}")
        normal_characters.clear()

    # Mythical characters — mutate in place
    try:
        with open(MYTHICAL_CHARS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = []
        mythical_characters.clear()
        mythical_characters.extend(data)
        print(f"[DEBUG] Loaded {len(mythical_characters)} mythical characters")
    except FileNotFoundError:
        mythical_characters.clear()
        save_mythical_chars()
    except Exception as e:
        print(f"[DEBUG] Error loading mythical chars: {e}")
        mythical_characters.clear()

    # Exalted characters — mutate in place
    try:
        with open(EXALTED_CHARS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = []
        exalted_characters.clear()
        exalted_characters.extend(data)
        print(f"[DEBUG] Loaded {len(exalted_characters)} exalted characters")
    except FileNotFoundError:
        exalted_characters.clear()
        save_exalted_chars()
    except Exception as e:
        print(f"[DEBUG] Error loading exalted chars: {e}")
        exalted_characters.clear()

    # One-time migration for older character records that predate global IDs.
    # IDs are required for unambiguous challenge captures and collection sync.
    for characters, save_fn in (
        (normal_characters, save_normal_chars),
        (mythical_characters, save_mythical_chars),
        (exalted_characters, save_exalted_chars),
    ):
        changed = False
        for character in characters:
            if not isinstance(character, dict):
                continue
            try:
                normalized_id = int(character.get("id"))
                valid_id = normalized_id > 0
            except (TypeError, ValueError, AttributeError):
                valid_id = False
            if not valid_id:
                character["id"] = get_next_char_id()
                changed = True
            elif character.get("id") != normalized_id:
                character["id"] = normalized_id
                changed = True
        if changed:
            save_fn()

    try:
        with open(RARITIES_FILE, "r") as f:
            data = json.load(f)
        stored_rarities = data.get("rarities", []) if isinstance(data, dict) else data
        stored_settings = data.get("settings", {}) if isinstance(data, dict) else {}
        custom_rarities.clear()
        custom_rarities.extend(
            " ".join(str(x).strip().upper().split())
            for x in (stored_rarities if isinstance(stored_rarities, list) else [])
            if str(x).strip()
        )
        for rarity, settings in (stored_settings.items() if isinstance(stored_settings, dict) else []):
            if isinstance(settings, dict):
                normalized = {
                    "emoji": str(settings.get("emoji", "💠")),
                    "chance": float(settings.get("chance", 0.0)),
                }
                try:
                    normalized["reward_min"] = max(0, int(settings.get("reward_min", 10_000)))
                    normalized["reward_max"] = max(normalized["reward_min"], int(settings.get("reward_max", normalized["reward_min"])))
                except (TypeError, ValueError):
                    normalized["reward_min"], normalized["reward_max"] = 10_000, 500_000
                rarity_settings[str(rarity).upper()] = normalized
        for rarity in custom_rarities:
            rarity_settings.setdefault(rarity, {"emoji": "💠", "chance": 0.0, "reward_min": 10_000, "reward_max": 500_000})
    except FileNotFoundError:
        custom_rarities.clear()
        save_rarities()
    except Exception as e:
        print(f"[DEBUG] Error loading rarities: {e}")
        custom_rarities.clear()

    # Global bans — mutate in place
    try:
        with open(GBANNED_FILE, "r") as f:
            data = json.load(f)
        GBANNED.clear()
        GBANNED.update(data)
        print(f"[DEBUG] Loaded {len(GBANNED)} global bans")
    except FileNotFoundError:
        GBANNED.clear()
        save_banned()
    except Exception as e:
        print(f"[DEBUG] Error loading global bans: {e}")
        GBANNED.clear()

    # Temp bans — mutate in place
    try:
        with open(TEMP_BANNED_FILE, "r") as f:
            raw = json.load(f)
        TEMP_BANNED.clear()
        for uid, t in raw.items():
            try:
                TEMP_BANNED[int(uid)] = float(t)
            except (ValueError, TypeError):
                pass
        print(f"[DEBUG] Loaded {len(TEMP_BANNED)} temp bans")
    except FileNotFoundError:
        TEMP_BANNED.clear()
        save_temp_banned()
    except Exception as e:
        print(f"[DEBUG] Error loading temp bans: {e}")
        TEMP_BANNED.clear()

    # Admins — mutate in place
    try:
        with open(ADMINS_FILE, "r") as f:
            data = json.load(f)
        ADMINS.clear()
        ADMINS.update(data)
        print(f"[DEBUG] Loaded {len(ADMINS)} admins")
    except FileNotFoundError:
        ADMINS.clear()
        save_admins()
    except Exception as e:
        print(f"[DEBUG] Error loading admins: {e}")
        ADMINS.clear()

    load_bot_groups()
    load_banned_players_info()
    load_pattern_state()
    load_group_cache()
    load_group_settings()

    print(
        f"[DEBUG] FINAL — Users: {len(user_data)}, "
        f"Normal: {len(normal_characters)}, "
        f"Mythical: {len(mythical_characters)}, "
        f"Exalted: {len(exalted_characters)}, "
        f"Groups: {len(bot_groups)}"
    )


# ==================== CHARACTER MANAGEMENT ====================
def character_media_exists(image, exclude_id=None):
    """Return the existing character using the same Telegram file ID or URL."""
    if not isinstance(image, str) or not image.strip():
        return None
    value = image.strip()
    for character in normal_characters + mythical_characters + exalted_characters:
        if exclude_id is not None and character.get("id") == exclude_id:
            continue
        if str(character.get("image", "")).strip() == value:
            return character
    return None


def _can_add_character_media(image):
    return character_media_exists(image) is None


def add_normal_character(name, image, media_type="photo"):
    if not _can_add_character_media(image):
        return False
    char_id = get_next_char_id()
    normal_characters.append({
        "id": char_id,
        "name": name,
        "image": image,
        "media_type": media_type if media_type in {"photo", "video"} else "photo",
        "rarity": "NORMAL",
        "created_at": time.time(),
    })
    save_normal_chars()
    return True


def add_mythical_character(name, image, media_type="photo"):
    if not _can_add_character_media(image):
        return False
    char_id = get_next_char_id()
    mythical_characters.append({
        "id": char_id,
        "name": name,
        "image": image,
        "media_type": media_type if media_type in {"photo", "video"} else "photo",
        "rarity": "MYTHICAL",
        "created_at": time.time(),
    })
    save_mythical_chars()
    return True


def add_exalted_character(name, image, media_type="photo"):
    if not _can_add_character_media(image):
        return False
    char_id = get_next_char_id()
    exalted_characters.append({
        "id": char_id,
        "name": name,
        "image": image,
        "media_type": media_type if media_type in {"photo", "video"} else "photo",
        "rarity": "EXALTED",
        "created_at": time.time(),
    })
    save_exalted_chars()
    return True


def add_custom_character(name, image, rarity, media_type="photo"):
    """Add a character with an owner-created rarity to the normal character store."""
    value = " ".join(str(rarity).strip().upper().split())
    if value not in custom_rarities or not _can_add_character_media(image):
        return False
    char_id = get_next_char_id()
    normal_characters.append({
        "id": char_id,
        "name": name,
        "image": image,
        "media_type": media_type if media_type in {"photo", "video"} else "photo",
        "rarity": value,
        "created_at": time.time(),
    })
    save_normal_chars()
    return True


def _delete_character_from_list(characters, char_id, save_fn):
    for index, character in enumerate(characters):
        if character.get("id") != char_id:
            continue
        deleted = characters.pop(index)
        for chat_id, challenge in list(active_challenges.items()):
            if challenge.get("char", {}).get("id") == char_id:
                active_challenges.pop(chat_id, None)
        for trade_id, trade in list(pending_trades.items()):
            selected = trade.get("selected_char")
            if selected and selected.get("id") == char_id:
                pending_trades.pop(trade_id, None)
        for player in user_data.values():
            player.captured_chars = [
                captured for captured in player.captured_chars
                if captured.get("id") != char_id
            ]
        save_fn()
        save_data()
        return deleted
    return None


def delete_character_by_id(char_id):
    """Delete a character by its globally unique ID across all backing lists."""
    for characters, save_fn in (
        (normal_characters, save_normal_chars),
        (mythical_characters, save_mythical_chars),
        (exalted_characters, save_exalted_chars),
    ):
        deleted = _delete_character_from_list(characters, char_id, save_fn)
        if deleted:
            return deleted
    return None


def delete_normal_character(char_id):
    return _delete_character_from_list(normal_characters, char_id, save_normal_chars)


def update_character(char_id, new_name=None, new_image=None, new_rarity=None):
    """Update a character's name / image / rarity in both lists AND propagate
    name + image to every player's captured_chars. Returns the updated dict
    with old+new values so the admin command can confirm, or None if not found.
    """
    target = None
    cur_list = None
    other_list = None
    for lst in (normal_characters, mythical_characters, exalted_characters):
        for c in lst:
            if c.get("id") == char_id:
                target = c
                cur_list = lst
                other_list = next(
                    (candidate for candidate in (normal_characters, mythical_characters, exalted_characters)
                     if candidate is not lst),
                    normal_characters,
                )
                break
        if target:
            break
    if not target:
        return None

    original_list = cur_list
    old_name = target.get("name")
    old_image = target.get("image")
    old_rarity = target.get("rarity", "NORMAL")

    if new_name is not None and str(new_name).strip():
        target["name"] = str(new_name).strip()
    if new_image is not None and str(new_image).strip():
        target["image"] = str(new_image).strip()
    rarity_lists = {
        "NORMAL": normal_characters,
        "MYTHICAL": mythical_characters,
        "EXALTED": exalted_characters,
    }
    normalized_rarity = (
        " ".join(str(new_rarity).strip().upper().split())
        if new_rarity is not None else None
    )
    if normalized_rarity in rarity_lists or normalized_rarity in custom_rarities:
        target["rarity"] = normalized_rarity
        destination = rarity_lists.get(normalized_rarity)
        if destination is not None and cur_list is not destination:
            cur_list.remove(target)
            destination.append(target)
            cur_list = destination

    new_name_val = target["name"]
    new_image_val = target["image"]
    new_rarity_val = target.get("rarity", "NORMAL")

    saved_lists = []
    for changed_list in (original_list, cur_list):
        if any(changed_list is already_saved for already_saved in saved_lists):
            continue
        saved_lists.append(changed_list)
        if changed_list is normal_characters:
            save_normal_chars()
        elif changed_list is mythical_characters:
            save_mythical_chars()
        elif changed_list is exalted_characters:
            save_exalted_chars()

    if (new_name_val != old_name) or (new_image_val != old_image) or (new_rarity_val != old_rarity):
        affected = 0
        for player in user_data.values():
            for ch in player.captured_chars:
                if ch.get("id") == char_id:
                    if new_name_val:
                        ch["name"] = new_name_val
                    if new_image_val:
                        ch["image"] = new_image_val
                    if new_rarity_val:
                        ch["rarity"] = new_rarity_val
                    affected += 1
        if affected:
            save_data()

    return {
        "id": char_id,
        "old_name": old_name,
        "new_name": new_name_val,
        "old_image": old_image,
        "new_image": new_image_val,
        "old_rarity": old_rarity,
        "new_rarity": new_rarity_val,
    }


def delete_mythical_character(char_id):
    return _delete_character_from_list(mythical_characters, char_id, save_mythical_chars)


def delete_exalted_character(char_id):
    return _delete_character_from_list(exalted_characters, char_id, save_exalted_chars)


def set_character_win_chance(char_id, chance):
    """Set a single character's absolute challenge win percentage."""
    try:
        chance_value = float(chance)
    except (TypeError, ValueError):
        return False
    if not 0 <= chance_value <= 100:
        return False
    character = get_character_by_id(char_id)
    if not character:
        return False
    character["win_chance"] = chance_value
    if any(character is item for item in normal_characters):
        save_normal_chars()
    elif any(character is item for item in mythical_characters):
        save_mythical_chars()
    else:
        save_exalted_chars()
    return chance_value


def get_normal_characters():
    return normal_characters


def get_mythical_characters():
    return mythical_characters


def get_exalted_characters():
    return exalted_characters


# ==================== TEMP BAN ====================
def check_temp_bans():
    now = time.time()
    expired = [uid for uid, t in TEMP_BANNED.items() if t <= now]
    for uid in expired:
        del TEMP_BANNED[uid]
    if expired:
        save_temp_banned()


# ==================== BOT GROUPS ====================
def load_bot_groups():
    global bot_groups
    try:
        f = os.path.join(DATA_DIR, "bot_groups.json")
        if os.path.exists(f):
            with open(f, "r") as fp:
                data = json.load(fp)
            bot_groups.clear()
            bot_groups.update(data)
        else:
            bot_groups.clear()
            save_bot_groups()
    except Exception as e:
        print(f"[DEBUG] Error loading bot groups: {e}")
        bot_groups.clear()


def add_bot_group(group_id):
    bot_groups.add(group_id)
    save_bot_groups()


def remove_bot_group(group_id):
    if group_id in bot_groups:
        bot_groups.discard(group_id)
        save_bot_groups()


def get_bot_groups():
    return bot_groups


# ==================== BANNED INFO ====================
def load_banned_players_info():
    global banned_players_info
    try:
        f = os.path.join(DATA_DIR, "banned_players_info.json")
        if os.path.exists(f):
            with open(f, "r") as fp:
                data = json.load(fp)
            banned_players_info.clear()
            banned_players_info.update(data)
        else:
            banned_players_info.clear()
    except Exception:
        banned_players_info.clear()


def add_banned_player_info(user_id, user_name, user_username, reason,
                           banned_by, banned_by_name):
    banned_players_info[str(user_id)] = {
        "reason": reason,
        "banned_by": banned_by,
        "banned_by_name": banned_by_name,
        "banned_at": time.time(),
        "banned_at_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_name": user_name,
        "user_username": user_username,
    }
    save_banned_players_info()


def remove_banned_player_info(user_id):
    if str(user_id) in banned_players_info:
        del banned_players_info[str(user_id)]
        save_banned_players_info()


def get_banned_player_info(user_id):
    return banned_players_info.get(str(user_id), {})


# ==================== TRADES ====================
def add_trade(trade_id, trade_data):
    pending_trades[trade_id] = trade_data


def get_trade(trade_id):
    return pending_trades.get(trade_id)


def remove_trade(trade_id):
    if trade_id in pending_trades:
        del pending_trades[trade_id]


# ==================== CHALLENGE ====================
def get_active_challenge(chat_id):
    return active_challenges.get(chat_id)


def set_active_challenge(chat_id, challenge_data):
    active_challenges[chat_id] = challenge_data


def remove_active_challenge(chat_id):
    if chat_id in active_challenges:
        del active_challenges[chat_id]


def increment_message_count(chat_id):
    message_count[chat_id] = message_count.get(chat_id, 0) + 1
    return message_count[chat_id]


def reset_message_count(chat_id):
    message_count[chat_id] = 0


# ==================== WORLD BOSS ====================
def set_world_boss_active(active):
    global world_boss_active
    world_boss_active = bool(active)


def get_world_boss_active():
    return world_boss_active


def get_world_boss_hp():
    return world_boss_hp


def set_world_boss_hp(hp):
    global world_boss_hp
    world_boss_hp = hp


def add_world_boss_damage(user_id, damage):
    world_boss_damage[user_id] = world_boss_damage.get(user_id, 0) + damage


def get_world_boss_damage():
    return world_boss_damage


def clear_world_boss_damage():
    world_boss_damage.clear()


# ==================== GIVEAWAYS ====================
def add_giveaway(key, giveaway_data):
    active_giveaways[key] = giveaway_data


def get_giveaway(key):
    return active_giveaways.get(key)


def remove_giveaway(key):
    if key in active_giveaways:
        del active_giveaways[key]


def get_all_giveaways():
    return active_giveaways


def get_global_giveaway():
    return active_global_giveaway


def set_global_giveaway(giveaway_data):
    global active_global_giveaway
    active_global_giveaway = giveaway_data


def clear_global_giveaway():
    global active_global_giveaway
    active_global_giveaway = None


def is_global_giveaway_active():
    return active_global_giveaway is not None


# ==================== PENDING FORWARDS ====================
def set_pending_forward(user_id, data):
    pending_forwards[user_id] = data


def get_pending_forward(user_id):
    return pending_forwards.get(user_id)


def clear_pending_forward(user_id):
    if user_id in pending_forwards:
        del pending_forwards[user_id]


def get_all_pending_forwards():
    return pending_forwards
