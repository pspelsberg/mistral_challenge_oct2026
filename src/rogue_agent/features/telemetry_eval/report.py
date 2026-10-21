"""Version-segregated benchmark aggregation and <2min demo GIF exporter (Sections 1, 15, 17).

Rule: Never combine or directly compare gameplay scores across different Rogue versions
(e.g. 'epyx-1.49' vs 'rogue-5.4.4') as if they had identical difficulty.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def aggregate_runs_by_version(runs_dir: Path = Path("./runs")) -> dict[str, dict[str, Any]]:
    """Aggregate all completed run summaries strictly grouped by `<backend>:<rogue_version>`."""
    if not runs_dir.is_dir():
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for summary_file in sorted(runs_dir.glob("*/summary.json")):
        try:
            data = json.loads(summary_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = f"{data.get('backend', 'unknown')}:{data.get('rogue_version', 'unknown')}"
        grouped.setdefault(key, []).append(data)

    report: dict[str, dict[str, Any]] = {}
    for key, summaries in grouped.items():
        n = len(summaries)
        turns_list = [int(s.get("turns_survived", 0)) for s in summaries]
        depth_list = [int(s.get("max_dungeon_depth_reached", 1)) for s in summaries]
        rooms_list = [int(s.get("rooms_discovered", 1)) for s in summaries]
        monsters_list = [int(s.get("monsters_defeated", 0)) for s in summaries]
        gold_list = [int(s.get("max_gold_collected", 0)) for s in summaries]
        inv_pct_list = [float(s.get("invalid_action_percentage", 0.0)) for s in summaries]
        cost_list = [float(s.get("estimated_cost_usd", 0.0)) for s in summaries]

        report[key] = {
            "runs_count": n,
            "backend": summaries[0].get("backend"),
            "rogue_version": summaries[0].get("rogue_version"),
            "avg_turns_survived": round(sum(turns_list) / n, 2),
            "max_turns_survived": max(turns_list),
            "max_depth_reached": max(depth_list),
            "max_rooms_discovered": max(rooms_list),
            "total_monsters_defeated": sum(monsters_list),
            "max_gold_collected": max(gold_list),
            "avg_invalid_action_percentage": round(sum(inv_pct_list) / n, 2),
            "total_estimated_cost_usd": round(sum(cost_list), 6),
        }

    return report


def _render_ascii_frame_to_image(ascii_text: str, title: str) -> Image.Image:
    """Render an 80x24/80x25 ASCII frame into a 640x420 dark terminal image for GIF export."""
    img = Image.new("RGB", (640, 420), (14, 16, 22))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 640, 22), fill=(32, 38, 52))
    draw.text((8, 4), title, fill=(100, 220, 170))
    y = 28
    for line in ascii_text.splitlines()[:25]:
        draw.text((8, y), line[:85], fill=(220, 225, 230))
        y += 15
    return img


def export_session_gif(
    session_dir: Path,
    output_path: Path | None = None,
    frame_duration_ms: int = 350,
    max_frames: int = 300,
) -> Path:
    """Export a recorded session's frames into a competition-ready (< 2 min) animated GIF."""
    frames_dir = session_dir / "frames"
    if not frames_dir.is_dir():
        raise FileNotFoundError(f"No frames directory found in {session_dir}")

    png_files = sorted(frames_dir.glob("turn_*.png"))[:max_frames]
    pil_frames: list[Image.Image] = []

    if png_files:
        for p in png_files:
            with Image.open(p) as im:
                pil_frames.append(im.convert("RGB"))
    else:
        txt_files = sorted(frames_dir.glob("turn_*.txt"))[:max_frames]
        for t in txt_files:
            text = t.read_text(encoding="utf-8")
            pil_frames.append(
                _render_ascii_frame_to_image(text, f"{session_dir.name} — {t.stem}")
            )

    if not pil_frames:
        raise ValueError(f"No turn frames (.png or .txt) found in {frames_dir}")

    # Enforce < 2 minutes (120,000 ms) competition limit
    total_ms = len(pil_frames) * frame_duration_ms
    if total_ms > 115_000:
        frame_duration_ms = max(50, 115_000 // len(pil_frames))

    dest = output_path or (session_dir / "demo.gif")
    pil_frames[0].save(
        dest,
        save_all=True,
        append_images=pil_frames[1:],
        duration=frame_duration_ms,
        loop=0,
        optimize=True,
    )
    return dest
