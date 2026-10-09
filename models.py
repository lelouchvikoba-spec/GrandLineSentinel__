# models.py
import time
import hashlib

from config import HAKI_BAR_MAX


def _stable_id(name: str) -> int:
    if not name:
        return 0
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000


class Player:
    def __init__(self, user_id):
        try:
            self.user_id = int(user_id)
        except (ValueError, TypeError):
            self.user_id = user_id

        self.bounty = 0
        self.level = 1
        self.xp = 0

        # ==================== HAKI ====================
        self.haki = None
        self.haki_level = 0
        self.haki_active = False
        self.haki_bar = HAKI_BAR_MAX
        self.haki_bar_updated = 0
        self.haki_is_advanced = False
        self.advanced_haki = False  # legacy sync flag

        # ==================== SHIELD ====================
        self.shield_level = 0
        self.shield_uses = 0
        self.shield_cd = 0

        # ==================== FLAGS ====================
        self.passive_enabled = True
        self.pvp_enabled = True

        # ==================== FRUIT ====================
        self.devil_fruit = None
        self.fruit_category = None
        self.nika_awakened = False

        # ==================== IDENTITY ====================
        self.name = ""
        self.username = ""

        # ==================== TIMERS ====================
        self.daily = 0
        self.weekly = 0
        self.pay_cd = 0
        self.rob_cd = 0
        self.boost_end = 0

        # ==================== VAULT ====================
        self.vault = 0
        self.vault_level = 1

        # ==================== COLLECTION ====================
        self.captured_chars = []

        # ==================== TOKENS ====================
        self.advanced_token = 0

        # ==================== CLAIM ====================
        self.claimed_main = False

        # ==================== INVENTORY ====================
        # Shields: list of dicts
        #   [{"level": 1, "uses": 3, "purchased_at": timestamp}]
        self.shields = []

        # XP Boosts: list of dicts
        #   [{"duration": 900, "purchased_at": timestamp}]
        self.xp_boosts = []

        # ==================== FISHING ====================
        self.fishing_rod = {"type": "wooden", "uses": 5, "max_uses": 5}
        self.fishing_bait = {"type": "basic", "uses": 5, "max_uses": 5}
        self.fish_inventory = {}

    # ---------- captured char helpers ----------
    def add_captured_character(self, char_data):
        if not isinstance(char_data, dict):
            return False
        if not char_data.get("id"):
            char_data["id"] = _stable_id(char_data.get("name", ""))
        if "captured_at" not in char_data:
            char_data["captured_at"] = time.time()
        self.captured_chars.append(char_data)
        return True

    def remove_captured_character(self, char_id):
        original = len(self.captured_chars)
        self.captured_chars = [c for c in self.captured_chars if c.get("id") != char_id]
        return original - len(self.captured_chars)

    def remove_captured_character_by_name(self, char_name):
        original = len(self.captured_chars)
        self.captured_chars = [c for c in self.captured_chars if c.get("name") != char_name]
        return original - len(self.captured_chars)

    def get_captured_char_ids(self):
        return [c.get("id") for c in self.captured_chars if c.get("id")]

    def get_captured_char_count(self, char_name=None):
        if char_name:
            return sum(1 for c in self.captured_chars if c.get("name") == char_name)
        return len(self.captured_chars)

    def get_unique_captured_chars(self):
        unique = {}
        for char in self.captured_chars:
            char_id = char.get("id") or char.get("name")
            if char_id not in unique:
                unique[char_id] = {
                    "id": char.get("id"),
                    "name": char.get("name"),
                    "image": char.get("image"),
                    "rarity": char.get("rarity", "NORMAL"),
                    "count": 0,
                }
            unique[char_id]["count"] += 1
        return list(unique.values())

    def has_character(self, char_id):
        return any(c.get("id") == char_id for c in self.captured_chars)

    def has_character_by_name(self, char_name):
        return any(c.get("name") == char_name for c in self.captured_chars)

    # ---------- serialization ----------
    def to_dict(self):
        return {
            "bounty": self.bounty,
            "level": self.level,
            "xp": self.xp,

            "haki": self.haki,
            "haki_level": self.haki_level,
            "haki_active": self.haki_active,
            "haki_bar": self.haki_bar,
            "haki_bar_updated": self.haki_bar_updated,
            "haki_is_advanced": self.haki_is_advanced,
            "advanced_haki": self.advanced_haki,

            "shield_level": self.shield_level,
            "shield_uses": self.shield_uses,
            "shield_cd": self.shield_cd,

            "passive_enabled": self.passive_enabled,
            "pvp_enabled": self.pvp_enabled,

            "devil_fruit": self.devil_fruit,
            "fruit_category": self.fruit_category,
            "nika_awakened": self.nika_awakened,

            "name": self.name,
            "username": self.username,

            "daily": self.daily,
            "weekly": self.weekly,
            "pay_cd": self.pay_cd,
            "rob_cd": self.rob_cd,
            "boost_end": self.boost_end,

            "vault": self.vault,
            "vault_level": self.vault_level,

            "captured_chars": self.captured_chars,

            "advanced_token": self.advanced_token,
            "claimed_main": self.claimed_main,

            # Inventory
            "shields": self.shields,
            "xp_boosts": self.xp_boosts,

            # Fishing
            "fishing_rod": self.fishing_rod,
            "fishing_bait": self.fishing_bait,
            "fish_inventory": self.fish_inventory,
        }

    @classmethod
    def from_dict(cls, uid, data):
        if not isinstance(data, dict):
            data = {}
        p = cls(uid)

        p.bounty = data.get("bounty", 0)
        p.level = data.get("level", 1)
        p.xp = data.get("xp", 0)

        p.haki = data.get("haki")
        p.haki_level = data.get("haki_level", 0)
        p.haki_active = data.get("haki_active", False)
        p.haki_bar = data.get("haki_bar", HAKI_BAR_MAX)
        p.haki_bar_updated = data.get("haki_bar_updated", 0)
        p.haki_is_advanced = data.get("haki_is_advanced", False)
        # haki_is_advanced is authoritative; older builds marked every Lv.3
        # player as advanced before the enchant confirmation existed.
        p.advanced_haki = bool(p.haki_is_advanced)

        p.shield_level = data.get("shield_level", 0)
        p.shield_uses = data.get("shield_uses", 0)
        p.shield_cd = data.get("shield_cd", 0)

        p.passive_enabled = data.get("passive_enabled", True)
        p.pvp_enabled = data.get("pvp_enabled", True)

        # Normalize fruit name (legacy compatibility)
        p.devil_fruit = data.get("devil_fruit")
        if p.devil_fruit:
            try:
                from config import normalize_fruit_name
                p.devil_fruit = normalize_fruit_name(p.devil_fruit)
            except Exception:
                pass
        p.fruit_category = data.get("fruit_category")
        p.nika_awakened = data.get("nika_awakened", False)

        p.name = data.get("name", "") or ""
        p.username = data.get("username", "") or ""

        p.daily = data.get("daily", 0)
        p.weekly = data.get("weekly", 0)
        p.pay_cd = data.get("pay_cd", 0)
        p.rob_cd = data.get("rob_cd", 0)
        p.boost_end = data.get("boost_end", 0)

        p.vault = data.get("vault", 0)
        p.vault_level = data.get("vault_level", 1)

        p.advanced_token = data.get("advanced_token", 0)
        p.claimed_main = data.get("claimed_main", False)

        # ==================== INVENTORY ====================
        p.shields = data.get("shields", [])
        if not isinstance(p.shields, list):
            p.shields = []

        p.xp_boosts = data.get("xp_boosts", [])
        if not isinstance(p.xp_boosts, list):
            p.xp_boosts = []

        # ==================== FISHING ====================
        p.fishing_rod = data.get("fishing_rod") or {"type": "wooden", "uses": 5, "max_uses": 5}
        p.fishing_bait = data.get("fishing_bait") or {"type": "basic", "uses": 5, "max_uses": 5}
        p.fish_inventory = data.get("fish_inventory") or {}
        if not isinstance(p.fishing_rod, dict):
            p.fishing_rod = {"type": "wooden", "uses": 5, "max_uses": 5}
        if not isinstance(p.fishing_bait, dict):
            p.fishing_bait = {"type": "basic", "uses": 5, "max_uses": 5}
        if not isinstance(p.fish_inventory, dict):
            p.fish_inventory = {}

        # ==================== CAPTURED CHARS ====================
        captured = data.get("captured_chars", [])
        if not isinstance(captured, list):
            captured = []
        p.captured_chars = []

        try:
            from data_manager import get_character_by_name as _lookup
        except Exception:
            _lookup = None

        for char in captured:
            if isinstance(char, str):
                # Old format: just name string
                resolved_id = None
                resolved_img = None
                rarity = "NORMAL"
                if _lookup:
                    master = _lookup(char)
                    if master:
                        resolved_id = master.get("id")
                        resolved_img = master.get("image")
                        rarity = master.get("rarity", "NORMAL")
                if not resolved_id:
                    resolved_id = _stable_id(char)
                p.captured_chars.append({
                    "id": resolved_id,
                    "name": char,
                    "image": resolved_img,
                    "rarity": rarity,
                    "captured_at": 0,
                })
            elif isinstance(char, dict):
                if not char.get("id"):
                    char["id"] = None
                    if _lookup:
                        master = _lookup(char.get("name", ""))
                        if master and master.get("id") is not None:
                            char["id"] = master["id"]
                            if not char.get("image"):
                                char["image"] = master.get("image")
                            if not char.get("rarity"):
                                char["rarity"] = master.get("rarity", "NORMAL")
                    if char["id"] is None:
                        char["id"] = _stable_id(char.get("name", ""))
                if "captured_at" not in char:
                    char["captured_at"] = 0
                if "rarity" not in char:
                    char["rarity"] = "NORMAL"
                p.captured_chars.append(char)

        return p
