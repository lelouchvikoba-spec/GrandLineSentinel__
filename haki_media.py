"""Persistent Telegram GIF file IDs for Advanced Haki unlock announcements."""
import json
import os
import tempfile

from config import DATA_DIR

GIFS_PATH = os.path.join(DATA_DIR, "advanced_haki_gifs.json")
VALID_HAKI_TYPES = {"observation", "armament", "conqueror"}


def normalize_haki_type(value):
    key = str(value or "").strip().lower().replace("'", "")
    aliases = {
        "obv": "observation",
        "observation": "observation",
        "arm": "armament",
        "armament": "armament",
        "conq": "conqueror",
        "conqueror": "conqueror",
        "conquerors": "conqueror",
    }
    return aliases.get(key)


def get_advanced_haki_gif(haki_type):
    key = normalize_haki_type(haki_type)
    if not key:
        return None
    try:
        with open(GIFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        value = data.get(key) if isinstance(data, dict) else None
        return value if isinstance(value, str) and value.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def set_advanced_haki_gif(haki_type, file_id):
    key = normalize_haki_type(haki_type)
    if not key:
        raise ValueError("Unknown Haki type")
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(GIFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[key] = str(file_id).strip()
    fd, temp_path = tempfile.mkstemp(prefix="advanced_haki_gifs_", suffix=".json", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_path, GIFS_PATH)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return key


def clear_advanced_haki_gif(haki_type):
    key = normalize_haki_type(haki_type)
    if not key:
        raise ValueError("Unknown Haki type")
    try:
        with open(GIFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    existed = data.pop(key, None) is not None
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(GIFS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return key, existed
