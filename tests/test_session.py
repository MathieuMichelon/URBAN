"""Unit tests for the network-ready match session layer."""

import pytest

from core.engine import GameEngine
from core.errors import RoundSynchronizationError, SelectionAlreadySubmittedError
from core.models import Card, RoundSelection
from core.session import MatchSession


def test_match_session_resolves_round_only_after_both_players_submit(
    card_factory,
) -> None:
    """A session should buffer one selection per player and resolve on the second."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    session = MatchSession(engine=engine, state=state)

    first_result = session.submit_selection(1, RoundSelection("p1c1", 3), round_number=1)
    second_result = session.submit_selection(2, RoundSelection("p2c1", 2), round_number=1)

    assert first_result is None
    assert second_result is not None
    assert second_result.round_number == 1
    assert session.pending_player_ids() == ()
    assert state.current_round == 2


def test_match_session_rejects_duplicate_submission_for_same_round(
    card_factory,
) -> None:
    """A player should not be able to submit twice in the same round."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    session = MatchSession(engine=engine, state=state)

    session.submit_selection(1, RoundSelection("p1c1", 3), round_number=1)

    with pytest.raises(SelectionAlreadySubmittedError, match="already submitted"):
        session.submit_selection(1, RoundSelection("p1c2", 2), round_number=1)


def test_match_session_rejects_stale_round_number(
    card_factory,
) -> None:
    """Submitted commands should target the authoritative current round."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    session = MatchSession(engine=engine, state=state)

    with pytest.raises(RoundSynchronizationError, match="current round is 1"):
        session.submit_selection(1, RoundSelection("p1c1", 3), round_number=2)
