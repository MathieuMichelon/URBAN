"""Console-oriented helpers for deterministic engine simulations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
import sys

from ai.base import BaseAIChoiceProvider
from ai.bot import HeuristicAIChoiceProvider
from core.draft import DraftPhase, build_draft_offer
from core.engine import GameEngine
from core.models import Card, GameState, RoundSelection
from data.card_repository import load_cards


@dataclass(frozen=True, slots=True)
class SoloDraftMatchSetup:
    """Deterministic solo setup built from the shared draft flow."""

    offer: list[Card]
    player_1_team: list[Card]
    player_2_team: list[Card]
    state: GameState


def simulate_console_match(
    player_1_hand: list[Card],
    player_2_hand: list[Card],
    player_1_script: Iterable[RoundSelection],
    player_2_script: Iterable[RoundSelection],
    stream: TextIO | None = None,
) -> GameState:
    """Simulate a full match and print a simple text trace."""
    output = stream or sys.stdout
    engine = GameEngine()
    state = engine.create_game(player_1_hand=player_1_hand, player_2_hand=player_2_hand)

    player_1_steps = list(player_1_script)
    player_2_steps = list(player_2_script)

    if len(player_1_steps) < 1 or len(player_2_steps) < 1:
        raise ValueError("Both players must provide at least one scripted round selection.")

    output.write("=== Urban Duel Simulation ===\n")

    round_index = 0
    while not state.is_over:
        if round_index >= len(player_1_steps) or round_index >= len(player_2_steps):
            raise ValueError("Not enough scripted round selections to finish the match.")

        selection_1 = player_1_steps[round_index]
        selection_2 = player_2_steps[round_index]
        result = engine.play_round(
            state=state,
            player_1_selection=selection_1,
            player_2_selection=selection_2,
        )
        player_1 = state.get_player(1)
        player_2 = state.get_player(2)

        output.write(
            f"Round {result.round_number}: "
            f"P1 {result.player_1_card_id} ({result.player_1_attack}) vs "
            f"P2 {result.player_2_card_id} ({result.player_2_attack})\n"
        )

        if result.winner_id is None:
            output.write("Result: tie\n")
        else:
            output.write(
                f"Result: player {result.winner_id} wins and deals {result.damage_dealt} damage\n"
            )

        output.write(
            f"HP -> P1: {player_1.hit_points} | P2: {player_2.hit_points} | "
            f"Pills -> P1: {player_1.pills} | P2: {player_2.pills}\n"
        )
        round_index += 1

    if state.winner_id is None:
        output.write("Final result: draw\n")
    else:
        output.write(f"Final result: player {state.winner_id} wins\n")

    return state


def simulate_console_match_from_json(
    cards_path: str | Path,
    player_1_script: Iterable[RoundSelection],
    player_2_script: Iterable[RoundSelection],
    stream: TextIO | None = None,
) -> GameState:
    """Load cards from JSON and run a deterministic console simulation."""
    cards = load_cards(cards_path)
    return simulate_console_match(
        player_1_hand=cards[:4],
        player_2_hand=cards[4:8],
        player_1_script=player_1_script,
        player_2_script=player_2_script,
        stream=stream,
    )


def build_solo_draft_match(
    cards: list[Card],
    player_1_draft_ids: Iterable[str],
    *,
    ai_provider: BaseAIChoiceProvider | None = None,
    draft_seed: str | int | None = "solo-mode",
) -> SoloDraftMatchSetup:
    """Build a solo match through the same draft flow used by the live modes."""
    provider = ai_provider or HeuristicAIChoiceProvider()
    draft_phase = DraftPhase(build_draft_offer(cards, seed=draft_seed))

    for card_id in player_1_draft_ids:
        draft_phase.toggle_card(1, card_id)

    draft_phase.lock_team(1)
    player_1_team = draft_phase.selected_cards(1)
    player_2_team = provider.choose_team(draft_phase.offer)

    engine = GameEngine()
    state = engine.create_game(player_1_hand=player_1_team, player_2_hand=player_2_team)
    return SoloDraftMatchSetup(
        offer=list(draft_phase.offer),
        player_1_team=list(player_1_team),
        player_2_team=list(player_2_team),
        state=state,
    )


def simulate_solo_match_with_draft_from_json(
    cards_path: str | Path,
    player_1_draft_ids: Iterable[str],
    player_1_script: Iterable[RoundSelection],
    *,
    ai_provider: BaseAIChoiceProvider | None = None,
    draft_seed: str | int | None = "solo-mode",
    stream: TextIO | None = None,
) -> GameState:
    """Run a deterministic solo match using the shared draft flow plus the core engine."""
    output = stream or sys.stdout
    cards = load_cards(cards_path)
    provider = ai_provider or HeuristicAIChoiceProvider()
    setup = build_solo_draft_match(
        cards,
        player_1_draft_ids,
        ai_provider=provider,
        draft_seed=draft_seed,
    )
    engine = GameEngine()
    state = setup.state
    player_1_steps = list(player_1_script)

    if len(player_1_steps) < 1:
        raise ValueError("Player 1 must provide at least one scripted round selection.")

    output.write("=== Urban Duel Solo Draft Simulation ===\n")
    output.write(f"Draft offer size: {len(setup.offer)}\n")
    output.write(
        f"Drafted teams -> P1: {', '.join(card.id for card in setup.player_1_team)} | "
        f"P2: {', '.join(card.id for card in setup.player_2_team)}\n"
    )

    round_index = 0
    while not state.is_over:
        if round_index >= len(player_1_steps):
            raise ValueError("Not enough scripted round selections to finish the solo match.")

        selection_1 = player_1_steps[round_index]
        selection_2 = provider.choose_action(state, state.get_player(2))
        result = engine.play_round(
            state=state,
            player_1_selection=selection_1,
            player_2_selection=selection_2,
        )
        player_1 = state.get_player(1)
        player_2 = state.get_player(2)

        output.write(
            f"Round {result.round_number}: "
            f"P1 {result.player_1_card_id} ({result.player_1_attack}) vs "
            f"P2 {result.player_2_card_id} ({result.player_2_attack})\n"
        )

        if result.winner_id is None:
            output.write("Result: tie\n")
        else:
            output.write(
                f"Result: player {result.winner_id} wins and deals {result.damage_dealt} damage\n"
            )

        output.write(
            f"HP -> P1: {player_1.hit_points} | P2: {player_2.hit_points} | "
            f"Pills -> P1: {player_1.pills} | P2: {player_2.pills}\n"
        )
        round_index += 1

    if state.winner_id is None:
        output.write("Final result: draw\n")
    else:
        output.write(f"Final result: player {state.winner_id} wins\n")

    return state


def build_demo_selections() -> tuple[list[RoundSelection], list[RoundSelection]]:
    """Return deterministic demo selections for quick manual runs."""
    player_1_script = [
        RoundSelection("hackeuse_cyber", 3),
        RoundSelection("rebelle_neon", 2),
        RoundSelection("ninja_urbain", 4),
        RoundSelection("proxy_ghost", 3),
    ]
    player_2_script = [
        RoundSelection("spectre_pixel", 2),
        RoundSelection("volt_dj", 2),
        RoundSelection("laser_tagger", 1),
        RoundSelection("echo_runner", 3),
    ]
    return player_1_script, player_2_script
