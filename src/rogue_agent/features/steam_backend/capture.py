"""Client-area screenshot capture, DOSBox titlebar stripping, and token-efficient encoding."""

from __future__ import annotations

import io
from dataclasses import dataclass

import mss
from PIL import Image
from Xlib import X

from rogue_agent.features.steam_backend.window_manager import WindowInfo, X11WindowManager


@dataclass(frozen=True)
class CropMargins:
    """Configurable pixel margins to trim window borders if needed."""

    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


def strip_wine_dosbox_chrome(image: Image.Image) -> Image.Image:
    """Strip the Wine/DOSBox window title bar (29px) and 3px frame in both 320x200 and 640x400 modes."""
    w, h = image.size
    if 642 <= w <= 660 and 420 <= h <= 450:
        pad_x = (w - 640) // 2
        pad_bottom = 3
        pad_top = h - 400 - pad_bottom
        if pad_top >= 20:
            return image.crop((pad_x, pad_top, pad_x + 640, pad_top + 400))
    if 322 <= w <= 340 and 220 <= h <= 250:
        pad_x = (w - 320) // 2
        pad_bottom = 3
        pad_top = h - 200 - pad_bottom
        if pad_top >= 20:
            return image.crop((pad_x, pad_top, pad_x + 320, pad_top + 200))
    return image


def capture_window_client_area(
    window_manager: X11WindowManager,
    win_info: WindowInfo,
    crop_margins: CropMargins | None = None,
    compact_for_api: bool = True,
) -> tuple[Image.Image, bytes]:
    """Capture strictly the client area of the verified game window and encode compactly."""
    win = window_manager.get_xlib_window(win_info.window_id)
    width = win_info.width
    height = win_info.height

    img: Image.Image | None = None
    try:
        raw = win.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)
        data = raw.data
        if isinstance(data, str):
            data = data.encode("latin1")
        img = Image.frombytes("RGB", (width, height), data, "raw", "BGRX")
    except Exception:
        # Fallback to mss strictly bounded to the verified window rectangle
        with mss.mss() as sct:
            region = {
                "left": max(0, win_info.x),
                "top": max(0, win_info.y),
                "width": width,
                "height": height,
            }
            shot = sct.grab(region)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    img = strip_wine_dosbox_chrome(img)

    if crop_margins and (
        crop_margins.top or crop_margins.bottom or crop_margins.left or crop_margins.right
    ):
        cw, ch = img.size
        left = min(crop_margins.left, cw // 4)
        top = min(crop_margins.top, ch // 4)
        right = max(left + 64, cw - min(crop_margins.right, cw // 4))
        bottom = max(top + 64, ch - min(crop_margins.bottom, ch // 4))
        img = img.crop((left, top, right, bottom))

    encode_img = img
    if compact_for_api and img.width > 480:
        # Downscale 640x400 -> 480x300 with nearest-neighbor and 32-color CGA/EGA palette
        # to minimize vision token footprint and PNG byte size without losing CP437 legibility
        target_h = max(150, int(round(img.height * (480.0 / img.width))))
        resized = img.resize((480, target_h), Image.Resampling.NEAREST)
        encode_img = resized.quantize(colors=32, method=Image.Quantize.FASTOCTREE)

    buf = io.BytesIO()
    encode_img.save(buf, format="PNG", optimize=True)
    return img, buf.getvalue()
