"""Unit tests for save/load of full game states."""

from pathlib import Path

import pytest

from core.engine import GameEngine
from core.errors import SaveGameFormatError
from core.models import Card, GameState, RoundSelection


def test_engine_can_export_and_import_an_in_progress_game_state(
    card_factory,
) -> None:
    """Exported state should restore the exact same in-progress match."""
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
    engine.play_round(
        state=state,
        player_1_selection=RoundSelection("p1c2", 2),
        player_2_selection=RoundSelection("p2c2", 2),
    )

    payload = engine.export_state(state)
    restored_state = engine.import_state(payload)

    _assert_states_equal(restored_state, state)


def test_engine_can_save_to_json_file_and_load_it_back(
    card_factory,
    tmp_path: Path,
) -> None:
    """Saving to disk and loading back should preserve the full game state."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    save_path = tmp_path / "savegame.json"

    engine.play_round(
        state=state,
        player_1_selection=RoundSelection("p1c1", 3),
        player_2_selection=RoundSelection("p2c1", 2),
    )

    engine.save_state(state, save_path)
    loaded_state = engine.load_state(save_path)

    assert save_path.exists() is True
    _assert_states_equal(loaded_state, state)


def test_loaded_game_can_resume_from_the_exact_saved_round(
    card_factory,
    tmp_path: Path,
) -> None:
    """A loaded game should continue exactly from the saved point."""
    engine = GameEngine()
    original_state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )

    opening_rounds = [
        (RoundSelection("p1c1", 3), RoundSelection("p2c1", 2)),
        (RoundSelection("p1c2", 2), RoundSelection("p2c2", 2)),
    ]
    remaining_rounds = [
        (RoundSelection("p1c3", 4), RoundSelection("p2c3", 1)),
        (RoundSelection("p1c4", 3), RoundSelection("p2c4", 3)),
    ]

    for player_1_selection, player_2_selection in opening_rounds:
        engine.play_round(
            state=original_state,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
        )

    save_path = tmp_path / "resume_save.json"
    engine.save_state(original_state, save_path)

    resumed_state = engine.load_state(save_path)
    expected_final_state = engine.import_state(engine.export_state(original_state))

    for player_1_selection, player_2_selection in remaining_rounds:
        engine.play_round(
            state=resumed_state,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
        )
        engine.play_round(
            state=expected_final_state,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
        )

    _assert_states_equal(resumed_state, expected_final_state)


def test_import_state_rejects_invalid_save_payload(card_factory) -> None:
    """Malformed save payloads should raise explicit format errors."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    payload = engine.export_state(state)
    invalid_payload = dict(payload)
    invalid_payload["game_state"] = {
        **payload["game_state"],
        "players": {
            "1": payload["game_state"]["players"]["1"],
            "2": payload["game_state"]["players"]["2"],
        },
        "winner_id": 1,
    }

    with pytest.raises(SaveGameFormatError, match="in-progress game cannot define a winner_id"):
        engine.import_state(invalid_payload)


def _assert_states_equal(left: GameState, right: GameState) -> None:
    """Assert that two game states represent the same match snapshot."""
    assert left.current_round == right.current_round
    assert left.starting_initiative_player_id == right.starting_initiative_player_id
    assert left.status == right.status
    assert left.winner_id == right.winner_id
    assert left.history == right.history

    for player_id in (1, 2):
        left_player = left.get_player(player_id)
        right_player = right.get_player(player_id)

        assert left_player.player_id == right_player.player_id
        assert left_player.hit_points == right_player.hit_points
        assert left_player.pills == right_player.pills
        assert left_player.hand == right_player.hand
        assert left_player.played_card_ids == right_player.played_card_ids
