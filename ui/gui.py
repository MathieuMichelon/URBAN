"""Pygame prototype UI wired to the pure game engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from ai.base import BaseAIChoiceProvider
from core.draft import DraftPhase, build_draft_offer, compute_team_stars
from ai.bot import HeuristicAIChoiceProvider
from core.engine import GameEngine
from core.enums import GameStatus, RoundOutcome
from core.errors import InvalidMoveError
from core.models import Card, GameState, RoundResult, RoundSelection
from data.card_repository import load_cards
from ui.widgets import (
    Button,
    CardVisual,
    draw_card,
    draw_horizontal_scrollbar,
    draw_panel,
    draw_pill_track,
    draw_text,
    draw_wrapped_text,
)

Color = tuple[int, int, int]

SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
FPS = 60
TOTAL_ROUNDS = 4
TOTAL_PILLS = 12
SCROLL_STEP = 120
MATCH_OPPONENT_CARD_WIDTH = 196
MATCH_OPPONENT_CARD_HEIGHT = 208
MATCH_OPPONENT_CARD_GAP = 16
MATCH_PLAYER_CARD_WIDTH = 226
MATCH_PLAYER_CARD_HEIGHT = 252
MATCH_PLAYER_CARD_GAP = 18

BACKGROUND_TOP = (20, 25, 38)
BACKGROUND_BOTTOM = (8, 11, 19)
PANEL_FILL = (28, 34, 49)
PANEL_BORDER = (60, 68, 92)
TEXT_PRIMARY = (243, 246, 251)
TEXT_MUTED = (180, 190, 208)
ACCENT_BLUE = (71, 140, 246)
ACCENT_GREEN = (64, 180, 130)
ACCENT_GOLD = (241, 191, 73)
ACCENT_RED = (219, 96, 84)
ACCENT_PURPLE = (128, 108, 242)
ACCENT_TEAL = (72, 188, 196)


def _mix_panel_border(accent: Color) -> Color:
    """Blend one accent with the HUD neutral border tone."""
    return tuple(int((accent[index] * 0.72) + (PANEL_BORDER[index] * 0.28)) for index in range(3))


@dataclass(slots=True)
class InterfaceState:
    """Track transient Pygame interaction state."""

    selected_card_id: str | None = None
    selected_pills: int = 0
    last_result: RoundResult | None = None
    banner_title: str = "Clique une carte pour choisir tes pills."
    banner_body: str = "La carte selectionnee ouvre un panneau detaille. Les pills restent cachees jusqu'a la resolution."
    banner_color: Color = ACCENT_BLUE
    mode: str = "draft"
    initiative_player_id: int = 1
    pending_ai_selection: RoundSelection | None = None
    revealed_opponent_card_id: str | None = None
    draft_offer_scroll: int = 0
    opponent_hand_scroll: int = 0
    player_hand_scroll: int = 0


class GameWindow:
    """Run a local Pygame match against a simple AI."""

    def __init__(
        self,
        cards_path: str | Path,
        *,
        ai_provider: BaseAIChoiceProvider | None = None,
    ) -> None:
        """Create the Pygame window and initialize the first match."""
        pygame.init()
        pygame.display.set_caption("Urban Duel Prototype")

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.fonts = self._build_fonts()

        self.cards_path = Path(cards_path)
        self.card_catalog = load_cards(self.cards_path)
        self.engine = GameEngine()
        self.ai_provider = ai_provider or HeuristicAIChoiceProvider()
        self.asset_root = self.cards_path.parent.parent
        self._illustration_cache: dict[str, pygame.Surface | None] = {}

        self.state: GameState | None = None
        self.draft_phase: DraftPhase | None = None
        self.ui_state: InterfaceState
        self._running = True

        self._start_new_match()

    def run(self) -> None:
        """Start the main Pygame loop."""
        while self._running:
            for event in pygame.event.get():
                self._handle_event(event)

            self._draw()
            pygame.display.flip()
            self.clock.tick(FPS)

        pygame.quit()

    def _start_new_match(self) -> None:
        """Create a new shared draft phase and reset UI selections."""
        self.state = None
        self.draft_phase = DraftPhase(build_draft_offer(self.card_catalog, seed="solo-mode"))
        self.ui_state = InterfaceState()
        self._update_draft_banner()

    def _prepare_round(self) -> None:
        """Prepare transient UI state for the next round."""
        assert self.state is not None
        self.ui_state.mode = "selection"
        self.ui_state.initiative_player_id = self._initiative_player_id_for_round(self.state.current_round)
        self.ui_state.pending_ai_selection = None
        self.ui_state.revealed_opponent_card_id = None
        self.ui_state.opponent_hand_scroll = 0
        self.ui_state.player_hand_scroll = 0
        self._clear_card_selection()

        if self.ui_state.initiative_player_id == 2:
            ai_player = self.state.get_player(2)
            ai_selection = self.ai_provider.choose_action(self.state, ai_player)
            self.ui_state.pending_ai_selection = ai_selection
            self.ui_state.revealed_opponent_card_id = ai_selection.card_id
        self._update_selection_banner()

    def _handle_event(self, event: pygame.event.Event) -> None:
        """Dispatch Pygame input events."""
        if event.type == pygame.QUIT:
            self._running = False
            return

        if event.type == pygame.KEYDOWN:
            self._handle_keydown(event.key)
            return

        if event.type == pygame.MOUSEWHEEL:
            self._handle_mousewheel(event.x, event.y)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_left_click(event.pos)

    def _handle_keydown(self, key: int) -> None:
        """Handle keyboard shortcuts."""
        if self.ui_state.mode == "draft":
            if key in {pygame.K_RETURN, pygame.K_SPACE}:
                self._confirm_draft()
            elif key == pygame.K_LEFT and self.draft_phase is not None:
                layout = self._build_layout()
                self.ui_state.draft_offer_scroll = self._scroll_card_strip(
                    self.ui_state.draft_offer_scroll,
                    len(self.draft_phase.offer),
                    self._card_viewport(layout["opponent_hand_rect"]),
                    card_width=156,
                    card_height=236,
                    gap=12,
                    shrink_to_fit=False,
                    delta=-SCROLL_STEP,
                )
            elif key == pygame.K_RIGHT and self.draft_phase is not None:
                layout = self._build_layout()
                self.ui_state.draft_offer_scroll = self._scroll_card_strip(
                    self.ui_state.draft_offer_scroll,
                    len(self.draft_phase.offer),
                    self._card_viewport(layout["opponent_hand_rect"]),
                    card_width=156,
                    card_height=236,
                    gap=12,
                    shrink_to_fit=False,
                    delta=SCROLL_STEP,
                )
            return

        if self.ui_state.mode == "game_over":
            if key == pygame.K_r:
                self._start_new_match()
            elif key == pygame.K_ESCAPE:
                self._running = False
            return

        if self.ui_state.mode == "feedback":
            if key in {pygame.K_RETURN, pygame.K_SPACE}:
                self._advance_after_feedback()
            return

        if key == pygame.K_ESCAPE:
            self._clear_card_selection()
            self._update_selection_banner()
            return

        if key in {pygame.K_LEFT, pygame.K_MINUS, pygame.K_KP_MINUS}:
            self._change_selected_pills(-1)
        elif key in {pygame.K_RIGHT, pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS}:
            self._change_selected_pills(1)
        elif key == pygame.K_TAB:
            self._cycle_selected_card()
        elif key in {pygame.K_RETURN, pygame.K_SPACE}:
            self._confirm_player_round()

    def _handle_mousewheel(self, horizontal_delta: int, vertical_delta: int) -> None:
        """Route mouse wheel events to the hovered card strip."""
        layout = self._build_layout()
        mouse_pos = pygame.mouse.get_pos()
        total_delta = (-vertical_delta * SCROLL_STEP) + (-horizontal_delta * SCROLL_STEP)
        if total_delta == 0:
            return

        if self.ui_state.mode == "draft":
            offer_viewport = self._card_viewport(layout["opponent_hand_rect"])
            if offer_viewport.collidepoint(mouse_pos) and self.draft_phase is not None:
                self.ui_state.draft_offer_scroll = self._scroll_card_strip(
                    self.ui_state.draft_offer_scroll,
                    len(self.draft_phase.offer),
                    offer_viewport,
                    card_width=156,
                    card_height=236,
                    gap=12,
                    shrink_to_fit=False,
                    delta=total_delta,
                )
            return

        if self.state is None:
            return

        opponent_viewport = self._card_viewport(layout["opponent_hand_rect"])
        if opponent_viewport.collidepoint(mouse_pos):
            self.ui_state.opponent_hand_scroll = self._scroll_card_strip(
                self.ui_state.opponent_hand_scroll,
                len(self.state.get_player(2).hand),
                opponent_viewport,
                card_width=MATCH_OPPONENT_CARD_WIDTH,
                card_height=MATCH_OPPONENT_CARD_HEIGHT,
                gap=MATCH_OPPONENT_CARD_GAP,
                shrink_to_fit=True,
                delta=total_delta,
            )
            return

        player_viewport = self._card_viewport(layout["player_hand_rect"])
        if player_viewport.collidepoint(mouse_pos):
            self.ui_state.player_hand_scroll = self._scroll_card_strip(
                self.ui_state.player_hand_scroll,
                len(self.state.get_player(1).hand),
                player_viewport,
                card_width=MATCH_PLAYER_CARD_WIDTH,
                card_height=MATCH_PLAYER_CARD_HEIGHT,
                gap=MATCH_PLAYER_CARD_GAP,
                shrink_to_fit=True,
                delta=total_delta,
            )

    def _handle_left_click(self, position: tuple[int, int]) -> None:
        """Handle mouse interactions."""
        layout = self._build_layout()

        if self.ui_state.mode == "draft":
            assert self.draft_phase is not None
            offer_rects, _, _, _ = self._layout_card_strip(
                self.draft_phase.offer,
                self._card_viewport(layout["opponent_hand_rect"]),
                card_width=156,
                card_height=236,
                gap=12,
                scroll_offset=self.ui_state.draft_offer_scroll,
                shrink_to_fit=False,
            )
            for card, rect in offer_rects:
                if rect.collidepoint(position):
                    try:
                        self.draft_phase.toggle_card(1, card.id)
                    except InvalidMoveError as error:
                        self._set_banner("Draft invalide", str(error), ACCENT_RED)
                    else:
                        self._update_draft_banner()
                    return

            confirm_button = layout["confirm_button"]
            assert isinstance(confirm_button, Button)
            if confirm_button.contains(position):
                self._confirm_draft()
            return

        assert self.state is not None

        if self.ui_state.mode == "game_over":
            if layout["restart_button"].contains(position):
                self._start_new_match()
            elif layout["quit_button"].contains(position):
                self._running = False
            return

        if self.ui_state.mode == "feedback":
            if layout["continue_button"].contains(position):
                self._advance_after_feedback()
            return

        player_rects, _, _, _ = self._layout_card_strip(
            self.state.get_player(1).hand,
            self._card_viewport(layout["player_hand_rect"]),
            card_width=MATCH_PLAYER_CARD_WIDTH,
            card_height=MATCH_PLAYER_CARD_HEIGHT,
            gap=MATCH_PLAYER_CARD_GAP,
            scroll_offset=self.ui_state.player_hand_scroll,
        )
        for card, rect in player_rects:
            if rect.collidepoint(position) and card.id not in self.state.get_player(1).played_card_ids:
                self._toggle_selected_card(card.id)
                self._update_selection_banner()
                return

        if layout["minus_button"].contains(position):
            self._change_selected_pills(-1)
        elif layout["plus_button"].contains(position):
            self._change_selected_pills(1)
        elif layout["confirm_button"].contains(position):
            self._confirm_player_round()

    def _change_selected_pills(self, delta: int) -> None:
        """Adjust the currently committed pills."""
        if self.ui_state.mode != "selection" or self.ui_state.selected_card_id is None:
            return

        assert self.state is not None
        player = self.state.get_player(1)
        next_value = self.ui_state.selected_pills + delta
        self.ui_state.selected_pills = max(0, min(player.pills, next_value))
        self._update_selection_banner()

    def _cycle_selected_card(self) -> None:
        """Move selection to the next available card."""
        assert self.state is not None
        available_cards = self.state.get_player(1).available_cards()
        if not available_cards:
            self._clear_card_selection()
            return

        current_id = self.ui_state.selected_card_id
        card_ids = [card.id for card in available_cards]
        if current_id not in card_ids:
            self.ui_state.selected_card_id = card_ids[0]
            self.ui_state.selected_pills = 0
            self._update_selection_banner()
            return

        current_index = card_ids.index(current_id)
        self.ui_state.selected_card_id = card_ids[(current_index + 1) % len(card_ids)]
        self._update_selection_banner()

    def _confirm_player_round(self) -> None:
        """Resolve the current round against the AI."""
        if self.ui_state.mode != "selection":
            return

        assert self.state is not None

        selected_card_id = self.ui_state.selected_card_id
        if selected_card_id is None:
            self._set_banner(
                "No card selected",
                "Choose an available card before confirming the round.",
                ACCENT_RED,
            )
            return

        player_2 = self.state.get_player(2)
        player_selection = RoundSelection(
            card_id=selected_card_id,
            pills_committed=self.ui_state.selected_pills,
        )

        try:
            ai_selection = self.ui_state.pending_ai_selection or self.ai_provider.choose_action(self.state, player_2)
            result = self.engine.play_round(
                state=self.state,
                player_1_selection=player_selection,
                player_2_selection=ai_selection,
            )
        except InvalidMoveError as error:
            self._set_banner("Invalid move", str(error), ACCENT_RED)
            return

        self.ui_state.pending_ai_selection = None
        self.ui_state.revealed_opponent_card_id = ai_selection.card_id
        self.ui_state.last_result = result
        self.ui_state.mode = "game_over" if self.state.is_over else "feedback"
        self._set_banner_from_result(result, ai_selection.card_id)

    def _confirm_draft(self) -> None:
        """Lock the drafted team, let the AI draft, and start the live match."""
        if self.ui_state.mode != "draft" or self.draft_phase is None:
            return

        try:
            self.draft_phase.lock_team(1)
        except InvalidMoveError as error:
            self._set_banner("Equipe invalide", str(error), ACCENT_RED)
            return

        ai_team = self.ai_provider.choose_team(self.draft_phase.offer)
        player_team = self.draft_phase.selected_cards(1)
        self.state = self.engine.create_game(player_1_hand=player_team, player_2_hand=ai_team)
        self.draft_phase = None
        self.ui_state.last_result = None
        self._prepare_round()

    def _advance_after_feedback(self) -> None:
        """Return to selection mode after showing round feedback."""
        if self.state.is_over:
            self.ui_state.mode = "game_over"
            return

        self._prepare_round()

    def _set_banner_from_result(self, result: RoundResult, opponent_card_id: str) -> None:
        """Update the top information panel after a round resolves."""
        assert self.state is not None
        player_card = self.state.get_player(1).get_card(result.player_1_card_id).name
        opponent_name = self.state.get_player(2).get_card(opponent_card_id).name

        if result.outcome is RoundOutcome.TIE:
            self._set_banner(
                "Round a egalite",
                f"{player_card} et {opponent_name} ont atteint la meme attaque. Les pills sont restees cachees jusqu'au reveal.",
                ACCENT_GOLD,
            )
            return

        winner_label = "Tu" if result.winner_id == 1 else "IA"
        loser_hp = self.state.get_player(result.loser_id).hit_points if result.loser_id else 0
        self._set_banner(
            f"{winner_label} gagne le round {result.round_number}",
            f"{player_card} vs {opponent_name} | degats: {result.damage_dealt} | PV restants: {loser_hp}",
            ACCENT_GREEN if result.winner_id == 1 else ACCENT_RED,
        )

    def _update_selection_banner(self) -> None:
        """Describe the current player choice state."""
        assert self.state is not None
        player = self.state.get_player(1)
        available_cards = player.available_cards()
        if not available_cards:
            self._set_banner(
                "No playable card left",
                "Every card in your hand has been played.",
                ACCENT_RED,
            )
            return

        if self.ui_state.selected_card_id is None:
            if self.ui_state.initiative_player_id == 2 and self.ui_state.revealed_opponent_card_id is not None:
                opponent_card = self.state.get_player(2).get_card(self.ui_state.revealed_opponent_card_id)
                self._set_banner(
                    f"L'IA revele {opponent_card.name}",
                    "Choisis l'une de tes cartes restantes pour ouvrir son detail, puis engage tes pills.",
                    ACCENT_RED,
                )
                return

            self._set_banner(
                "Clique une carte pour choisir tes pills.",
                "Tu as l'initiative ce round. Selectionne une de tes quatre cartes pour ouvrir le focus panel.",
                ACCENT_BLUE,
            )
            return

        card = player.get_card(self.ui_state.selected_card_id)
        projected_attack = card.power * self.ui_state.selected_pills
        remaining = max(0, player.pills - self.ui_state.selected_pills)
        bonus_state = "active" if card.clan in player.active_clan_bonuses else "inactive"

        if self.ui_state.initiative_player_id == 2 and self.ui_state.revealed_opponent_card_id is not None:
            opponent_card = self.state.get_player(2).get_card(self.ui_state.revealed_opponent_card_id)
            self._set_banner(
                f"{card.name} selectionnee contre {opponent_card.name}",
                f"Attaque prevue {projected_attack} | Pills restantes {remaining} | Bonus {bonus_state}. Les pills IA restent cachees jusqu'au reveal.",
                ACCENT_RED,
            )
            return

        self._set_banner(
            f"{card.name} selectionnee",
            f"Attaque prevue {projected_attack} | Degats {card.damage} | Pills restantes {remaining} | Bonus {bonus_state}.",
            ACCENT_BLUE,
        )

    def _update_draft_banner(self) -> None:
        """Describe the current draft selection state."""
        if self.draft_phase is None:
            return

        validation = self.draft_phase.validation_for(1)
        selected_cards = self.draft_phase.selected_cards(1)
        if not selected_cards:
            self._set_banner(
                "Draft ton equipe",
                "Choisis 4 cartes dans l'offre commune. Limite: 8 etoiles.",
                ACCENT_BLUE,
            )
            return

        clan_text = ", ".join(validation.active_clans) if validation.active_clans else "aucun"
        self._set_banner(
            f"Equipe {len(selected_cards)}/4 - {validation.total_stars}/8 etoiles",
            f"Bonus actifs: {clan_text}. {'Equipe valide' if validation.is_valid else 'Encore invalide'}",
            ACCENT_GREEN if validation.is_valid else ACCENT_GOLD,
        )

    def _set_banner(self, title: str, body: str, color: Color) -> None:
        """Store the info panel content."""
        self.ui_state.banner_title = title
        self.ui_state.banner_body = body
        self.ui_state.banner_color = color

    def _clear_card_selection(self) -> None:
        """Return to the neutral match-selection state."""
        self.ui_state.selected_card_id = None
        self.ui_state.selected_pills = 0

    def _toggle_selected_card(self, card_id: str) -> None:
        """Toggle the focused card in the hand layout."""
        if self.ui_state.selected_card_id == card_id:
            self._clear_card_selection()
            return

        self.ui_state.selected_card_id = card_id
        if self.state is None:
            return

        player_pills = self.state.get_player(1).pills
        self.ui_state.selected_pills = max(0, min(player_pills, self.ui_state.selected_pills))

    def _selected_card(self) -> Card | None:
        """Return the selected local card when one is focused."""
        assert self.state is not None
        if self.ui_state.selected_card_id is None:
            return None
        return self.state.get_player(1).get_card(self.ui_state.selected_card_id)

    def _draw(self) -> None:
        """Render the whole screen."""
        self._draw_background()
        layout = self._build_layout()
        mouse_pos = pygame.mouse.get_pos()

        if self.ui_state.mode == "draft":
            self._draw_draft_mode(layout, mouse_pos)
            pygame.display.flip()
            return

        self._draw_match_chrome(layout)
        self._draw_opponent_section(layout, mouse_pos)
        self._draw_center_panels(layout, mouse_pos)
        self._draw_player_section(layout, mouse_pos)

        if self.ui_state.mode == "game_over":
            self._draw_game_over_overlay(layout, mouse_pos)

    def _draw_background(self) -> None:
        """Paint the scene background."""
        for y in range(SCREEN_HEIGHT):
            ratio = y / SCREEN_HEIGHT
            color = tuple(
                int(BACKGROUND_TOP[index] + (BACKGROUND_BOTTOM[index] - BACKGROUND_TOP[index]) * ratio)
                for index in range(3)
            )
            pygame.draw.line(self.screen, color, (0, y), (SCREEN_WIDTH, y))

        skyline_base = SCREEN_HEIGHT - 170
        building_colors = [(10, 18, 32), (12, 22, 38), (14, 26, 44)]
        building_specs = [
            (0, 118, 230), (102, 84, 180), (176, 132, 260), (286, 96, 210),
            (382, 150, 320), (514, 112, 240), (624, 138, 340), (770, 98, 220),
            (876, 144, 280), (1010, 108, 250), (1134, 152, 300), (1288, 94, 170),
        ]
        for index, (left, width, height) in enumerate(building_specs):
            rect = pygame.Rect(left, skyline_base - height, width, height)
            color = building_colors[index % len(building_colors)]
            pygame.draw.rect(self.screen, color, rect)
            for window_y in range(rect.top + 12, rect.bottom - 10, 18):
                for window_x in range(rect.left + 10, rect.right - 8, 18):
                    if (window_x + window_y + index) % 3 == 0:
                        continue
                    glow = (44, 168, 255) if index % 2 == 0 else (168, 84, 255)
                    pygame.draw.rect(self.screen, glow, pygame.Rect(window_x, window_y, 6, 10), border_radius=2)

        for offset in range(0, SCREEN_WIDTH, 48):
            pygame.draw.line(self.screen, (16, 34, 54), (offset, skyline_base + 8), (SCREEN_WIDTH // 2, SCREEN_HEIGHT), 1)
        for step in range(0, 8):
            y = skyline_base + 14 + step * 26
            pygame.draw.line(self.screen, (14, 28, 44), (0, y), (SCREEN_WIDTH, y), 1)

        pygame.draw.circle(self.screen, (34, 46, 82), (180, 110), 168)
        pygame.draw.circle(self.screen, (18, 74, 108), (SCREEN_WIDTH - 140, SCREEN_HEIGHT - 110), 240)
        vignette = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(vignette, (2, 4, 8, 72), vignette.get_rect(), width=42, border_radius=24)
        self.screen.blit(vignette, (0, 0))

    def _build_layout(self) -> dict[str, pygame.Rect | Button]:
        """Create the screen layout rectangles."""
        margin = 24
        section_gap = 20
        content_width = SCREEN_WIDTH - (margin * 2)

        if self.ui_state.mode == "draft":
            opponent_panel = pygame.Rect(margin, margin, content_width, 236)
            center_top = opponent_panel.bottom + section_gap
            center_height = 248
            center_info = pygame.Rect(margin, center_top, 720, center_height)
            control_panel = pygame.Rect(center_info.right + 24, center_top, SCREEN_WIDTH - center_info.right - margin - 24, center_height)
            player_panel = pygame.Rect(margin, center_info.bottom + section_gap, content_width, SCREEN_HEIGHT - (center_info.bottom + section_gap + margin))

            detail_width = 214
            info_left = control_panel.left + 20 + detail_width + 16
            info_width = control_panel.right - info_left - 20
            controls_row_y = control_panel.bottom - 62
            minus_rect = pygame.Rect(info_left, controls_row_y, 56, 46)
            value_rect = pygame.Rect(minus_rect.right + 12, controls_row_y - 2, 92, 50)
            plus_rect = pygame.Rect(value_rect.right + 12, controls_row_y, 56, 46)
            confirm_rect = pygame.Rect(info_left + info_width - 148, controls_row_y + 2, 148, 46)
            continue_rect = pygame.Rect(center_info.right - 166, center_info.bottom - 58, 136, 40)
            restart_rect = pygame.Rect(SCREEN_WIDTH // 2 - 160, SCREEN_HEIGHT // 2 + 90, 140, 46)
            quit_rect = pygame.Rect(SCREEN_WIDTH // 2 + 20, SCREEN_HEIGHT // 2 + 90, 140, 46)

            confirm_label = "Lock Team" if self.ui_state.mode == "draft" else "Confirm"
            selection_active = self.ui_state.mode == "selection" and self.ui_state.selected_card_id is not None

            return {
                "opponent_panel": opponent_panel,
                "opponent_info_rect": pygame.Rect(opponent_panel.left + 20, opponent_panel.top + 18, 250, 196),
                "opponent_hand_rect": pygame.Rect(opponent_panel.left + 288, opponent_panel.top + 26, opponent_panel.width - 308, 180),
                "center_info": center_info,
                "control_panel": control_panel,
                "control_value_rect": value_rect,
                "player_panel": player_panel,
                "player_header_rect": pygame.Rect(player_panel.left + 20, player_panel.top + 16, player_panel.width - 40, 84),
                "player_hand_rect": pygame.Rect(player_panel.left + 18, player_panel.top + 110, player_panel.width - 36, player_panel.height - 132),
                "minus_button": Button(minus_rect, "-", ACCENT_PURPLE, enabled=selection_active),
                "plus_button": Button(plus_rect, "+", ACCENT_PURPLE, enabled=selection_active),
                "confirm_button": Button(confirm_rect, confirm_label, ACCENT_GREEN, enabled=self.ui_state.mode == "draft" or selection_active),
                "continue_button": Button(continue_rect, "Continue", ACCENT_TEAL, enabled=self.ui_state.mode == "feedback"),
                "restart_button": Button(restart_rect, "Play Again", ACCENT_GREEN, enabled=True),
                "quit_button": Button(quit_rect, "Quit", ACCENT_RED, enabled=True),
            }

        top_offset = 58
        row_gap = 14
        identity_sidebar_width = 176
        round_info_width = 216
        sidepod_width = 156
        top_height = 228
        middle_height = 244
        top_strip_width = content_width - identity_sidebar_width - sidepod_width - 32

        opponent_sidebar = pygame.Rect(margin, top_offset, identity_sidebar_width, top_height)
        opponent_cards = pygame.Rect(opponent_sidebar.right + 16, top_offset, top_strip_width, top_height)
        opponent_focus = pygame.Rect(opponent_cards.right + 16, top_offset, sidepod_width, top_height)

        middle_top = opponent_sidebar.bottom + row_gap
        round_info = pygame.Rect(margin, middle_top, round_info_width, middle_height)
        center_stage = pygame.Rect(round_info.right + 16, middle_top, 592, middle_height)
        pills_panel = pygame.Rect(center_stage.right + 16, middle_top, SCREEN_WIDTH - margin - (center_stage.right + 16), middle_height)

        bottom_top = middle_top + middle_height + row_gap
        bottom_height = SCREEN_HEIGHT - bottom_top - margin
        player_sidebar = pygame.Rect(margin, bottom_top, identity_sidebar_width, bottom_height)
        player_cards = pygame.Rect(player_sidebar.right + 16, bottom_top, top_strip_width, bottom_height)
        player_focus = pygame.Rect(player_cards.right + 16, bottom_top, sidepod_width, bottom_height)

        controls_row_y = pills_panel.top + 138
        minus_rect = pygame.Rect(pills_panel.left + 26, controls_row_y, 54, 42)
        value_rect = pygame.Rect(minus_rect.right + 10, controls_row_y - 2, 98, 46)
        plus_rect = pygame.Rect(value_rect.right + 10, controls_row_y, 54, 42)
        confirm_rect = pygame.Rect(pills_panel.left + 26, pills_panel.bottom - 56, pills_panel.width - 52, 42)
        continue_rect = pygame.Rect(pills_panel.left + 26, pills_panel.bottom - 56, pills_panel.width - 52, 42)
        restart_rect = pygame.Rect(SCREEN_WIDTH // 2 - 160, SCREEN_HEIGHT // 2 + 90, 140, 46)
        quit_rect = pygame.Rect(SCREEN_WIDTH // 2 + 20, SCREEN_HEIGHT // 2 + 90, 140, 46)

        confirm_label = "CONFIRMER"
        selection_active = self.ui_state.mode == "selection" and self.ui_state.selected_card_id is not None

        return {
            "hud_header": pygame.Rect(margin, 18, content_width, 42),
            "round_badge": pygame.Rect(SCREEN_WIDTH // 2 - 92, 10, 184, 34),
            "opponent_panel": opponent_cards,
            "opponent_info_rect": opponent_sidebar,
            "opponent_hand_rect": pygame.Rect(opponent_cards.left + 8, opponent_cards.top + 10, opponent_cards.width - 16, opponent_cards.height - 20),
            "opponent_focus_rect": opponent_focus,
            "center_info": round_info,
            "control_panel": center_stage,
            "pills_panel": pills_panel,
            "control_value_rect": value_rect,
            "player_panel": player_cards,
            "player_header_rect": player_sidebar,
            "player_hand_rect": pygame.Rect(player_cards.left + 8, player_cards.top + 10, player_cards.width - 16, player_cards.height - 20),
            "player_focus_rect": player_focus,
            "minus_button": Button(minus_rect, "-", ACCENT_PURPLE, enabled=selection_active),
            "plus_button": Button(plus_rect, "+", ACCENT_PURPLE, enabled=selection_active),
            "confirm_button": Button(confirm_rect, confirm_label, ACCENT_GREEN, enabled=selection_active),
            "continue_button": Button(continue_rect, "Suite", ACCENT_TEAL, enabled=self.ui_state.mode == "feedback"),
            "restart_button": Button(restart_rect, "Play Again", ACCENT_GREEN, enabled=True),
            "quit_button": Button(quit_rect, "Quit", ACCENT_RED, enabled=True),
        }

    def _draw_draft_mode(self, layout: dict[str, pygame.Rect | Button], mouse_pos: tuple[int, int]) -> None:
        """Render the solo draft phase using the shared offer."""
        assert self.draft_phase is not None
        panel_rect = layout["opponent_panel"]
        info_rect = layout["opponent_info_rect"]
        hand_rect = layout["opponent_hand_rect"]
        player_panel = layout["player_panel"]
        header_rect = layout["player_header_rect"]
        player_hand_rect = layout["player_hand_rect"]
        control_rect = layout["control_panel"]
        info_panel = layout["center_info"]
        assert isinstance(panel_rect, pygame.Rect)
        assert isinstance(info_rect, pygame.Rect)
        assert isinstance(hand_rect, pygame.Rect)
        assert isinstance(player_panel, pygame.Rect)
        assert isinstance(header_rect, pygame.Rect)
        assert isinstance(player_hand_rect, pygame.Rect)
        assert isinstance(control_rect, pygame.Rect)
        assert isinstance(info_panel, pygame.Rect)

        draw_panel(self.screen, panel_rect, fill=PANEL_FILL, border=PANEL_BORDER)
        draw_panel(self.screen, player_panel, fill=PANEL_FILL, border=PANEL_BORDER)
        draw_panel(self.screen, info_panel, fill=PANEL_FILL, border=PANEL_BORDER)
        draw_panel(self.screen, control_rect, fill=PANEL_FILL, border=PANEL_BORDER)

        draw_text(self.screen, self.fonts["section"], "Shared Draft Offer", TEXT_PRIMARY, (info_rect.left, info_rect.top))
        draw_text(self.screen, self.fonts["small"], "Choose 4 cards under 8 stars. AI drafts from the same pool.", TEXT_MUTED, (info_rect.left, info_rect.top + 34))

        validation = self.draft_phase.validation_for(1)
        selected_ids = set(self.draft_phase.seats[1].selected_card_ids)
        active_clans = set(validation.active_clans)
        preview_by_id = {
            preview.card_id: preview
            for preview in validation.selected_card_previews
        }
        offer_viewport = self._card_viewport(hand_rect)
        offer_rects, offer_content_width, _, clamped_offer_scroll = self._layout_card_strip(
            self.draft_phase.offer,
            offer_viewport,
            card_width=156,
            card_height=236,
            gap=12,
            scroll_offset=self.ui_state.draft_offer_scroll,
            shrink_to_fit=False,
        )
        self.ui_state.draft_offer_scroll = clamped_offer_scroll
        self._draw_card_strip_background(offer_viewport)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(offer_viewport)
        for card, rect in offer_rects:
            card_visual = self._build_card_visual(
                card,
                rect=rect,
                selected=card.id in selected_ids,
                footer="Selected" if card.id in selected_ids else "Offered",
                bonus_active=card.clan in active_clans and card.id in selected_ids,
            )
            draw_card(self.screen, self.fonts, card_visual, mouse_pos=mouse_pos)
        self.screen.set_clip(previous_clip)
        self._draw_card_strip_scrollbar(offer_viewport, offer_content_width, self.ui_state.draft_offer_scroll, ACCENT_TEAL)
        if offer_content_width > offer_viewport.width:
            draw_text(
                self.screen,
                self.fonts["tiny"],
                "Mouse wheel or left/right to scroll",
                TEXT_MUTED,
                (hand_rect.right - 8, hand_rect.bottom - 2),
                anchor="bottomright",
            )

        draw_text(self.screen, self.fonts["section"], "My Drafted Team", TEXT_PRIMARY, (header_rect.left, header_rect.top))
        draw_text(
            self.screen,
            self.fonts["small"],
            f"Cards {len(validation.selected_card_ids)}/4 | Stars {validation.total_stars}/8",
            ACCENT_GREEN if validation.is_valid else TEXT_MUTED,
            (header_rect.left, header_rect.top + 36),
        )
        clan_text = ", ".join(validation.active_clans) if validation.active_clans else "No active clan bonus yet"
        draw_text(self.screen, self.fonts["small"], clan_text, TEXT_MUTED, (header_rect.left, header_rect.top + 60))

        drafted_viewport = self._card_viewport(player_hand_rect)
        drafted_rects, _, _, _ = self._layout_card_strip(
            self.draft_phase.selected_cards(1),
            drafted_viewport,
            card_width=208,
            card_height=248,
            gap=18,
        )
        self._draw_card_strip_background(drafted_viewport)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(drafted_viewport)
        for card, rect in drafted_rects:
            preview = preview_by_id.get(card.id)
            draw_card(
                self.screen,
                self.fonts,
                self._build_card_visual(
                    card,
                    rect=rect,
                    selected=True,
                    footer="Picked" if preview and preview.bonus_active else "Picked - bonus off",
                    bonus_active=preview.bonus_active if preview is not None else False,
                ),
                mouse_pos=mouse_pos,
            )
        self.screen.set_clip(previous_clip)

        draw_text(self.screen, self.fonts["section"], "Draft Info", TEXT_PRIMARY, (info_panel.left + 22, info_panel.top + 18))
        draw_text(self.screen, self.fonts["small"], self.ui_state.banner_title, self.ui_state.banner_color, (info_panel.left + 22, info_panel.top + 60))
        draw_wrapped_text(
            self.screen,
            self.fonts["body"],
            self.ui_state.banner_body,
            TEXT_MUTED,
            pygame.Rect(info_panel.left + 22, info_panel.top + 88, info_panel.width - 44, 92),
            max_lines=4,
        )

        draw_text(self.screen, self.fonts["section"], "Lock Team", TEXT_PRIMARY, (control_rect.left + 22, control_rect.top + 18))
        draw_text(self.screen, self.fonts["body"], f"Current stars: {validation.total_stars}/8", TEXT_PRIMARY, (control_rect.left + 22, control_rect.top + 66))
        draw_text(self.screen, self.fonts["body"], f"Current size: {len(validation.selected_card_ids)}/4", TEXT_PRIMARY, (control_rect.left + 22, control_rect.top + 96))
        draw_text(
            self.screen,
            self.fonts["small"],
            "Active clan bonuses preview is shown directly on your selected cards.",
            TEXT_MUTED,
            (control_rect.left + 22, control_rect.top + 130),
        )

        confirm_button = layout["confirm_button"]
        assert isinstance(confirm_button, Button)
        confirm_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])

    def _draw_match_chrome(self, layout: dict[str, pygame.Rect | Button]) -> None:
        """Render the top HUD header and centered round badge."""
        assert self.state is not None
        header_rect = layout["hud_header"]
        round_badge = layout["round_badge"]
        assert isinstance(header_rect, pygame.Rect)
        assert isinstance(round_badge, pygame.Rect)

        pygame.draw.line(self.screen, (36, 86, 128), (header_rect.left, header_rect.bottom), (header_rect.right, header_rect.bottom), 1)
        draw_text(self.screen, self.fonts["section"], "URBAN DUEL", TEXT_PRIMARY, (header_rect.left + 18, header_rect.top + 2))
        draw_text(
            self.screen,
            self.fonts["tiny"],
            "Prototype local solo",
            TEXT_MUTED,
            (header_rect.left + 20, header_rect.top + 30),
        )

        draw_panel(self.screen, round_badge, fill=(14, 18, 28), border=(55, 82, 126), radius=12, shadow_offset=(0, 4))
        draw_text(
            self.screen,
            self.fonts["small"],
            f"ROUND {self.state.current_round} / {TOTAL_ROUNDS}",
            TEXT_PRIMARY,
            round_badge.center,
            anchor="center",
        )

    def _draw_identity_sidebar(self, rect: pygame.Rect, player, *, title: str, accent: Color) -> None:
        """Draw a left HUD sidebar with identity, stats, and clan bonus."""
        draw_panel(self.screen, rect, fill=(14, 18, 28), border=_mix_panel_border(accent))
        draw_text(self.screen, self.fonts["small"], title, accent, (rect.left + 14, rect.top + 14))

        avatar_center = (rect.left + 40, rect.top + 72)
        pygame.draw.circle(self.screen, (12, 16, 26), avatar_center, 34)
        pygame.draw.circle(self.screen, accent, avatar_center, 36, 2)
        pygame.draw.circle(self.screen, (235, 240, 248), (avatar_center[0], avatar_center[1] - 10), 10)
        pygame.draw.arc(self.screen, (235, 240, 248), pygame.Rect(avatar_center[0] - 18, avatar_center[1] - 2, 36, 30), 3.14, 6.28, 3)

        hp_box = pygame.Rect(rect.left + 80, rect.top + 44, rect.width - 92, 40)
        pills_box = pygame.Rect(rect.left + 80, rect.top + 88, rect.width - 92, 40)
        for box, label, value in ((hp_box, "PV", player.hit_points), (pills_box, "PILLS", player.pills)):
            pygame.draw.rect(self.screen, (18, 24, 36), box, border_radius=12)
            pygame.draw.rect(self.screen, _mix_panel_border(accent), box, width=2, border_radius=12)
            draw_text(self.screen, self.fonts["tiny"], label, TEXT_MUTED, (box.left + 10, box.top + 7))
            draw_text(self.screen, self.fonts["body"], str(value), TEXT_PRIMARY, (box.left + 10, box.bottom - 7), anchor="bottomleft")

        bonus_rect = pygame.Rect(rect.left + 12, rect.top + 136, rect.width - 24, rect.height - 148)
        pygame.draw.rect(self.screen, (16, 20, 30), bonus_rect, border_radius=14)
        pygame.draw.rect(self.screen, accent, bonus_rect, width=1, border_radius=14)
        draw_text(self.screen, self.fonts["tiny"], "BONUS DE CLAN", accent, (bonus_rect.left + 10, bonus_rect.top + 10))

        active_bonuses = sorted(player.active_clan_bonuses)
        active_bonus = ", ".join(active_bonuses) if active_bonuses else "Aucun bonus"
        draw_wrapped_text(
            self.screen,
            self.fonts["small"],
            active_bonus,
            TEXT_PRIMARY,
            pygame.Rect(bonus_rect.left + 10, bonus_rect.top + 32, bonus_rect.width - 20, bonus_rect.height - 56),
            max_lines=3,
        )
        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            "Actif" if player.active_clan_bonuses else "Inactif",
            ACCENT_GREEN if player.active_clan_bonuses else TEXT_MUTED,
            pygame.Rect(bonus_rect.left + 10, bonus_rect.bottom - 22, bonus_rect.width - 20, 16),
            max_lines=1,
        )

    def _draw_waiting_pod(self, rect: pygame.Rect, *, title: str, body: str, accent: Color) -> None:
        """Draw a right-side placeholder pod."""
        draw_panel(self.screen, rect, fill=(14, 18, 28), border=(42, 50, 72), radius=18)
        inset = rect.inflate(-26, -26)
        pygame.draw.rect(self.screen, (12, 16, 24), inset, border_radius=18)
        pygame.draw.rect(self.screen, (40, 48, 68), inset, width=1, border_radius=18)
        pygame.draw.line(self.screen, (28, 34, 50), inset.midtop, inset.midbottom, 1)
        pygame.draw.line(self.screen, (28, 34, 50), inset.midleft, inset.midright, 1)
        draw_text(self.screen, self.fonts["body"], title, accent, (rect.centerx, rect.centery - 12), anchor="center")
        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            body,
            TEXT_MUTED,
            pygame.Rect(rect.left + 16, rect.centery + 6, rect.width - 32, 42),
            max_lines=3,
        )

    def _draw_opponent_section(self, layout: dict[str, pygame.Rect | Button], mouse_pos: tuple[int, int]) -> None:
        """Draw the opponent zone with visible cards and stats."""
        assert self.state is not None
        panel_rect = layout["opponent_panel"]
        info_rect = layout["opponent_info_rect"]
        hand_rect = layout["opponent_hand_rect"]
        focus_rect = layout["opponent_focus_rect"]
        assert isinstance(panel_rect, pygame.Rect)
        assert isinstance(info_rect, pygame.Rect)
        assert isinstance(hand_rect, pygame.Rect)
        assert isinstance(focus_rect, pygame.Rect)

        opponent = self.state.get_player(2)
        opponent_accent = ACCENT_RED
        self._draw_identity_sidebar(info_rect, opponent, title="ADVERSAIRE", accent=opponent_accent)
        draw_panel(self.screen, panel_rect, fill=(14, 18, 28), border=(49, 56, 80))

        opponent_viewport = self._card_viewport(hand_rect)
        opponent_rects, opponent_content_width, _, clamped_opponent_scroll = self._layout_card_strip(
            opponent.hand,
            opponent_viewport,
            card_width=MATCH_OPPONENT_CARD_WIDTH,
            card_height=MATCH_OPPONENT_CARD_HEIGHT,
            gap=MATCH_OPPONENT_CARD_GAP,
            scroll_offset=self.ui_state.opponent_hand_scroll,
        )
        self.ui_state.opponent_hand_scroll = clamped_opponent_scroll
        self._draw_card_strip_background(opponent_viewport)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(opponent_viewport)
        for card, rect in opponent_rects:
            disabled = card.id in opponent.played_card_ids
            is_locked = (
                self.ui_state.mode == "selection"
                and self.ui_state.initiative_player_id == 2
                and card.id == self.ui_state.revealed_opponent_card_id
            )
            card_visual = CardVisual(
                rect=rect,
                title=card.name,
                clan=card.clan,
                stars=card.stars,
                power=card.power,
                damage=card.damage,
                power_text=card.power_text,
                bonus_text=card.bonus_text,
                accent=self._card_accent(card, opponent_accent),
                illustration_label="Visible Card",
                illustration=self._load_card_illustration(card),
                bonus_active=card.clan in opponent.active_clan_bonuses,
                selected=is_locked or card.id == self.ui_state.revealed_opponent_card_id and self.ui_state.mode != "selection",
                disabled=disabled,
                hidden=False,
                show_footer="Locked" if is_locked else "Played" if disabled else "Open",
            )
            draw_card(self.screen, self.fonts, card_visual, mouse_pos=mouse_pos)
        self.screen.set_clip(previous_clip)
        self._draw_card_strip_scrollbar(opponent_viewport, opponent_content_width, self.ui_state.opponent_hand_scroll, opponent_accent)

        if self.ui_state.revealed_opponent_card_id is not None:
            revealed_name = opponent.get_card(self.ui_state.revealed_opponent_card_id).name
            self._draw_waiting_pod(
                focus_rect,
                title="CARTE VISIBLE",
                body=f"{revealed_name} est annoncée. Les pills restent secretes jusqu'a la resolution.",
                accent=opponent_accent,
            )
        else:
            self._draw_waiting_pod(
                focus_rect,
                title="EN ATTENTE",
                body="Choisit sa carte. Sa mise de pills reste cachee.",
                accent=opponent_accent,
            )

    def _draw_player_section(self, layout: dict[str, pygame.Rect | Button], mouse_pos: tuple[int, int]) -> None:
        """Draw the local player zone."""
        assert self.state is not None
        panel_rect = layout["player_panel"]
        header_rect = layout["player_header_rect"]
        hand_rect = layout["player_hand_rect"]
        focus_rect = layout["player_focus_rect"]
        assert isinstance(panel_rect, pygame.Rect)
        assert isinstance(header_rect, pygame.Rect)
        assert isinstance(hand_rect, pygame.Rect)
        assert isinstance(focus_rect, pygame.Rect)

        player = self.state.get_player(1)
        player_accent = ACCENT_PURPLE
        self._draw_identity_sidebar(header_rect, player, title="JOUEUR", accent=player_accent)
        draw_panel(self.screen, panel_rect, fill=(14, 18, 28), border=(49, 56, 80))

        player_viewport = self._card_viewport(hand_rect)
        player_rects, player_content_width, _, clamped_player_scroll = self._layout_card_strip(
            player.hand,
            player_viewport,
            card_width=MATCH_PLAYER_CARD_WIDTH,
            card_height=MATCH_PLAYER_CARD_HEIGHT,
            gap=MATCH_PLAYER_CARD_GAP,
            scroll_offset=self.ui_state.player_hand_scroll,
        )
        self.ui_state.player_hand_scroll = clamped_player_scroll
        self._draw_card_strip_background(player_viewport)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(player_viewport)
        for card, rect in player_rects:
            is_selected = (
                self.ui_state.mode == "selection"
                and card.id == self.ui_state.selected_card_id
                and card.id not in player.played_card_ids
            )
            disabled = card.id in player.played_card_ids
            card_visual = CardVisual(
                rect=rect,
                title=card.name,
                clan=card.clan,
                stars=card.stars,
                power=card.power,
                damage=card.damage,
                power_text=card.power_text,
                bonus_text=card.bonus_text,
                accent=self._card_accent(card, player_accent),
                illustration_label="Playable Card",
                illustration=self._load_card_illustration(card),
                bonus_active=card.clan in player.active_clan_bonuses,
                selected=is_selected,
                disabled=disabled,
                hidden=False,
                show_footer="Selected" if is_selected else "Played" if disabled else "Ready",
            )
            draw_card(self.screen, self.fonts, card_visual, mouse_pos=mouse_pos)
        self.screen.set_clip(previous_clip)
        self._draw_card_strip_scrollbar(player_viewport, player_content_width, self.ui_state.player_hand_scroll, player_accent)

        selected_card = self._selected_card()
        if selected_card is None:
            self._draw_waiting_pod(
                focus_rect,
                title="CARTE",
                body="Clique une carte de ta main pour ouvrir le focus detaille.",
                accent=player_accent,
            )
        else:
            self._draw_waiting_pod(
                focus_rect,
                title="FOCUS",
                body=f"{selected_card.name} est en focus. Clique a nouveau pour annuler.",
                accent=player_accent,
            )

    def _draw_center_panels(self, layout: dict[str, pygame.Rect | Button], mouse_pos: tuple[int, int]) -> None:
        """Draw round information plus the contextual selection focus panel."""
        assert self.state is not None
        info_rect = layout["center_info"]
        control_rect = layout["control_panel"]
        pills_rect = layout["pills_panel"]
        value_rect = layout["control_value_rect"]
        assert isinstance(info_rect, pygame.Rect)
        assert isinstance(control_rect, pygame.Rect)
        assert isinstance(pills_rect, pygame.Rect)
        assert isinstance(value_rect, pygame.Rect)

        draw_panel(self.screen, info_rect, fill=(14, 18, 28), border=(42, 50, 72))
        draw_panel(self.screen, control_rect, fill=(14, 18, 28), border=(68, 54, 120))
        draw_panel(self.screen, pills_rect, fill=(14, 18, 28), border=(42, 50, 72))

        self._draw_round_info_panel(info_rect)

        if self.ui_state.last_result is not None:
            self._draw_last_result_summary(info_rect, self.ui_state.last_result)

        selected_card = self._selected_card()
        if selected_card is None:
            self._draw_selection_placeholder(control_rect)
            self._draw_pills_panel(pills_rect, value_rect=value_rect, layout=layout, mouse_pos=mouse_pos, selected_card=None)
        else:
            self._draw_selected_card_panel(
                stage_rect=control_rect,
                pills_rect=pills_rect,
                value_rect=value_rect,
                selected_card=selected_card,
                mouse_pos=mouse_pos,
                layout=layout,
            )

        continue_button = layout["continue_button"]
        assert isinstance(continue_button, Button)
        if self.ui_state.mode == "feedback":
            continue_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])

    def _draw_round_info_panel(self, info_rect: pygame.Rect) -> None:
        """Render the left round summary panel."""
        assert self.state is not None
        selected_card = self._selected_card()
        projected_attack = selected_card.power * self.ui_state.selected_pills if selected_card is not None else "-"
        projected_damage = selected_card.damage if selected_card is not None else "-"
        local_player = self.state.get_player(1)
        bonus_label = selected_card.clan if selected_card and selected_card.clan in local_player.active_clan_bonuses else "-"

        draw_text(self.screen, self.fonts["small"], "INFOS DU ROUND", TEXT_PRIMARY, (info_rect.left + 16, info_rect.top + 16))
        metrics = [
            ("ATQ", str(projected_attack)),
            ("DMG", str(projected_damage)),
            ("INIT", "Toi" if self.ui_state.initiative_player_id == 1 else "IA"),
            ("BONUS", bonus_label),
        ]
        y = info_rect.top + 50
        for label, value in metrics:
            draw_text(self.screen, self.fonts["tiny"], label, TEXT_MUTED, (info_rect.left + 16, y))
            draw_text(
                self.screen,
                self.fonts["tiny"],
                value,
                TEXT_PRIMARY,
                (info_rect.right - 16, y),
                anchor="topright",
            )
            y += 24

        pygame.draw.line(self.screen, (44, 52, 74), (info_rect.left + 16, y + 2), (info_rect.right - 16, y + 2), 1)
        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            self.ui_state.banner_title,
            self.ui_state.banner_color,
            pygame.Rect(info_rect.left + 16, y + 16, info_rect.width - 32, 32),
            max_lines=2,
        )
        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            self.ui_state.banner_body,
            TEXT_MUTED,
            pygame.Rect(info_rect.left + 16, y + 54, info_rect.width - 32, info_rect.bottom - (y + 66)),
            max_lines=6,
        )

    def _draw_selection_placeholder(self, control_rect: pygame.Rect) -> None:
        """Render the neutral selection state with no pills controls."""
        draw_text(self.screen, self.fonts["hero"], f"ROUND {self.state.current_round} / {TOTAL_ROUNDS}", TEXT_PRIMARY, (control_rect.centerx, control_rect.top + 24), anchor="midtop")
        draw_text(
            self.screen,
            self.fonts["body"],
            "Selectionne une carte et choisis tes pills.",
            ACCENT_BLUE,
            (control_rect.centerx, control_rect.top + 72),
            anchor="midtop",
        )

        neutral_rect = pygame.Rect(control_rect.left + 40, control_rect.top + 106, control_rect.width - 80, 78)
        pygame.draw.rect(self.screen, (8, 14, 24), neutral_rect, border_radius=18)
        pygame.draw.rect(self.screen, (58, 92, 150), neutral_rect, width=2, border_radius=18)

        primary_hint = "Le detail de la carte et les controls de pills apparaitront ici."
        secondary_hint = "Clique la meme carte ou appuie sur Esc pour retirer le focus."
        if self.ui_state.initiative_player_id == 2 and self.ui_state.revealed_opponent_card_id is not None and self.state is not None:
            opponent_name = self.state.get_player(2).get_card(self.ui_state.revealed_opponent_card_id).name
            primary_hint = f"L'IA a revele {opponent_name}. Ses pills restent secretes."
            secondary_hint = "Choisis maintenant ta reponse."
        else:
            primary_hint = "Clique une carte dans ta main pour ouvrir le panneau detail."
            secondary_hint = "Les controls de pills apparaissent seulement quand une carte est en focus."

        draw_wrapped_text(
            self.screen,
            self.fonts["small"],
            primary_hint,
            TEXT_PRIMARY,
            pygame.Rect(neutral_rect.left + 18, neutral_rect.top + 14, neutral_rect.width - 36, 24),
            max_lines=2,
        )
        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            secondary_hint,
            TEXT_MUTED,
            pygame.Rect(neutral_rect.left + 18, neutral_rect.top + 44, neutral_rect.width - 36, 20),
            max_lines=2,
        )

    def _draw_selected_card_panel(
        self,
        *,
        stage_rect: pygame.Rect,
        pills_rect: pygame.Rect,
        value_rect: pygame.Rect,
        selected_card: Card,
        mouse_pos: tuple[int, int],
        layout: dict[str, pygame.Rect | Button],
    ) -> None:
        """Render the focused-card state with pills controls."""
        assert self.state is not None
        player = self.state.get_player(1)
        bonus_active = selected_card.clan in player.active_clan_bonuses
        accent = self._card_accent(selected_card, ACCENT_BLUE)
        minus_button = layout["minus_button"]
        plus_button = layout["plus_button"]
        confirm_button = layout["confirm_button"]
        assert isinstance(minus_button, Button)
        assert isinstance(plus_button, Button)
        assert isinstance(confirm_button, Button)

        header_rect = pygame.Rect(stage_rect.left + 18, stage_rect.top + 18, stage_rect.width - 36, 28)
        draw_text(self.screen, self.fonts["card_title"], selected_card.name.upper(), TEXT_PRIMARY, (header_rect.left, header_rect.top))
        draw_wrapped_text(
            self.screen,
            self.fonts["small"],
            selected_card.clan.upper(),
            accent,
            pygame.Rect(header_rect.left, header_rect.bottom + 2, header_rect.width - 56, 18),
            max_lines=1,
        )
        draw_text(
            self.screen,
            self.fonts["small"],
            "★" * selected_card.stars,
            ACCENT_GOLD,
            (header_rect.right, header_rect.top + 4),
            anchor="topright",
        )

        detail_width = min(272, max(236, int(stage_rect.width * 0.44)))
        detail_card_rect = pygame.Rect(stage_rect.left + 18, stage_rect.top + 58, detail_width, stage_rect.height - 76)
        info_rect = pygame.Rect(detail_card_rect.right + 18, stage_rect.top + 58, stage_rect.width - detail_card_rect.width - 54, stage_rect.height - 76)
        draw_card(
            self.screen,
            self.fonts,
            self._build_card_visual(
                selected_card,
                rect=detail_card_rect,
                selected=True,
                footer="Focused",
                bonus_active=bonus_active,
            ),
            mouse_pos=mouse_pos,
        )

        info_panel = info_rect.inflate(0, 0)
        pygame.draw.rect(self.screen, (31, 38, 55), info_panel, border_radius=18)
        pygame.draw.rect(self.screen, accent, info_panel, width=2, border_radius=18)

        draw_text(self.screen, self.fonts["small"], "CLAN", TEXT_MUTED, (info_panel.left + 16, info_panel.top + 14))
        next_y = draw_wrapped_text(
            self.screen,
            self.fonts["body"],
            selected_card.clan,
            TEXT_PRIMARY,
            pygame.Rect(info_panel.left + 16, info_panel.top + 34, info_panel.width - 32, 32),
            max_lines=2,
        )

        draw_text(self.screen, self.fonts["small"], "BONUS DE CLAN", TEXT_MUTED, (info_panel.left + 16, next_y + 8))
        draw_text(
            self.screen,
            self.fonts["tiny"],
            "ACTIF" if bonus_active else "INACTIF",
            ACCENT_GREEN if bonus_active else TEXT_MUTED,
            (info_panel.right - 16, next_y + 12),
            anchor="topright",
        )
        next_y = draw_wrapped_text(
            self.screen,
            self.fonts["small"],
            selected_card.bonus_text,
            ACCENT_GREEN if bonus_active else (255, 191, 150),
            pygame.Rect(info_panel.left + 16, next_y + 28, info_panel.width - 32, 52),
            max_lines=3,
        )

        draw_text(self.screen, self.fonts["small"], "ETOILES", TEXT_MUTED, (info_panel.left + 16, next_y + 10))
        draw_text(
            self.screen,
            self.fonts["body"],
            "★" * selected_card.stars,
            ACCENT_GOLD,
            (info_panel.left + 16, next_y + 32),
        )
        draw_wrapped_text(
            self.screen,
            self.fonts["small"],
            "POUVOIR",
            TEXT_MUTED,
            pygame.Rect(info_panel.left + 16, next_y + 60, info_panel.width - 32, 18),
            max_lines=1,
        )
        draw_wrapped_text(
            self.screen,
            self.fonts["body"],
            f"Power: {selected_card.power_text}",
            TEXT_PRIMARY,
            pygame.Rect(info_panel.left + 16, next_y + 82, info_panel.width - 32, max(36, info_panel.bottom - (next_y + 96))),
            max_lines=3,
        )
        self._draw_pills_panel(
            pills_rect,
            value_rect=value_rect,
            layout=layout,
            mouse_pos=mouse_pos,
            selected_card=selected_card,
        )

    def _draw_pills_panel(
        self,
        rect: pygame.Rect,
        *,
        value_rect: pygame.Rect,
        layout: dict[str, pygame.Rect | Button],
        mouse_pos: tuple[int, int],
        selected_card: Card | None,
    ) -> None:
        """Render the right pills/confirmation panel."""
        assert self.state is not None
        player = self.state.get_player(1)

        title = "PILLS A ENGAGER" if selected_card is not None else "PILLS RESTANTES"
        draw_text(self.screen, self.fonts["section"], title, TEXT_PRIMARY, (rect.left + 18, rect.top + 16))
        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            "Clique sur - ou + pour regler la mise." if selected_card is not None else "Clique une carte pour afficher les controls de pills.",
            TEXT_MUTED,
            pygame.Rect(rect.left + 18, rect.top + 48, rect.width - 36, 32),
            max_lines=2,
        )

        draw_pill_track(
            self.screen,
            pygame.Rect(rect.left + 18, rect.top + 86, rect.width - 36, 20),
            total=TOTAL_PILLS,
            available=player.pills - self.ui_state.selected_pills,
            committed=self.ui_state.selected_pills if selected_card is not None else 0,
            accent=ACCENT_BLUE,
        )
        draw_text(
            self.screen,
            self.fonts["hero"],
            f"{player.pills - self.ui_state.selected_pills}/{TOTAL_PILLS}" if selected_card is not None else f"{player.pills}/{TOTAL_PILLS}",
            ACCENT_BLUE,
            (rect.centerx, rect.top + 112),
            anchor="midtop",
        )

        if self.ui_state.mode == "feedback":
            continue_button = layout["continue_button"]
            assert isinstance(continue_button, Button)
            self._draw_waiting_pod(
                pygame.Rect(rect.left + 18, rect.top + 142, rect.width - 36, max(74, rect.height - 220)),
                title="ROUND TERMINE",
                body="Clique sur Suite ou appuie sur Espace pour passer au round suivant.",
                accent=ACCENT_TEAL,
            )
            draw_wrapped_text(
                self.screen,
                self.fonts["tiny"],
                "Les pills non depensees restent disponibles pour les prochains rounds.",
                TEXT_MUTED,
                pygame.Rect(rect.left + 18, rect.bottom - 86, rect.width - 36, 24),
                max_lines=2,
            )
            continue_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])
            return

        if selected_card is None:
            self._draw_waiting_pod(
                pygame.Rect(rect.left + 18, rect.top + 142, rect.width - 36, rect.height - 160),
                title="SELECTION",
                body="La carte choisie ouvrira ici les commandes de pills et la confirmation.",
                accent=ACCENT_BLUE,
            )
            return

        pygame.draw.rect(self.screen, (38, 43, 61), value_rect, border_radius=16)
        pygame.draw.rect(self.screen, ACCENT_GOLD, value_rect, width=2, border_radius=16)
        draw_text(self.screen, self.fonts["hero"], str(self.ui_state.selected_pills), TEXT_PRIMARY, value_rect.center, anchor="center")

        minus_button = layout["minus_button"]
        plus_button = layout["plus_button"]
        confirm_button = layout["confirm_button"]
        assert isinstance(minus_button, Button)
        assert isinstance(plus_button, Button)
        assert isinstance(confirm_button, Button)
        minus_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])
        plus_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])
        confirm_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])

        draw_wrapped_text(
            self.screen,
            self.fonts["tiny"],
            "Les pills restantes seront conservees pour les prochains rounds.",
            TEXT_MUTED,
            pygame.Rect(rect.left + 18, rect.bottom - 18, rect.width - 36, 16),
            max_lines=2,
        )

    def _draw_last_result_summary(self, info_rect: pygame.Rect, result: RoundResult) -> None:
        """Render a compact summary of the previous round."""
        assert self.state is not None
        reserved_width = 210 if self.ui_state.mode == "feedback" else 44
        battle_rect = pygame.Rect(info_rect.left + 22, info_rect.top + 170, info_rect.width - reserved_width, 40)
        pygame.draw.rect(self.screen, (36, 42, 60), battle_rect, border_radius=14)
        pygame.draw.rect(self.screen, self.ui_state.banner_color, battle_rect, width=2, border_radius=14)

        left_name = self.state.get_player(1).get_card(result.player_1_card_id).name
        right_name = self.state.get_player(2).get_card(result.player_2_card_id).name
        left_text = f"You: {left_name} | atk {result.player_1_attack}"
        right_text = f"AI: {right_name} | atk {result.player_2_attack}"
        outcome = "Tie" if result.winner_id is None else "Winner: You" if result.winner_id == 1 else "Winner: AI"

        draw_text(self.screen, self.fonts["tiny"], left_text, TEXT_PRIMARY, (battle_rect.left + 14, battle_rect.top + 12))
        draw_text(
            self.screen,
            self.fonts["tiny"],
            right_text,
            TEXT_PRIMARY,
            (battle_rect.left + max(210, battle_rect.width // 2), battle_rect.top + 12),
        )
        draw_text(self.screen, self.fonts["small"], outcome, TEXT_PRIMARY, (battle_rect.right - 14, battle_rect.centery), anchor="midright")

    def _draw_game_over_overlay(self, layout: dict[str, pygame.Rect | Button], mouse_pos: tuple[int, int]) -> None:
        """Render the victory screen overlay."""
        assert self.state is not None
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((8, 10, 18, 170))
        self.screen.blit(overlay, (0, 0))

        modal_rect = pygame.Rect(SCREEN_WIDTH // 2 - 260, SCREEN_HEIGHT // 2 - 150, 520, 320)
        draw_panel(self.screen, modal_rect, fill=(25, 31, 45), border=self._final_accent())

        title = self._final_title()
        subtitle = self._final_subtitle()

        draw_text(self.screen, self.fonts["victory"], title, self._final_accent(), (modal_rect.centerx, modal_rect.top + 42), anchor="midtop")
        draw_wrapped_text(
            self.screen,
            self.fonts["body"],
            subtitle,
            TEXT_MUTED,
            pygame.Rect(modal_rect.left + 40, modal_rect.top + 92, modal_rect.width - 80, 44),
            max_lines=2,
        )

        player_1 = self.state.get_player(1)
        player_2 = self.state.get_player(2)
        score_rect = pygame.Rect(modal_rect.left + 42, modal_rect.top + 140, modal_rect.width - 84, 72)
        pygame.draw.rect(self.screen, (35, 42, 60), score_rect, border_radius=18)
        pygame.draw.rect(self.screen, self._final_accent(), score_rect, width=2, border_radius=18)
        draw_text(self.screen, self.fonts["section"], f"{player_1.hit_points} HP", TEXT_PRIMARY, (score_rect.left + 34, score_rect.centery), anchor="midleft")
        draw_text(self.screen, self.fonts["section"], "VS", TEXT_MUTED, score_rect.center, anchor="center")
        draw_text(self.screen, self.fonts["section"], f"{player_2.hit_points} HP", TEXT_PRIMARY, (score_rect.right - 34, score_rect.centery), anchor="midright")

        draw_text(
            self.screen,
            self.fonts["tiny"],
            "Press R to restart or Esc to quit.",
            TEXT_MUTED,
            (modal_rect.centerx, modal_rect.bottom - 76),
            anchor="center",
        )

        restart_button = layout["restart_button"]
        quit_button = layout["quit_button"]
        assert isinstance(restart_button, Button)
        assert isinstance(quit_button, Button)
        restart_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])
        quit_button.draw(self.screen, mouse_pos=mouse_pos, label_font=self.fonts["button"])

    def _selected_card_name(self) -> str:
        """Return the current selected card name."""
        assert self.state is not None
        if self.ui_state.selected_card_id is None:
            return "None"
        return self.state.get_player(1).get_card(self.ui_state.selected_card_id).name

    def _initiative_player_id_for_round(self, round_number: int) -> int:
        """Return which side chooses first on a given round."""
        return 1 if round_number % 2 == 1 else 2

    def _initiative_caption(self, *, for_player_id: int) -> str:
        """Return a readable caption describing initiative for the current round."""
        if self.ui_state.mode in {"feedback", "game_over"}:
            return "Round resolved"
        if self.ui_state.initiative_player_id == for_player_id:
            return "Chooses first this round"
        return "Chooses second this round"

    def _final_title(self) -> str:
        """Return the end-game headline."""
        assert self.state is not None
        if self.state.status is GameStatus.PLAYER_1_WON:
            return "Victory"
        if self.state.status is GameStatus.PLAYER_2_WON:
            return "Defeat"
        return "Draw"

    def _final_subtitle(self) -> str:
        """Return the end-game explanation."""
        assert self.state is not None
        if self.state.status is GameStatus.PLAYER_1_WON:
            return "You controlled the tempo better over the full match."
        if self.state.status is GameStatus.PLAYER_2_WON:
            return "The AI kept the upper hand. Try a different pill curve."
        return "Both sides ended with the same life total after four rounds."

    def _final_accent(self) -> Color:
        """Return the end-game accent color."""
        assert self.state is not None
        if self.state.status is GameStatus.PLAYER_1_WON:
            return ACCENT_GREEN
        if self.state.status is GameStatus.PLAYER_2_WON:
            return ACCENT_RED
        return ACCENT_GOLD

    def _card_viewport(self, hand_rect: pygame.Rect) -> pygame.Rect:
        """Return the clipped viewport used to draw a horizontal card strip."""
        return pygame.Rect(
            hand_rect.left + 4,
            hand_rect.top + 4,
            max(1, hand_rect.width - 8),
            max(1, hand_rect.height - 18),
        )

    def _draw_card_strip_background(self, viewport: pygame.Rect) -> None:
        """Draw a subtle lane behind one horizontal card strip."""
        lane_rect = viewport.inflate(0, 8)
        pygame.draw.rect(self.screen, (23, 28, 42), lane_rect, border_radius=18)
        pygame.draw.rect(self.screen, (44, 52, 75), lane_rect, width=1, border_radius=18)

    def _draw_card_strip_scrollbar(self, viewport: pygame.Rect, content_width: int, offset: int, accent: Color) -> None:
        """Render a horizontal scrollbar when the card strip overflows."""
        scrollbar_rect = pygame.Rect(viewport.left + 10, viewport.bottom + 4, viewport.width - 20, 6)
        draw_horizontal_scrollbar(
            self.screen,
            scrollbar_rect,
            content_width=content_width,
            viewport_width=viewport.width,
            offset=offset,
            accent=accent,
        )

    def _scroll_card_strip(
        self,
        current_offset: int,
        card_count: int,
        viewport: pygame.Rect,
        *,
        card_width: int,
        card_height: int,
        gap: int,
        shrink_to_fit: bool,
        delta: int,
    ) -> int:
        """Clamp a strip offset after applying a scroll delta."""
        content_width = self._card_strip_content_width(
            card_count,
            viewport,
            card_width=card_width,
            card_height=card_height,
            gap=gap,
            shrink_to_fit=shrink_to_fit,
        )
        max_scroll = max(0, content_width - viewport.width)
        return max(0, min(max_scroll, current_offset + delta))

    def _card_strip_content_width(
        self,
        card_count: int,
        viewport: pygame.Rect,
        *,
        card_width: int,
        card_height: int,
        gap: int,
        shrink_to_fit: bool,
    ) -> int:
        """Compute the total width required by one strip."""
        if card_count <= 0:
            return 0

        fitted_gap = gap
        fitted_width = min(card_width, viewport.width)
        _ = min(card_height, viewport.height)

        total_width = (card_count * fitted_width) + ((card_count - 1) * fitted_gap)
        if shrink_to_fit and total_width > viewport.width and card_count > 1:
            fitted_width = max(148, (viewport.width - ((card_count - 1) * fitted_gap)) // card_count)
            total_width = (card_count * fitted_width) + ((card_count - 1) * fitted_gap)

        if shrink_to_fit and total_width > viewport.width and card_count > 1:
            fitted_gap = max(8, (viewport.width - (card_count * fitted_width)) // (card_count - 1))
            total_width = (card_count * fitted_width) + ((card_count - 1) * fitted_gap)

        return total_width

    def _layout_card_strip(
        self,
        cards: list[Card],
        viewport: pygame.Rect,
        *,
        card_width: int,
        card_height: int,
        gap: int,
        scroll_offset: int = 0,
        shrink_to_fit: bool = True,
    ) -> tuple[list[tuple[Card, pygame.Rect]], int, int, int]:
        """Compute card rectangles inside a scrollable hand panel."""
        if not cards:
            return [], 0, 0, 0

        card_count = len(cards)
        fitted_gap = gap
        fitted_width = min(card_width, viewport.width)
        fitted_height = min(card_height, viewport.height)

        total_width = (card_count * fitted_width) + ((card_count - 1) * fitted_gap)
        if shrink_to_fit and total_width > viewport.width and card_count > 1:
            fitted_width = max(148, (viewport.width - ((card_count - 1) * fitted_gap)) // card_count)
            total_width = (card_count * fitted_width) + ((card_count - 1) * fitted_gap)

        if shrink_to_fit and total_width > viewport.width and card_count > 1:
            fitted_gap = max(8, (viewport.width - (card_count * fitted_width)) // (card_count - 1))
            total_width = (card_count * fitted_width) + ((card_count - 1) * fitted_gap)

        max_scroll = max(0, total_width - viewport.width)
        clamped_scroll = max(0, min(scroll_offset, max_scroll))
        if max_scroll == 0:
            start_x = viewport.left + max(0, (viewport.width - total_width) // 2)
        else:
            start_x = viewport.left - clamped_scroll
        start_y = viewport.top + max(0, (viewport.height - fitted_height) // 2)

        rects = [
            (
                card,
                pygame.Rect(start_x + index * (fitted_width + fitted_gap), start_y, fitted_width, fitted_height),
            )
            for index, card in enumerate(cards)
        ]
        return rects, total_width, max_scroll, clamped_scroll

    def _card_accent(self, card: Card, fallback: Color) -> Color:
        """Return a clan-driven accent color that stays readable across the HUD."""
        clan_palette = {
            "Pulse 404": ACCENT_PURPLE,
            "Verdelune": ACCENT_GREEN,
            "Bastion-9": ACCENT_BLUE,
        }
        return clan_palette.get(card.clan, fallback)

    def _build_card_visual(
        self,
        card: Card,
        *,
        rect: pygame.Rect,
        selected: bool,
        footer: str,
        bonus_active: bool,
    ) -> CardVisual:
        """Create a rich card visual shared by draft and round rendering."""
        return CardVisual(
            rect=rect,
            title=card.name,
            clan=card.clan,
            stars=card.stars,
            power=card.power,
            damage=card.damage,
            power_text=card.power_text,
            bonus_text=card.bonus_text,
            accent=self._card_accent(card, ACCENT_BLUE),
            illustration_label="Urban Duel Card",
            illustration=self._load_card_illustration(card),
            bonus_active=bonus_active,
            selected=selected,
            hidden=False,
            show_footer=footer,
        )

    def _load_card_illustration(self, card: Card) -> pygame.Surface | None:
        """Load and cache a card illustration from its relative asset path."""
        if card.illustration in self._illustration_cache:
            return self._illustration_cache[card.illustration]

        image_path = (self.asset_root / card.illustration).resolve()
        try:
            image = pygame.image.load(str(image_path)).convert_alpha()
        except (FileNotFoundError, pygame.error):
            image = None

        self._illustration_cache[card.illustration] = image
        return image

    def _build_fonts(self) -> dict[str, pygame.font.Font]:
        """Create fonts used by the interface."""
        return {
            "victory": pygame.font.SysFont("arial", 44, bold=True),
            "hero": pygame.font.SysFont("arial", 36, bold=True),
            "section": pygame.font.SysFont("arial", 28, bold=True),
            "card_title": pygame.font.SysFont("arial", 22, bold=True),
            "button": pygame.font.SysFont("arial", 24, bold=True),
            "body": pygame.font.SysFont("arial", 20),
            "small": pygame.font.SysFont("arial", 18),
            "tiny": pygame.font.SysFont("arial", 14),
        }
