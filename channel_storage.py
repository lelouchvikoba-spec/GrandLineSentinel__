# channel_storage.py
import os
import gzip
from pyrogram import Client

from config import (
    DATA_DIR,
    STORAGE_CHANNEL_ID,
    STORAGE_CHANNEL_USERNAME,
)


# ==================== CONFIG ====================
# Priority:
#   1. Username (if set) — always resolvable, no warmup needed
#   2. Numeric ID (fallback) — needs warmup on every startup
#
# Whatever is used here gets passed to send_message / get_chat_history etc.
STORAGE_CHANNEL = STORAGE_CHANNEL_USERNAME or STORAGE_CHANNEL_ID

# A cached, resolved peer (filled by warmup if username is empty)
_RESOLVED_PEER = None

# Files to sync
SYNC_FILES = [
    "users.json",
    "normal_chars.json",
    "mythical_chars.json",
    "exalted_chars.json",
    "rarities.json",
    "admins.json",
    "gbanned.json",
    "temp_banned.json",
    "bot_groups.json",
    "banned_players_info.json",
    "pattern_state.json",
    "group_cache.json",
    "group_settings.json",
    "char_id_counter.json",
    "crews.json",
]

KEEP_VERSIONS = 3


# ==================== PEER RESOLUTION ====================
async def resolve_peer(client: Client):
    """
    Return a peer reference that Pyrogram can use for chat operations.

    - If STORAGE_CHANNEL is a username (starts with @), return it directly.
      Usernames are always resolvable via Telegram's servers — no caching needed.
    - If STORAGE_CHANNEL is a numeric ID, we must 'warm up' by sending a
      throwaway message first so Pyrogram caches the access_hash. Otherwise
      subsequent calls like get_chat_history() fail with 'Peer id invalid'.
    """
    global _RESOLVED_PEER

    if not STORAGE_CHANNEL:
        return None

    # Case 1: username — just return it, Pyrogram handles resolution
    if isinstance(STORAGE_CHANNEL, str) and STORAGE_CHANNEL.startswith("@"):
        _RESOLVED_PEER = STORAGE_CHANNEL
        return STORAGE_CHANNEL

    # Case 2: numeric ID — warm up and cache the resolved peer
    if _RESOLVED_PEER is not None:
        return _RESOLVED_PEER

    try:
        msg = await client.send_message(STORAGE_CHANNEL, "🔧")
        try:
            await msg.delete()
        except Exception:
            pass

        # After sending, the peer is cached. Get the actual chat object.
        chat = await client.get_chat(STORAGE_CHANNEL)
        _RESOLVED_PEER = chat.id
        print(f"[channel_storage] Peer warmed up ✅ ({_RESOLVED_PEER})")
        return _RESOLVED_PEER
    except Exception as e:
        print(f"[channel_storage] Warm-up failed: {e}")
        return None


# ==================== UPLOAD ====================
async def upload_file(client: Client, file_path: str, caption: str = None):
    if not STORAGE_CHANNEL:
        return None
    peer = await resolve_peer(client)
    if peer is None:
        return None
    try:
        msg = await client.send_document(
            peer,
            file_path,
            caption=caption or os.path.basename(file_path),
        )
        return msg.id
    except Exception as e:
        print(f"[channel_storage] Upload failed ({file_path}): {e}")
        return None


async def upload_gzipped(client: Client, file_path: str, fname: str):
    if not STORAGE_CHANNEL:
        return None

    peer = await resolve_peer(client)
    if peer is None:
        return None

    gz_path = file_path + ".gz"
    try:
        with open(file_path, "rb") as f_in:
            data = f_in.read()
        with gzip.open(gz_path, "wb") as f_out:
            f_out.write(data)

        msg = await client.send_document(
            peer,
            gz_path,
            caption=fname + ".gz",
        )
        return msg.id
    except Exception as e:
        print(f"[channel_storage] Upload failed ({fname}): {e}")
        return None
    finally:
        try:
            if os.path.exists(gz_path):
                os.remove(gz_path)
        except Exception:
            pass


# ==================== DOWNLOAD ====================
async def download_latest(client: Client, filename: str, save_path: str):
    if not STORAGE_CHANNEL:
        return False

    peer = await resolve_peer(client)
    if peer is None:
        return False

    try:
        found = None
        is_gz = False
        target_name = filename

        async for msg in client.get_chat_history(peer, limit=500):
            if not msg.document:
                continue
            doc_name = msg.document.file_name or ""

            if doc_name == filename:
                found = msg
                is_gz = False
                break
            if doc_name == filename + ".gz":
                found = msg
                is_gz = True
                target_name = doc_name
                break

        if not found:
            print(f"[channel_storage] No '{filename}' found in channel")
            return False

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tmp_path = save_path + (".gz" if is_gz else ".tmp")
        await client.download_media(found, file_name=tmp_path)

        if is_gz:
            with gzip.open(tmp_path, "rb") as f_in:
                data = f_in.read()
            with open(save_path, "wb") as f_out:
                f_out.write(data)
            os.remove(tmp_path)
        else:
            os.replace(tmp_path, save_path)

        print(f"[channel_storage] Downloaded {target_name} → {save_path}")
        return True

    except Exception as e:
        print(f"[channel_storage] Download failed ({filename}): {e}")
        return False


# ==================== CLEANUP ====================
async def delete_old_from_channel(client: Client, filename: str, keep: int = KEEP_VERSIONS):
    if not STORAGE_CHANNEL:
        return

    peer = await resolve_peer(client)
    if peer is None:
        return

    try:
        matches = []
        async for msg in client.get_chat_history(peer, limit=500):
            if not msg.document:
                continue
            doc_name = msg.document.file_name or ""
            if doc_name == filename or doc_name == filename + ".gz":
                matches.append(msg)

        matches.sort(key=lambda m: m.id, reverse=True)

        for old_msg in matches[keep:]:
            try:
                await old_msg.delete()
            except Exception:
                pass

    except Exception as e:
        print(f"[channel_storage] Cleanup error ({filename}): {e}")


# ==================== SYNC WRAPPERS ====================
async def sync_all_from_channel(client: Client):
    """Download all known files from channel."""
    if not STORAGE_CHANNEL:
        print("[channel_storage] STORAGE_CHANNEL_ID not set — skipping")
        return

    peer = await resolve_peer(client)
    if peer is None:
        print("[channel_storage] Cannot reach channel — aborting sync")
        return

    print("[channel_storage] Syncing from channel...")
    for fname in SYNC_FILES:
        local_path = os.path.join(DATA_DIR, fname)
        await download_latest(client, fname, local_path)
    print("[channel_storage] Sync complete")


async def backup_all_to_channel(client: Client):
    """Upload all local files to channel (with cleanup)."""
    if not STORAGE_CHANNEL:
        return

    peer = await resolve_peer(client)
    if peer is None:
        return

    for fname in SYNC_FILES:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        await upload_gzipped(client, path, fname)
        await delete_old_from_channel(client, fname, keep=KEEP_VERSIONS)
