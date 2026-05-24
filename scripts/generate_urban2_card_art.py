"""Generate Urban 2 individual card art from the 2x5 clan sheets."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
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
CANVAS_SIZE = (768, 1024)
SEARCH_EXPANSION_X = 0.12
SEARCH_EXPANSION_Y = 0.04
FOREGROUND_DISTANCE_THRESHOLD = 30.0
MIN_FOREGROUND_PIXELS_PER_AXIS = 4
MIN_COMPONENT_AREA = 80
SUBJECT_PADDING_RATIO = 0.12
MAX_SUBJECT_WIDTH_RATIO = 0.82
MAX_SUBJECT_HEIGHT_RATIO = 0.9
BOTTOM_ANCHOR_RATIO = 0.94


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
            cropped, detected_rect = crop_character_portrait(
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
                    "detected_rect": {
                        "x": detected_rect.x,
                        "y": detected_rect.y,
                        "width": detected_rect.width,
                        "height": detected_rect.height,
                    },
                    "canvas_size": {
                        "width": cropped.get_width(),
                        "height": cropped.get_height(),
                    },
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


def crop_character_portrait(
    sheet: pygame.Surface,
    *,
    row: int,
    col: int,
    rows: int,
    cols: int,
) -> tuple[pygame.Surface, pygame.Rect]:
    """Detect one character inside its approximate grid slot and center it on a stable portrait canvas."""
    base_rect = grid_cell_rect(sheet, row=row, col=col, rows=rows, cols=cols)
    search_rect = expanded_grid_cell(sheet, row=row, col=col, rows=rows, cols=cols)
    background_color = sample_background_color(sheet)
    detected_rect, selected_components = detect_foreground_bounds(sheet, search_rect, base_rect, background_color)
    padded_rect = pad_rect(detected_rect, search_rect, padding_ratio=SUBJECT_PADDING_RATIO)
    subject = build_clean_subject(sheet, padded_rect, selected_components, background_color)

    portrait = pygame.Surface(CANVAS_SIZE)
    portrait.fill(background_color)

    fitted_subject = scale_subject_to_canvas(subject, portrait.get_size())
    x = (portrait.get_width() - fitted_subject.get_width()) // 2
    y = min(
        portrait.get_height() - fitted_subject.get_height(),
        int(portrait.get_height() * BOTTOM_ANCHOR_RATIO) - fitted_subject.get_height(),
    )
    y = max(0, y)
    portrait.blit(fitted_subject, (x, y))
    remove_edge_artifacts(portrait, background_color)
    return portrait, padded_rect


def expanded_grid_cell(sheet: pygame.Surface, *, row: int, col: int, rows: int, cols: int) -> pygame.Rect:
    """Return a slightly expanded search area around the JSON grid position."""
    base_rect = grid_cell_rect(sheet, row=row, col=col, rows=rows, cols=cols)
    expanded = base_rect.inflate(
        int(base_rect.width * SEARCH_EXPANSION_X),
        int(base_rect.height * SEARCH_EXPANSION_Y),
    )
    row_rect = pygame.Rect(0, base_rect.top, sheet.get_width(), base_rect.height)
    expanded = expanded.clip(row_rect)
    return expanded.clip(sheet.get_rect())


def crop_grid_cell(sheet: pygame.Surface, *, row: int, col: int, rows: int, cols: int) -> pygame.Surface:
    """Crop one atlas cell without resizing or trimming the character."""
    rect = grid_cell_rect(sheet, row=row, col=col, rows=rows, cols=cols)
    cropped = pygame.Surface(rect.size)
    cropped.blit(sheet, (0, 0), rect)
    return cropped


def grid_cell_rect(sheet: pygame.Surface, *, row: int, col: int, rows: int, cols: int) -> pygame.Rect:
    """Return the nominal grid cell rectangle for one row/column."""
    width, height = sheet.get_size()
    if row < 1 or row > rows or col < 1 or col > cols:
        raise ValueError(f"Invalid sheet position row={row}, col={col} for a {rows}x{cols} sheet.")

    x_edges = [round(width * index / cols) for index in range(cols + 1)]
    y_edges = [round(height * index / rows) for index in range(rows + 1)]
    return pygame.Rect(
        x_edges[col - 1],
        y_edges[row - 1],
        x_edges[col] - x_edges[col - 1],
        y_edges[row] - y_edges[row - 1],
    )


def sample_background_color(sheet: pygame.Surface) -> tuple[int, int, int]:
    """Estimate the sheet background color from the outer border pixels."""
    pixels = pygame.surfarray.array3d(sheet).astype(np.int16)
    width, height = sheet.get_size()
    border = max(12, min(width, height) // 60)
    samples = np.concatenate(
        [
            pixels[:border, :, :].reshape(-1, 3),
            pixels[width - border :, :, :].reshape(-1, 3),
            pixels[:, :border, :].reshape(-1, 3),
            pixels[:, height - border :, :].reshape(-1, 3),
        ],
        axis=0,
    )
    median = np.median(samples, axis=0)
    return tuple(int(value) for value in median)


def detect_foreground_bounds(
    sheet: pygame.Surface,
    search_rect: pygame.Rect,
    base_rect: pygame.Rect,
    background_color: tuple[int, int, int],
) -> tuple[pygame.Rect, list[pygame.Rect]]:
    """Find the subject bounds by comparing the search area to the sampled background."""
    pixels = pygame.surfarray.array3d(sheet).astype(np.int16)
    left, top, width, height = search_rect
    region = pixels[left : left + width, top : top + height, :]
    background = np.array(background_color, dtype=np.int16)
    distance = np.linalg.norm(region - background, axis=2)
    mask = distance > FOREGROUND_DISTANCE_THRESHOLD

    component_rects = component_bounds_for_character(mask, search_rect=search_rect, base_rect=base_rect)
    if component_rects:
        return union_rects(component_rects).clip(search_rect), component_rects

    x_counts = mask.sum(axis=1)
    y_counts = mask.sum(axis=0)
    x_indices = np.flatnonzero(x_counts >= MIN_FOREGROUND_PIXELS_PER_AXIS)
    y_indices = np.flatnonzero(y_counts >= MIN_FOREGROUND_PIXELS_PER_AXIS)

    if x_indices.size == 0 or y_indices.size == 0:
        return search_rect, [search_rect]

    detected = pygame.Rect(
        left + int(x_indices[0]),
        top + int(y_indices[0]),
        int(x_indices[-1] - x_indices[0] + 1),
        int(y_indices[-1] - y_indices[0] + 1),
    )
    clipped = detected.clip(search_rect)
    return clipped, [clipped]


def build_clean_subject(
    sheet: pygame.Surface,
    crop_rect: pygame.Rect,
    selected_components: list[pygame.Rect],
    background_color: tuple[int, int, int],
) -> pygame.Surface:
    """Crop the subject and neutralize detected foreground pieces outside selected components."""
    subject = pygame.Surface(crop_rect.size)
    subject.blit(sheet, (0, 0), crop_rect)

    pixels = pygame.surfarray.array3d(subject).astype(np.int16)
    background = np.array(background_color, dtype=np.int16)
    keep_mask = np.zeros(pixels.shape[:2], dtype=bool)

    for component in selected_components:
        local = component.clip(crop_rect).move(-crop_rect.left, -crop_rect.top)
        if local.width <= 0 or local.height <= 0:
            continue
        keep_mask[local.left : local.right, local.top : local.bottom] = True

    cleaned = pixels.copy()
    cleaned[~keep_mask] = background

    foreground_mask = np.linalg.norm(pixels - background, axis=2) > FOREGROUND_DISTANCE_THRESHOLD
    for component_rect, component_points in foreground_components_in_crop(foreground_mask, crop_rect):
        if component_matches_selected_rect(component_rect, selected_components):
            continue
        local_rect = component_rect.clip(crop_rect).move(-crop_rect.left, -crop_rect.top).inflate(8, 8)
        local_rect = local_rect.clip(pygame.Rect(0, 0, crop_rect.width, crop_rect.height))
        cleaned[local_rect.left : local_rect.right, local_rect.top : local_rect.bottom] = background
        for x, y in component_points:
            cleaned[x, y] = background

    cleaned_surface = pygame.Surface(crop_rect.size)
    pygame.surfarray.blit_array(cleaned_surface, cleaned.astype(np.uint8))
    return cleaned_surface


def foreground_components_in_crop(
    mask: np.ndarray,
    crop_rect: pygame.Rect,
) -> list[tuple[pygame.Rect, list[tuple[int, int]]]]:
    """Return exact foreground components inside a cropped subject surface."""
    visited = np.zeros(mask.shape, dtype=bool)
    width, height = mask.shape[0], mask.shape[1]
    components: list[tuple[pygame.Rect, list[tuple[int, int]]]] = []

    for start_x, start_y in np.argwhere(mask):
        start_x = int(start_x)
        start_y = int(start_y)
        if visited[start_x, start_y]:
            continue

        stack = [(start_x, start_y)]
        visited[start_x, start_y] = True
        points: list[tuple[int, int]] = []
        min_x = max_x = start_x
        min_y = max_y = start_y

        while stack:
            x, y = stack.pop()
            points.append((x, y))
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

            for next_x in (x - 1, x, x + 1):
                for next_y in (y - 1, y, y + 1):
                    if next_x == x and next_y == y:
                        continue
                    if next_x < 0 or next_y < 0 or next_x >= width or next_y >= height:
                        continue
                    if visited[next_x, next_y] or not mask[next_x, next_y]:
                        continue
                    visited[next_x, next_y] = True
                    stack.append((next_x, next_y))

        if len(points) < MIN_COMPONENT_AREA:
            continue

        component_rect = pygame.Rect(
            crop_rect.left + min_x,
            crop_rect.top + min_y,
            max_x - min_x + 1,
            max_y - min_y + 1,
        )
        components.append((component_rect, points))

    return components


def component_matches_selected_rect(component_rect: pygame.Rect, selected_components: list[pygame.Rect]) -> bool:
    """Return whether a foreground component corresponds to one of the selected subject components."""
    component_area = max(1, component_rect.width * component_rect.height)
    for selected_rect in selected_components:
        intersection = component_rect.clip(selected_rect)
        intersection_area = intersection.width * intersection.height
        if intersection_area == 0:
            continue
        selected_area = max(1, selected_rect.width * selected_rect.height)
        component_coverage = intersection_area / component_area
        selected_coverage = intersection_area / selected_area
        if component_coverage >= 0.75 and selected_coverage >= 0.35:
            return True
    return False


def component_bounds_for_character(
    mask: np.ndarray,
    *,
    search_rect: pygame.Rect,
    base_rect: pygame.Rect,
) -> list[pygame.Rect]:
    """Return foreground components whose center belongs to the requested grid slot."""
    height, width = mask.shape[1], mask.shape[0]
    visited = np.zeros(mask.shape, dtype=bool)
    components: list[tuple[pygame.Rect, int]] = []

    for start_x, start_y in np.argwhere(mask):
        start_x = int(start_x)
        start_y = int(start_y)
        if visited[start_x, start_y]:
            continue

        stack = [(start_x, start_y)]
        visited[start_x, start_y] = True
        min_x = max_x = start_x
        min_y = max_y = start_y
        area = 0

        while stack:
            x, y = stack.pop()
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

            for next_x in (x - 1, x, x + 1):
                for next_y in (y - 1, y, y + 1):
                    if next_x == x and next_y == y:
                        continue
                    if next_x < 0 or next_y < 0 or next_x >= width or next_y >= height:
                        continue
                    if visited[next_x, next_y] or not mask[next_x, next_y]:
                        continue
                    visited[next_x, next_y] = True
                    stack.append((next_x, next_y))

        if area < MIN_COMPONENT_AREA:
            continue

        rect = pygame.Rect(
            search_rect.left + min_x,
            search_rect.top + min_y,
            max_x - min_x + 1,
            max_y - min_y + 1,
        )
        if base_rect.collidepoint(rect.center):
            components.append((rect, area))

    if not components:
        return []

    anchor = (
        base_rect.centerx,
        base_rect.top + int(base_rect.height * 0.58),
    )
    base_area = max(1, base_rect.width * base_rect.height)

    def component_score(component: tuple[pygame.Rect, int]) -> float:
        rect, area = component
        dx = (rect.centerx - anchor[0]) / max(1, base_rect.width)
        dy = (rect.centery - anchor[1]) / max(1, base_rect.height)
        area_bonus = min(0.18, area / base_area)
        return (dx * dx) + (dy * dy) - area_bonus

    primary_rect, primary_area = min(components, key=component_score)
    attachment_zone = primary_rect.inflate(
        int(primary_rect.width * 0.7),
        int(primary_rect.height * 0.45),
    )

    selected = [primary_rect]
    for rect, _area in components:
        if rect == primary_rect:
            continue
        touches_search_edge = (
            rect.left <= search_rect.left + 2
            or rect.right >= search_rect.right - 2
            or rect.top <= search_rect.top + 2
            or rect.bottom >= search_rect.bottom - 2
        )
        relative_center_x = (rect.centerx - base_rect.left) / max(1, base_rect.width)
        relative_center_y = (rect.centery - base_rect.top) / max(1, base_rect.height)
        center_is_on_cell_edge = (
            relative_center_x < 0.12
            or relative_center_x > 0.88
            or relative_center_y < 0.05
            or relative_center_y > 0.98
        )
        separated_from_primary = not rect.colliderect(primary_rect.inflate(20, 20))
        if touches_search_edge and center_is_on_cell_edge and _area < primary_area * 0.9:
            continue
        if touches_search_edge and separated_from_primary and _area < primary_area * 0.8:
            continue
        if attachment_zone.collidepoint(rect.center):
            selected.append(rect)

    return selected


def union_rects(rects: list[pygame.Rect]) -> pygame.Rect:
    """Return one rectangle containing all provided rectangles."""
    combined = rects[0].copy()
    for rect in rects[1:]:
        combined.union_ip(rect)
    return combined


def pad_rect(rect: pygame.Rect, bounds: pygame.Rect, *, padding_ratio: float) -> pygame.Rect:
    """Add breathing room around a detected character rectangle."""
    padding_x = max(12, int(rect.width * padding_ratio))
    padding_y = max(16, int(rect.height * padding_ratio))
    return rect.inflate(padding_x * 2, padding_y * 2).clip(bounds)


def scale_subject_to_canvas(subject: pygame.Surface, canvas_size: tuple[int, int]) -> pygame.Surface:
    """Scale a detected subject crop to fit comfortably inside the portrait canvas."""
    canvas_width, canvas_height = canvas_size
    target_width = int(canvas_width * MAX_SUBJECT_WIDTH_RATIO)
    target_height = int(canvas_height * MAX_SUBJECT_HEIGHT_RATIO)
    scale = min(target_width / subject.get_width(), target_height / subject.get_height())
    scaled_size = (
        max(1, int(subject.get_width() * scale)),
        max(1, int(subject.get_height() * scale)),
    )
    return pygame.transform.smoothscale(subject, scaled_size)


def remove_edge_artifacts(surface: pygame.Surface, background_color: tuple[int, int, int]) -> None:
    """Erase small foreground fragments that still touch the final portrait edges."""
    pixels = pygame.surfarray.array3d(surface).astype(np.int16)
    background = np.array(background_color, dtype=np.int16)
    mask = np.linalg.norm(pixels - background, axis=2) > FOREGROUND_DISTANCE_THRESHOLD
    visited = np.zeros(mask.shape, dtype=bool)
    width, height = mask.shape[0], mask.shape[1]
    components: list[tuple[int, bool, list[tuple[int, int]]]] = []

    for start_x, start_y in np.argwhere(mask):
        start_x = int(start_x)
        start_y = int(start_y)
        if visited[start_x, start_y]:
            continue

        stack = [(start_x, start_y)]
        visited[start_x, start_y] = True
        points: list[tuple[int, int]] = []
        touches_edge = False

        while stack:
            x, y = stack.pop()
            points.append((x, y))
            touches_edge = touches_edge or x == 0 or y == 0 or x == width - 1 or y == height - 1

            for next_x in (x - 1, x, x + 1):
                for next_y in (y - 1, y, y + 1):
                    if next_x == x and next_y == y:
                        continue
                    if next_x < 0 or next_y < 0 or next_x >= width or next_y >= height:
                        continue
                    if visited[next_x, next_y] or not mask[next_x, next_y]:
                        continue
                    visited[next_x, next_y] = True
                    stack.append((next_x, next_y))

        if len(points) >= MIN_COMPONENT_AREA:
            components.append((len(points), touches_edge, points))

    if not components:
        return

    largest_area = max(area for area, _touches_edge, _points in components)
    cleaned = pixels.copy()
    for area, touches_edge, points in components:
        if not touches_edge or area >= largest_area * 0.35:
            continue
        for x, y in points:
            cleaned[x, y] = background

    pygame.surfarray.blit_array(surface, cleaned.astype(np.uint8))


def main() -> None:
    """Generate cropped Urban 2 card art assets."""
    manifest = generate_art()
    print(f"Generated {len(manifest['entries'])} Urban 2 card illustrations into {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
