"""Generate individual character illustrations from composite clan sheets."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROSTER_PATH = PROJECT_ROOT / "data" / "roster_source.json"
ASSETS_ROOT = PROJECT_ROOT / "assets"
OUTPUT_ROOT = ASSETS_ROOT / "cards"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SHEET_FILENAMES = {
    "pulse_404": "Pulse 404.png",
    "verdelune": "Verdelune.png",
    "bastion_9": "Bastion-9.png",
}


def slugify(value: str) -> str:
    """Return a deterministic filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def load_source_roster(path: Path) -> dict[str, object]:
    """Read the roster source JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def crop_sheet(sheet: pygame.Surface, *, row: int, col: int, rows: int, cols: int) -> pygame.Surface:
    """Crop one slot from a fixed-size grid sheet."""
    width, height = sheet.get_size()
    x_edges = [round(width * index / cols) for index in range(cols + 1)]
    y_edges = [round(height * index / rows) for index in range(rows + 1)]
    x = x_edges[col - 1]
    y = y_edges[row - 1]
    cell_width = x_edges[col] - x
    cell_height = y_edges[row] - y

    if cell_width <= 0 or cell_height <= 0:
        raise ValueError(
            f"Invalid crop size for slot row={row}, col={col} inside {width}x{height} sheet."
        )

    cropped = pygame.Surface((cell_width, cell_height), pygame.SRCALPHA)
    cropped.blit(sheet, (0, 0), pygame.Rect(x, y, cell_width, cell_height))
    return cropped


def generate_art() -> dict[str, object]:
    """Generate all cropped character images and a manifest."""
    payload = load_source_roster(SOURCE_ROSTER_PATH)
    clans = payload.get("clans", [])
    grid_template = payload.get("grid_template", {})
    rows = int(grid_template.get("rows", 2))
    cols = int(grid_template.get("cols", 5))

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, object]] = []

    pygame.init()
    try:
        for clan in clans:
            clan_id = clan["id"]
            clan_name = clan["name"]
            sheet_filename = SHEET_FILENAMES[clan_id]
            sheet_path = ASSETS_ROOT / sheet_filename
            if not sheet_path.exists():
                raise FileNotFoundError(f"Missing composite sheet: {sheet_path}")

            sheet = pygame.image.load(str(sheet_path))
            clan_output_dir = OUTPUT_ROOT / clan_id
            clan_output_dir.mkdir(parents=True, exist_ok=True)

            for character in clan["characters"]:
                character_id = slugify(character["id"])
                position = character["grid_position"]
                cropped = crop_sheet(
                    sheet,
                    row=int(position["row"]),
                    col=int(position["col"]),
                    rows=rows,
                    cols=cols,
                )

                output_path = clan_output_dir / f"{character_id}.png"
                pygame.image.save(cropped, str(output_path))
                manifest_entries.append(
                    {
                        "card_id": character["id"],
                        "card_name": character["name"],
                        "clan_id": clan_id,
                        "clan_name": clan_name,
                        "source_sheet": f"assets/{sheet_filename}",
                        "grid_position": position,
                        "output_path": output_path.relative_to(PROJECT_ROOT).as_posix(),
                    }
                )
    finally:
        pygame.quit()

    manifest = {
        "version": 1,
        "source_roster": SOURCE_ROSTER_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "entries": manifest_entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    """Generate cropped card art assets."""
    manifest = generate_art()
    print(f"Generated {len(manifest['entries'])} card illustrations into {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
