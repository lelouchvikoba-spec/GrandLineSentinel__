# level_card.py
import os
from io import BytesIO

from config import FONTS_DIR, IMAGES_DIR, BOT_NAME

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ---------- palette ----------
LEVEL_UP_BG = (30, 45, 70)
LEVEL_UP_ACCENT = (60, 180, 90)
LEVEL_UP_TEXT = (255, 255, 255)
LEVEL_UP_SUB = (200, 230, 200)

LEVEL_DOWN_BG = (55, 20, 25)
LEVEL_DOWN_ACCENT = (200, 60, 60)
LEVEL_DOWN_TEXT = (255, 230, 230)
LEVEL_DOWN_SUB = (230, 180, 180)


def _load_font(size, bold=False):
    if not PIL_AVAILABLE:
        return None
    candidates = [
        "TimesNewRoman-Bold.ttf" if bold else "times.ttf",
        "TimesNewRomanBold.ttf" if bold else "TimesNewRoman.ttf",
        "arial.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for fname in candidates:
        p = os.path.join(FONTS_DIR, fname)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _draw_centered(draw, text, font, y, fill, W):
    if font is None:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (W - tw) // 2
    draw.text((x, y), text, fill=fill, font=font)
    return th


def _load_custom_base(kind):
    candidates = []
    if kind == "up":
        candidates = ["levelup.jpg", "levelup.jpeg", "levelup.png"]
    else:
        candidates = ["leveldown.jpg", "leveldown.jpeg", "leveldown.png"]

    for fname in candidates:
        path = os.path.join(IMAGES_DIR, fname)
        if os.path.exists(path):
            try:
                return Image.open(path).convert("RGB")
            except Exception:
                continue
    return None


def generate_level_card(
    kind,
    old_level,
    new_level,
    rank,
    title,
    medal="",
    source_label="",
    player_name="",
):
    """
    Generate a level card image. Returns BytesIO or None.
    kind: "up" or "down"
    """
    if not PIL_AVAILABLE:
        return None

    try:
        W, H = 1200, 600

        img = _load_custom_base(kind)
        if img is None:
            if kind == "up":
                bg = LEVEL_UP_BG
                accent = LEVEL_UP_ACCENT
                title_color = LEVEL_UP_TEXT
                sub_color = LEVEL_UP_SUB
                header = "LEVEL UP!"
            else:
                bg = LEVEL_DOWN_BG
                accent = LEVEL_DOWN_ACCENT
                title_color = LEVEL_DOWN_TEXT
                sub_color = LEVEL_DOWN_SUB
                header = "LEVEL DOWN!"

            img = Image.new("RGB", (W, H), bg)
            draw = ImageDraw.Draw(img)

            for i in range(-H, W, 80):
                draw.line(
                    [(i, 0), (i + H, H)],
                    fill=tuple(min(255, c + 15) for c in bg),
                    width=3,
                )

            draw.rectangle([(0, 0), (W, 12)], fill=accent)
            draw.rectangle([(0, H - 12), (W, H)], fill=accent)

            font_header = _load_font(120, bold=True)
            _draw_centered(draw, header, font_header, 40, title_color, W)

            font_level = _load_font(140, bold=True)
            level_text = f"{old_level}  ➜  {new_level}"
            _draw_centered(draw, level_text, font_level, 200, accent, W)

            font_rank = _load_font(52)
            _draw_centered(draw, rank, font_rank, 380, title_color, W)

            font_title = _load_font(46)
            title_text = (
                title.replace("👑🔥", "").replace("🌊", "")
                .replace("👑", "").replace("⚔️", "")
                .replace("💥", "").replace("🗺️", "")
                .replace("🎯", "").replace("⚓", "")
                .replace("🧹", "").replace("🏴‍☠️", "").strip()
            )
            _draw_centered(draw, title_text, font_title, 450, sub_color, W)

            if source_label:
                font_src = _load_font(36)
                _draw_centered(draw, source_label, font_src, 520, sub_color, W)

        else:
            img = img.resize((W, H))
            draw = ImageDraw.Draw(img)
            accent = LEVEL_UP_ACCENT if kind == "up" else LEVEL_DOWN_ACCENT
            title_color = LEVEL_UP_TEXT if kind == "up" else LEVEL_DOWN_TEXT
            sub_color = LEVEL_UP_SUB if kind == "up" else LEVEL_DOWN_SUB

            font_header = _load_font(120, bold=True)
            font_level = _load_font(140, bold=True)
            font_rank = _load_font(52)
            font_src = _load_font(36)

            header = "LEVEL UP!" if kind == "up" else "LEVEL DOWN!"
            _draw_centered(draw, header, font_header, 30, title_color, W)

            level_text = f"{old_level}  ➜  {new_level}"
            _draw_centered(draw, level_text, font_level, 180, accent, W)

            _draw_centered(draw, rank, font_rank, 380, title_color, W)

            if source_label:
                _draw_centered(draw, source_label, font_src, 470, sub_color, W)

            if player_name:
                font_pn = _load_font(48)
                _draw_centered(draw, player_name, font_pn, 530, sub_color, W)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)
        buf.name = "levelup.jpg" if kind == "up" else "leveldown.jpg"
        return buf

    except Exception as e:
        print(f"[level_card] {e}")
        return None