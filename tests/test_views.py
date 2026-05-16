"""Unit tests for serializable game snapshots."""

from core.engine import GameEngine
from core.models import Card, RoundSelection
from core.session import MatchSession
from core.views import build_game_snapshot


def test_game_snapshot_hides_opponent_unplayed_cards_from_a_player_view(
    card_factory,
) -> None:
    """A player-facing snapshot should not reveal unplayed opponent cards."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )

    snapshot = build_game_snapshot(state, perspective_player_id=1)

    opponent_slots = snapshot["players"]["2"]["hand"]
    assert opponent_slots[0]["card"] is None
    assert opponent_slots[1]["card"] is None
    assert opponent_slots[2]["card"] is None
    assert opponent_slots[3]["card"] is None


def test_game_snapshot_reveals_played_opponent_cards_after_resolution(
    card_factory,
) -> None:
    """A player-facing snapshot may reveal already played opponent cards."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    engine.play_round(
        state=state,
        player_1_selection=RoundSelection("p1c1", 3),
        player_2_selection=RoundSelection("p2c1", 2),
    )

    snapshot = build_game_snapshot(state, perspective_player_id=1)

    opponent_slots = snapshot["players"]["2"]["hand"]
    assert opponent_slots[0]["card"]["id"] == "p2c1"
    assert opponent_slots[0]["played"] is True
    assert opponent_slots[1]["card"] is None


def test_match_session_snapshot_exposes_pending_submissions(
    card_factory,
) -> None:
    """A session snapshot should include which players already submitted."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    session = MatchSession(engine=engine, state=state)
    session.submit_selection(1, RoundSelection("p1c1", 2), round_number=1)

    snapshot = session.build_snapshot(perspective_player_id=1)

    assert snapshot["pending_player_ids"] == [1]
