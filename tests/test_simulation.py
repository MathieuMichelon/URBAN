"""Unit tests for console simulation helpers."""

from itertools import combinations
from io import StringIO
from pathlib import Path

from ai.bot import ScriptedAIChoiceProvider
from core.draft import build_draft_offer
from data.card_repository import load_cards
from core.models import RoundSelection
from core.simulation import build_solo_draft_match, simulate_console_match_from_json, simulate_solo_match_with_draft_from_json


def _first_valid_draft_ids(offer) -> list[str]:
    """Return the first legal 4-card team from a deterministic offer."""
    for team in combinations(offer, 4):
        if sum(card.stars for card in team) <= 8:
            return [card.id for card in team]
    raise AssertionError("Expected a legal 4-card team in the draft offer.")


def test_simulation_from_json_runs_and_prints_trace() -> None:
    """The console simulation should produce a readable trace."""
    project_root = Path(__file__).resolve().parents[1]
    stream = StringIO()
    cards = load_cards(project_root / "data" / "cards.json")
    player_1_ids = [card.id for card in cards[:4]]
    player_2_ids = [card.id for card in cards[4:8]]

    state = simulate_console_match_from_json(
        cards_path=project_root / "data" / "cards.json",
        player_1_script=[
            RoundSelection(player_1_ids[0], 3),
            RoundSelection(player_1_ids[1], 2),
            RoundSelection(player_1_ids[2], 4),
            RoundSelection(player_1_ids[3], 3),
        ],
        player_2_script=[
            RoundSelection(player_2_ids[0], 2),
            RoundSelection(player_2_ids[1], 2),
            RoundSelection(player_2_ids[2], 1),
            RoundSelection(player_2_ids[3], 3),
        ],
        stream=stream,
    )

    output = stream.getvalue()
    assert "Urban Duel Simulation" in output
    assert "Round 1" in output
    assert "Final result:" in output
    assert state.is_over is True


def test_build_solo_draft_match_uses_shared_draft_and_engine(sample_cards) -> None:
    """Solo setup should go through the shared draft flow before creating the game."""
    offer = build_draft_offer(sample_cards, seed="solo-mode")
    player_1_draft_ids = _first_valid_draft_ids(offer)
    player_2_draft_ids = _first_valid_draft_ids(offer)
    scripted_provider = ScriptedAIChoiceProvider(
        selections=[],
        team_card_ids=player_2_draft_ids,
    )

    setup = build_solo_draft_match(
        sample_cards,
        player_1_draft_ids=player_1_draft_ids,
        ai_provider=scripted_provider,
        draft_seed="solo-mode",
    )

    assert len(setup.offer) == 10
    assert [card.id for card in setup.player_1_team] == player_1_draft_ids
    assert [card.id for card in setup.player_2_team] == player_2_draft_ids
    assert len(setup.state.get_player(1).hand) == 4
    assert len(setup.state.get_player(2).hand) == 4


def test_solo_draft_simulation_from_json_runs_with_scripted_ai() -> None:
    """The fast solo simulation path should run through draft plus the shared engine."""
    project_root = Path(__file__).resolve().parents[1]
    stream = StringIO()
    cards = load_cards(project_root / "data" / "cards.json")
    offer = build_draft_offer(cards, seed="solo-mode")
    player_1_draft_ids = _first_valid_draft_ids(offer)
    player_2_draft_ids = _first_valid_draft_ids(offer)
    scripted_provider = ScriptedAIChoiceProvider(
        selections=[
            RoundSelection(player_2_draft_ids[0], 1),
            RoundSelection(player_2_draft_ids[1], 1),
            RoundSelection(player_2_draft_ids[2], 1),
            RoundSelection(player_2_draft_ids[3], 1),
        ],
        team_card_ids=player_2_draft_ids,
    )

    state = simulate_solo_match_with_draft_from_json(
        cards_path=project_root / "data" / "cards.json",
        player_1_draft_ids=player_1_draft_ids,
        player_1_script=[
            RoundSelection(player_1_draft_ids[0], 2),
            RoundSelection(player_1_draft_ids[1], 2),
            RoundSelection(player_1_draft_ids[2], 2),
            RoundSelection(player_1_draft_ids[3], 2),
        ],
        ai_provider=scripted_provider,
        draft_seed="solo-mode",
        stream=stream,
    )

    output = stream.getvalue()
    assert "Urban Duel Solo Draft Simulation" in output
    assert "Draft offer size: 10" in output
    assert "Drafted teams -> P1:" in output
    assert "Round 1" in output
    assert "Final result:" in output
    assert state.is_over is True
