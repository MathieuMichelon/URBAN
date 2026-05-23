"""Generate Urban 2 individual card art from the 2x5 clan sheets."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.urban2_loader import SHEET_BY_CLAN_ID, load_urban2_roster, slugify


SOURCE_ROSTER_PATH = PROJECT_ROOT / "assets" / "data" / "urban2_personnages_base.json"
OUTPUT_ROOT = PROJECT_ROOT / "assets" / "cards" / "urban2"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
ROWS = 2
COLS = 5


def generate_art() -> dict[str, object]:
    """Crop every Urban 2 character slot into the card-art folder."""
    source_payload = json.loads(SOURCE_ROSTER_PATH.read_text(encoding="utf-8"))
    roster = load_urban2_roster(SOURCE_ROSTER_PATH)
    card_by_name = {card.name: card for card in roster.cards}

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, object]] = []

    pygame.init()
    try:
        sheet_cache: dict[str, pygame.Surface] = {}
        for character in source_payload["characters"]:
            clan_id = slugify(character["clan"])
            card = card_by_name[character["name"]]
            sheet_relative_path = SHEET_BY_CLAN_ID[clan_id]
            sheet_path = PROJECT_ROOT / sheet_relative_path
            if not sheet_path.exists():
                raise FileNotFoundError(f"Missing Urban 2 clan sheet: {sheet_path}")

            if sheet_relative_path not in sheet_cache:
                sheet_cache[sheet_relative_path] = pygame.image.load(str(sheet_path))
            sheet = sheet_cache[sheet_relative_path]

            position = character["sheet_position"]
            cropped = crop_grid_cell(
                sheet,
                row=int(position["row"]),
                col=int(position["column"]),
                rows=ROWS,
                cols=COLS,
            )

            output_path = PROJECT_ROOT / card.illustration
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(cropped, str(output_path))
            manifest_entries.append(
                {
                    "card_id": card.id,
                    "card_name": card.name,
                    "clan_id": clan_id,
                    "clan_name": character["clan"],
                    "source_sheet": sheet_relative_path,
                    "sheet_position": position,
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


def crop_grid_cell(sheet: pygame.Surface, *, row: int, col: int, rows: int, cols: int) -> pygame.Surface:
    """Crop one atlas cell without resizing or trimming the character."""
    width, height = sheet.get_size()
    if row < 1 or row > rows or col < 1 or col > cols:
        raise ValueError(f"Invalid sheet position row={row}, col={col} for a {rows}x{cols} sheet.")

    x_edges = [round(width * index / cols) for index in range(cols + 1)]
    y_edges = [round(height * index / rows) for index in range(rows + 1)]
    rect = pygame.Rect(
        x_edges[col - 1],
        y_edges[row - 1],
        x_edges[col] - x_edges[col - 1],
        y_edges[row] - y_edges[row - 1],
    )
    cropped = pygame.Surface(rect.size)
    cropped.blit(sheet, (0, 0), rect)
    return cropped


def main() -> None:
    """Generate cropped Urban 2 card art assets."""
    manifest = generate_art()
    print(f"Generated {len(manifest['entries'])} Urban 2 card illustrations into {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
