"""Generate individual Urban 2 character illustrations from clan sheets."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROSTER_PATH = PROJECT_ROOT / "assets" / "data" / "urban2_personnages_base.json"
CLAN_SHEETS_ROOT = PROJECT_ROOT / "assets" / "clans"
OUTPUT_ROOT = PROJECT_ROOT / "assets" / "cards" / "urban2"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
GRID_ROWS = 2
GRID_COLUMNS = 5

SOURCE_SHEET_BY_CLAN_ID = {
    "solaires": CLAN_SHEETS_ROOT / "solaires.png",
    "corsaires_du_port": CLAN_SHEETS_ROOT / "corsaires.png",
    "palmeros": CLAN_SHEETS_ROOT / "palmeros.jfif",
    "egoutiers": CLAN_SHEETS_ROOT / "egoutiers.png",
    "jardiniers_de_beton": CLAN_SHEETS_ROOT / "jardiniers.png",
}

OUTPUT_SHEET_BY_CLAN_ID = {
    "solaires": CLAN_SHEETS_ROOT / "solaires.png",
    "corsaires_du_port": CLAN_SHEETS_ROOT / "corsaires.png",
    "palmeros": CLAN_SHEETS_ROOT / "palmeros.png",
    "egoutiers": CLAN_SHEETS_ROOT / "egoutiers.png",
    "jardiniers_de_beton": CLAN_SHEETS_ROOT / "jardiniers.png",
}


def slugify(value: str) -> str:
    """Return a deterministic ASCII identifier while keeping display names elsewhere."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_value = ascii_value.replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def load_source_roster(path: Path) -> dict[str, object]:
    """Read the Urban 2 source JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def crop_grid_slot(sheet: pygame.Surface, *, row: int, column: int) -> pygame.Surface:
    """Crop one character slot from the fixed 2x5 clan sheet grid."""
    width, height = sheet.get_size()
    x_edges = [round(width * index / GRID_COLUMNS) for index in range(GRID_COLUMNS + 1)]
    y_edges = [round(height * index / GRID_ROWS) for index in range(GRID_ROWS + 1)]
    left = x_edges[column - 1]
    top = y_edges[row - 1]
    slot_width = x_edges[column] - left
    slot_height = y_edges[row] - top

    cropped = pygame.Surface((slot_width, slot_height), pygame.SRCALPHA)
    cropped.blit(sheet, (0, 0), pygame.Rect(left, top, slot_width, slot_height))
    return cropped


def ensure_expected_clan_sheet_aliases() -> None:
    """Create normalized clan sheet filenames expected by the runtime mapping."""
    pygame.init()
    try:
        for clan_id, output_path in OUTPUT_SHEET_BY_CLAN_ID.items():
            if output_path.exists():
                continue

            source_path = SOURCE_SHEET_BY_CLAN_ID[clan_id]
            if not source_path.exists():
                raise FileNotFoundError(f"Missing source clan sheet: {source_path}")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            image = pygame.image.load(str(source_path))
            pygame.image.save(image, str(output_path))
    finally:
        pygame.quit()


def generate_art() -> dict[str, object]:
    """Generate one individual PNG per Urban 2 character plus a manifest."""
    payload = load_source_roster(SOURCE_ROSTER_PATH)
    clans = payload.get("clans", [])
    characters = payload.get("characters", [])
    clan_name_by_id = {
        slugify(clan["name"]): clan["name"]
        for clan in clans
        if isinstance(clan, dict) and isinstance(clan.get("name"), str)
    }

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, object]] = []

    pygame.init()
    try:
        sheet_cache: dict[str, pygame.Surface] = {}
        for character in characters:
            if not isinstance(character, dict):
                continue

            clan_name = str(character["clan"])
            clan_id = slugify(clan_name)
            source_sheet_path = SOURCE_SHEET_BY_CLAN_ID[clan_id]
            if clan_id not in sheet_cache:
                if not source_sheet_path.exists():
                    raise FileNotFoundError(f"Missing source clan sheet: {source_sheet_path}")
                sheet_cache[clan_id] = pygame.image.load(str(source_sheet_path))

            sheet_position = character["sheet_position"]
            row = int(sheet_position["row"])
            column = int(sheet_position["column"])
            cropped = crop_grid_slot(sheet_cache[clan_id], row=row, column=column)

            card_id = slugify(str(character["name"]))
            clan_output_dir = OUTPUT_ROOT / clan_id
            clan_output_dir.mkdir(parents=True, exist_ok=True)
            output_path = clan_output_dir / f"{card_id}.png"
            pygame.image.save(cropped, str(output_path))

            manifest_entries.append(
                {
                    "card_id": card_id,
                    "card_name": character["name"],
                    "clan_id": clan_id,
                    "clan_name": clan_name_by_id.get(clan_id, clan_name),
                    "source_sheet": source_sheet_path.relative_to(PROJECT_ROOT).as_posix(),
                    "grid_position": {
                        "row": row,
                        "column": column,
                        "position": sheet_position.get("position"),
                        "order": sheet_position.get("order"),
                    },
                    "output_path": output_path.relative_to(PROJECT_ROOT).as_posix(),
                }
            )
    finally:
        pygame.quit()

    manifest = {
        "version": 1,
        "source_roster": SOURCE_ROSTER_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "grid": {"rows": GRID_ROWS, "columns": GRID_COLUMNS},
        "entries": manifest_entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    """Generate normalized clan sheets and individual character images."""
    ensure_expected_clan_sheet_aliases()
    manifest = generate_art()
    print(f"Generated {len(manifest['entries'])} Urban 2 illustrations into {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
