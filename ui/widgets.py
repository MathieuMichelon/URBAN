"""Reusable drawing helpers for the Pygame interface."""

from __future__ import annotations

from dataclasses import dataclass

import pygame

Color = tuple[int, int, int]
ImageSurface = pygame.Surface


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    fill: Color,
    border: Color,
    shadow: Color = (12, 16, 28),
    radius: int = 20,
    shadow_offset: tuple[int, int] = (0, 8),
) -> None:
    """Draw a rounded panel with a soft drop shadow."""
    _draw_glow(surface, rect.inflate(10, 10), border, alpha=28, radius=radius + 4)
    shadow_rect = rect.move(*shadow_offset)
    pygame.draw.rect(surface, shadow, shadow_rect, border_radius=radius)
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    pygame.draw.rect(surface, border, rect, width=2, border_radius=radius)
    inner_rect = rect.inflate(-12, -12)
    if inner_rect.width > 0 and inner_rect.height > 0:
        pygame.draw.rect(surface, _mix_color(fill, (255, 255, 255), 0.04), inner_rect, width=1, border_radius=max(8, radius - 6))


def draw_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    color: Color,
    position: tuple[int, int],
    *,
    anchor: str = "topleft",
) -> pygame.Rect:
    """Render text with a chosen anchor."""
    rendered = font.render(text, True, color)
    rect = rendered.get_rect()
    setattr(rect, anchor, position)
    surface.blit(rendered, rect)
    return rect


def draw_wrapped_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    color: Color,
    rect: pygame.Rect,
    *,
    line_gap: int = 4,
    max_lines: int | None = None,
) -> int:
    """Render wrapped text inside a bounding rect and return the bottom y position."""
    words = text.split()
    if not words:
        return rect.top

    lines: list[str] = []
    current_line = words[0]

    for word in words[1:]:
        trial = f"{current_line} {word}"
        if font.size(trial)[0] <= rect.width:
            current_line = trial
            continue

        lines.append(current_line)
        current_line = word

    lines.append(current_line)
    was_truncated = max_lines is not None and len(lines) > max_lines
    if max_lines is not None:
        lines = lines[:max_lines]
    if was_truncated and lines:
        lines[-1] = _fit_text(lines[-1], font, rect.width)

    y = rect.top
    for line in lines:
        line_rect = draw_text(surface, font, line, color, (rect.left, y))
        y = line_rect.bottom + line_gap

    return y - line_gap


@dataclass(frozen=True, slots=True)
class Button:
    """Describe a clickable rounded button."""

    rect: pygame.Rect
    label: str
    accent: Color
    enabled: bool = True

    def contains(self, position: tuple[int, int]) -> bool:
        """Return whether a point lies inside the button."""
        return self.enabled and self.rect.collidepoint(position)

    def draw(
        self,
        surface: pygame.Surface,
        *,
        mouse_pos: tuple[int, int],
        label_font: pygame.font.Font,
        shadow: Color = (11, 16, 27),
    ) -> None:
        """Draw the button with hover and disabled states."""
        hovered = self.enabled and self.rect.collidepoint(mouse_pos)
        fill = _mix_color(self.accent, (13, 18, 29), 0.3) if self.enabled else (42, 48, 64)
        border = _mix_color(self.accent if self.enabled else fill, (255, 255, 255), 0.2 if hovered else 0.08)
        text_color = (247, 249, 252) if self.enabled else (188, 194, 208)

        if self.enabled:
            _draw_glow(surface, self.rect.inflate(12, 12), self.accent, alpha=36 if hovered else 24, radius=18)
        shadow_rect = self.rect.move(0, 5)
        pygame.draw.rect(surface, shadow, shadow_rect, border_radius=16)
        pygame.draw.rect(surface, fill, self.rect, border_radius=16)
        pygame.draw.rect(surface, border, self.rect, width=2, border_radius=16)

        if hovered:
            highlight = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            highlight.fill((255, 255, 255, 18))
            surface.blit(highlight, self.rect)

        draw_text(
            surface,
            label_font,
            self.label,
            text_color,
            self.rect.center,
            anchor="center",
        )


@dataclass(frozen=True, slots=True)
class CardVisual:
    """Describe a card to render on screen."""

    rect: pygame.Rect
    title: str
    clan: str
    stars: int
    power: int
    damage: int
    power_text: str
    bonus_text: str
    accent: Color
    illustration_label: str
    illustration: ImageSurface | None = None
    bonus_active: bool | None = None
    selected: bool = False
    disabled: bool = False
    hidden: bool = False
    show_footer: str | None = None

    def contains(self, position: tuple[int, int]) -> bool:
        """Return whether a point lies inside the card."""
        return self.rect.collidepoint(position)


def draw_card(
    surface: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    visual: CardVisual,
    *,
    mouse_pos: tuple[int, int],
) -> None:
    """Draw one playing card."""
    hovered = visual.rect.collidepoint(mouse_pos) and not visual.disabled
    lift = -6 if visual.selected else -3 if hovered else 0
    rect = visual.rect.move(0, lift)

    border_color = (248, 208, 92) if visual.selected else _mix_color(visual.accent, (255, 255, 255), 0.14)
    body_color = _mix_color(visual.accent, (10, 14, 24), 0.22)
    _draw_glow(surface, rect.inflate(18, 18), visual.accent if not visual.selected else border_color, alpha=46 if visual.selected else 22 if hovered else 12, radius=24)

    draw_panel(
        surface,
        rect,
        fill=body_color,
        border=border_color,
        shadow=(11, 15, 25),
        radius=18,
        shadow_offset=(0, 10),
    )

    if visual.hidden:
        _draw_card_back(surface, rect, visual.accent)
    else:
        _draw_card_front(surface, fonts, rect, visual)

    if visual.disabled:
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        overlay.fill((15, 18, 28, 170))
        surface.blit(overlay, rect)
        draw_text(
            surface,
            fonts["body"],
            "PLAYED",
            (228, 230, 235),
            (rect.centerx, rect.centery),
            anchor="center",
        )


def draw_horizontal_scrollbar(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    content_width: int,
    viewport_width: int,
    offset: int,
    accent: Color,
) -> None:
    """Draw a minimal horizontal scrollbar for card strips."""
    if content_width <= viewport_width or rect.width <= 0 or rect.height <= 0:
        return

    track_color = (33, 39, 56)
    thumb_color = _mix_color(accent, (255, 255, 255), 0.2)
    pygame.draw.rect(surface, track_color, rect, border_radius=rect.height // 2)

    thumb_width = max(36, int(rect.width * (viewport_width / content_width)))
    max_offset = max(1, content_width - viewport_width)
    travel = max(0, rect.width - thumb_width)
    thumb_x = rect.left + int(travel * (max(0, min(offset, max_offset)) / max_offset))
    thumb_rect = pygame.Rect(thumb_x, rect.top, thumb_width, rect.height)
    pygame.draw.rect(surface, thumb_color, thumb_rect, border_radius=rect.height // 2)
    pygame.draw.rect(
        surface,
        _mix_color(thumb_color, (255, 255, 255), 0.18),
        thumb_rect,
        width=1,
        border_radius=rect.height // 2,
    )


def draw_pill_track(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    total: int,
    available: int,
    committed: int,
    accent: Color,
) -> None:
    """Draw a readable pills tracker with remaining and committed states."""
    if total <= 0:
        return

    spacing = 10
    radius = 9
    span = (radius * 2 * total) + spacing * (total - 1)
    start_x = rect.centerx - span // 2
    center_y = rect.centery

    for index in range(total):
        x = start_x + index * ((radius * 2) + spacing) + radius
        color = (74, 81, 98)
        if index < available:
            color = accent
        elif index < available + committed:
            color = (240, 178, 66)

        pygame.draw.circle(surface, color, (x, center_y), radius)
        pygame.draw.circle(surface, _mix_color(color, (255, 255, 255), 0.18), (x, center_y), radius, 2)


def _draw_card_front(
    surface: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    rect: pygame.Rect,
    visual: CardVisual,
) -> None:
    """Draw a visible card face."""
    if rect.height < 250:
        _draw_compact_card_front(surface, fonts, rect, visual)
        return

    content_left = rect.left + 14
    content_width = rect.width - 28
    title = _fit_text(visual.title, fonts["card_title"], content_width)
    draw_text(surface, fonts["card_title"], title, (247, 249, 252), (content_left, rect.top + 12))
    _draw_card_meta_row(surface, fonts, rect, visual, top=rect.top + 42)

    art_rect = pygame.Rect(rect.left + 14, rect.top + 68, rect.width - 28, rect.height - 148)
    pygame.draw.rect(surface, _mix_color(visual.accent, (255, 255, 255), 0.1), art_rect, border_radius=14)
    image_rect = art_rect.inflate(-10, -10)
    _draw_illustration(surface, visual.illustration, image_rect, visual.accent, radius=12)

    if visual.illustration is None:
        for stripe_index in range(5):
            stripe_rect = pygame.Rect(
                art_rect.left + 8,
                art_rect.top + 10 + stripe_index * 20,
                art_rect.width - 16,
                10,
            )
            pygame.draw.rect(
                surface,
                _mix_color(visual.accent, (255, 255, 255), 0.08 + stripe_index * 0.03),
                stripe_rect,
                border_radius=8,
            )

    label_strip = pygame.Rect(rect.left + 14, art_rect.bottom - 36, rect.width - 28, 28)
    label_bg = pygame.Surface(label_strip.size, pygame.SRCALPHA)
    label_bg.fill((8, 11, 20, 170))
    surface.blit(label_bg, label_strip)

    text_rect = pygame.Rect(rect.left + 14, art_rect.bottom + 2, rect.width - 28, 28)
    draw_wrapped_text(surface, fonts["tiny"], f"Power: {visual.power_text}", (222, 229, 241), text_rect, max_lines=2)
    bonus_color = (150, 240, 182) if visual.bonus_active else (255, 191, 150)
    draw_wrapped_text(
        surface,
        fonts["tiny"],
        f"Bonus: {visual.bonus_text} ({'active' if visual.bonus_active else 'inactive'})",
        bonus_color,
        pygame.Rect(rect.left + 14, art_rect.bottom + 32, rect.width - 28, 30),
        max_lines=2,
    )

    _draw_stat_badge(surface, fonts, (rect.left + 18, rect.bottom - 34), "POW", str(visual.power), visual.accent)
    _draw_stat_badge(surface, fonts, (rect.right - 18, rect.bottom - 34), "DMG", str(visual.damage), (221, 105, 87), align_right=True)

    if visual.show_footer:
        draw_text(
            surface,
            fonts["tiny"],
            visual.show_footer,
            (198, 205, 217),
            (rect.centerx, rect.bottom - 16),
            anchor="midbottom",
        )


def _draw_compact_card_front(
    surface: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    rect: pygame.Rect,
    visual: CardVisual,
) -> None:
    """Draw a more compact card face for shorter hand rows."""
    content_left = rect.left + 12
    content_width = rect.width - 24
    title = _fit_text(visual.title, fonts["card_title"], content_width)
    draw_text(surface, fonts["card_title"], title, (247, 249, 252), (content_left, rect.top + 10))
    _draw_card_meta_row(surface, fonts, rect, visual, top=rect.top + 36, compact=True)

    art_rect = pygame.Rect(rect.left + 12, rect.top + 56, rect.width - 24, max(40, rect.height - 132))
    pygame.draw.rect(surface, _mix_color(visual.accent, (255, 255, 255), 0.12), art_rect, border_radius=12)
    image_rect = art_rect.inflate(-8, -8)
    _draw_illustration(surface, visual.illustration, image_rect, visual.accent, radius=10)

    if visual.illustration is None:
        for stripe_index in range(3):
            stripe_rect = pygame.Rect(
                art_rect.left + 8,
                art_rect.top + 8 + stripe_index * 14,
                art_rect.width - 16,
                8,
            )
            pygame.draw.rect(
                surface,
                _mix_color(visual.accent, (255, 255, 255), 0.08 + stripe_index * 0.03),
                stripe_rect,
                border_radius=6,
            )

    ability_strip = pygame.Rect(rect.left + 12, art_rect.bottom - 28, rect.width - 24, 24)
    ability_bg = pygame.Surface(ability_strip.size, pygame.SRCALPHA)
    ability_bg.fill((8, 10, 18, 170))
    surface.blit(ability_bg, ability_strip)

    draw_wrapped_text(
        surface,
        fonts["tiny"],
        f"P: {visual.power_text}",
        (222, 229, 241),
        pygame.Rect(rect.left + 12, art_rect.bottom + 4, rect.width - 24, 24),
        max_lines=2,
    )
    bonus_color = (150, 240, 182) if visual.bonus_active else (255, 191, 150)
    draw_wrapped_text(
        surface,
        fonts["tiny"],
        f"B: {visual.bonus_text} ({'on' if visual.bonus_active else 'off'})",
        bonus_color,
        pygame.Rect(rect.left + 12, art_rect.bottom + 26, rect.width - 24, 24),
        max_lines=2,
    )

    badge_y = rect.bottom - 28
    _draw_stat_badge(surface, fonts, (rect.left + 18, badge_y), "POW", str(visual.power), visual.accent)
    _draw_stat_badge(surface, fonts, (rect.right - 18, badge_y), "DMG", str(visual.damage), (221, 105, 87), align_right=True)

    if visual.show_footer:
        draw_text(
            surface,
            fonts["tiny"],
            visual.show_footer,
            (198, 205, 217),
            (rect.right - 12, rect.top + 10),
            anchor="topright",
        )


def _draw_card_back(surface: pygame.Surface, rect: pygame.Rect, accent: Color) -> None:
    """Draw the opponent card back."""
    inset = rect.inflate(-20, -20)
    pygame.draw.rect(surface, _mix_color(accent, (21, 26, 39), 0.74), inset, border_radius=16)
    pygame.draw.rect(surface, _mix_color(accent, (255, 255, 255), 0.18), inset, width=3, border_radius=16)

    center = inset.center
    pygame.draw.circle(surface, _mix_color(accent, (255, 255, 255), 0.15), center, 34)
    pygame.draw.circle(surface, _mix_color(accent, (20, 25, 38), 0.78), center, 18)

    for line_index in range(4):
        y = inset.top + 26 + line_index * 22
        pygame.draw.line(surface, _mix_color(accent, (255, 255, 255), 0.12), (inset.left + 18, y), (inset.right - 18, y), 3)


def _draw_card_meta_row(
    surface: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    rect: pygame.Rect,
    visual: CardVisual,
    *,
    top: int,
    compact: bool = False,
) -> None:
    """Draw clan badge, clan name, and star count."""
    clan_code, clan_color = _clan_style(visual.clan)
    badge_width = 36 if compact else 42
    badge_height = 18 if compact else 20
    badge_rect = pygame.Rect(rect.left + 12, top, badge_width, badge_height)
    pygame.draw.rect(surface, clan_color, badge_rect, border_radius=badge_height // 2)
    pygame.draw.rect(
        surface,
        _mix_color(clan_color, (255, 255, 255), 0.22),
        badge_rect,
        width=1,
        border_radius=badge_height // 2,
    )
    draw_text(
        surface,
        fonts["tiny"],
        clan_code,
        (248, 250, 252),
        badge_rect.center,
        anchor="center",
    )

    stars_text = "*" * max(1, visual.stars)
    stars_width = fonts["tiny"].size(stars_text)[0]
    clan_left = badge_rect.right + 8
    clan_width = rect.right - 12 - clan_left - stars_width - 10
    clan_label = _fit_text(visual.clan, fonts["tiny"], max(10, clan_width))
    draw_text(surface, fonts["tiny"], clan_label, (206, 215, 230), (clan_left, top + 2))
    draw_text(
        surface,
        fonts["tiny"],
        stars_text,
        (244, 208, 116),
        (rect.right - 12, top + 2),
        anchor="topright",
    )


def _draw_stat_badge(
    surface: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    anchor: tuple[int, int],
    label: str,
    value: str,
    color: Color,
    *,
    align_right: bool = False,
) -> None:
    """Draw a pill-shaped card stat badge."""
    rect = pygame.Rect(0, 0, 64, 42)
    if align_right:
        rect.midright = anchor
    else:
        rect.midleft = anchor

    pygame.draw.rect(surface, color, rect, border_radius=16)
    pygame.draw.rect(surface, _mix_color(color, (255, 255, 255), 0.16), rect, width=2, border_radius=16)

    draw_text(surface, fonts["tiny"], label, (239, 243, 247), (rect.centerx, rect.top + 7), anchor="midtop")
    draw_text(surface, fonts["body"], value, (255, 255, 255), (rect.centerx, rect.bottom - 7), anchor="midbottom")


def _draw_illustration(
    surface: pygame.Surface,
    illustration: ImageSurface | None,
    rect: pygame.Rect,
    accent: Color,
    *,
    radius: int,
) -> None:
    """Draw the card illustration when available, otherwise keep the stylized fallback."""
    if illustration is None:
        pygame.draw.rect(surface, _mix_color(accent, (20, 25, 38), 0.78), rect, border_radius=radius)
        return

    scaled = _scale_to_cover(illustration, rect.size)
    clipped = pygame.Surface(rect.size, pygame.SRCALPHA)
    clipped.blit(scaled, (0, 0))
    mask = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    clipped.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(clipped, rect.topleft)


def _scale_to_cover(image: ImageSurface, size: tuple[int, int]) -> ImageSurface:
    """Scale an image to fully cover the target size, cropping the overflow."""
    target_width, target_height = size
    if target_width <= 0 or target_height <= 0:
        return image

    image_width, image_height = image.get_size()
    if image_width == 0 or image_height == 0:
        return image

    scale = max(target_width / image_width, target_height / image_height)
    scaled_size = (max(1, int(image_width * scale)), max(1, int(image_height * scale)))
    scaled = pygame.transform.smoothscale(image, scaled_size)

    crop_x = max(0, (scaled_size[0] - target_width) // 2)
    crop_y = max(0, (scaled_size[1] - target_height) // 2)
    covered = pygame.Surface(size, pygame.SRCALPHA)
    covered.blit(scaled, (-crop_x, -crop_y))
    return covered


def _mix_color(base: Color, target: Color, ratio: float) -> Color:
    """Return a blended color."""
    return tuple(
        int(base[index] + (target[index] - base[index]) * ratio)
        for index in range(3)
    )


def _fit_text(text: str, font: pygame.font.Font, max_width: int) -> str:
    """Trim text to fit the requested width."""
    if max_width <= 0:
        return ""
    if font.size(text)[0] <= max_width:
        return text

    ellipsis = "..."
    if font.size(ellipsis)[0] > max_width:
        return ""

    trimmed = text
    while trimmed and font.size(f"{trimmed}{ellipsis}")[0] > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed.rstrip()}{ellipsis}"


def _clan_style(clan: str) -> tuple[str, Color]:
    """Return a compact clan badge code and placeholder color."""
    styles = {
        "Neon Syndicate": ("NS", (169, 92, 255)),
        "Iron Circuit": ("IC", (82, 208, 255)),
        "Wild Fury": ("WF", (255, 118, 54)),
    }
    if clan in styles:
        return styles[clan]

    initials = "".join(part[0] for part in clan.split()[:2]).upper() or "CL"
    return initials[:2], (150, 162, 188)


def _draw_glow(surface: pygame.Surface, rect: pygame.Rect, color: Color, *, alpha: int, radius: int) -> None:
    """Draw a soft neon glow around a rect."""
    if rect.width <= 0 or rect.height <= 0 or alpha <= 0:
        return

    glow = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(glow, (*color, alpha), glow.get_rect(), border_radius=radius)
    pygame.draw.rect(glow, (*color, max(0, alpha - 18)), glow.get_rect().inflate(-10, -10), width=2, border_radius=max(8, radius - 8))
    surface.blit(glow, rect.topleft)
