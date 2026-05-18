"""Unit tests for the pure game engine."""

import pytest

from core.engine import GameEngine
from core.enums import GameStatus, RoundOutcome
from core.errors import CardAlreadyPlayedError, GameAlreadyFinishedError, InvalidGameSetupError, NotEnoughPillsError
from core.models import Card, RoundSelection
from core.rules import STARTING_HIT_POINTS, compute_attack


def _simple_hand(card_factory, prefix: str, stats: list[tuple[int, int]]) -> list[Card]:
    """Build a deterministic hand with no active clan bonuses."""
    hand: list[Card] = []
    for index, (power, damage) in enumerate(stats, start=1):
        hand.append(
            card_factory(
                f"{prefix}{index}",
                clan=f"{prefix}_clan_{index}",
                power=power,
                damage=damage,
                power_text="No power",
                bonus_text="No bonus",
            )
        )
    return hand


def test_game_initialization_sets_expected_default_values(card_factory) -> None:
    """A new game should start with the expected resources and counters."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=2,
    )

    assert state.current_round == 1
    assert state.starting_initiative_player_id in {1, 2}
    assert state.initiative_player_id == state.starting_initiative_player_id
    assert state.status is GameStatus.IN_PROGRESS
    assert state.winner_id is None
    assert state.history == []
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS
    assert state.get_player(1).pills == 12
    assert len(state.get_player(1).available_cards()) == 4
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS
    assert state.get_player(2).pills == 12
    assert len(state.get_player(2).available_cards()) == 4


def test_game_initialization_can_force_player_1_to_start_and_alternates_initiative(card_factory) -> None:
    """Player 1 can be forced to start and initiative then alternates every round."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=1,
    )

    assert state.initiative_player_id == 1
    state.current_round = 2
    assert state.initiative_player_id == 2
    state.current_round = 3
    assert state.initiative_player_id == 1
    state.current_round = 4
    assert state.initiative_player_id == 2


def test_game_initialization_can_force_player_2_to_start_and_alternates_initiative(card_factory) -> None:
    """Player 2 can be forced to start and initiative then alternates every round."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=2,
    )

    assert state.initiative_player_id == 2
    state.current_round = 2
    assert state.initiative_player_id == 1
    state.current_round = 3
    assert state.initiative_player_id == 2
    state.current_round = 4
    assert state.initiative_player_id == 1


def test_game_initialization_randomizes_starting_player(card_factory, monkeypatch) -> None:
    """When no starting player is provided, the engine should draw one server-side."""
    monkeypatch.setattr("core.engine.secrets.choice", lambda choices: 2)
    engine = GameEngine()

    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=2,
    )

    assert state.starting_initiative_player_id == 2
    assert state.initiative_player_id == 2


def test_game_initialization_rejects_invalid_starting_player(card_factory) -> None:
    """Explicit invalid initiative seeds should be rejected instead of silently randomized."""
    engine = GameEngine()

    with pytest.raises(InvalidGameSetupError, match="Starting initiative player"):
        engine.create_game(
            _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
            _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
            starting_initiative_player_id=0,
        )


def test_compute_attack_uses_one_base_multiplier_plus_committed_pills(card_factory) -> None:
    """Attack should use card power multiplied by one plus committed pills."""
    card = card_factory("attacker", power=7, damage=4)

    assert compute_attack(card, 0) == 7
    assert compute_attack(card, 1) == 14
    assert compute_attack(card, 2) == 21


def test_play_round_applies_damage_and_consumes_pills(card_factory) -> None:
    """The winning card should deal damage and both players should spend pills."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
    )

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c1", pills_committed=3),
        player_2_selection=RoundSelection(card_id="p2c1", pills_committed=2),
    )

    assert result.outcome is RoundOutcome.PLAYER_1_WINS
    assert result.winner_id == 1
    assert result.loser_id == 2
    assert result.player_1_attack == 28
    assert result.player_2_attack == 21
    assert result.player_1_pills_committed == 3
    assert result.player_2_pills_committed == 2
    assert result.damage_dealt == 4
    assert state.get_player(1).pills == 9
    assert state.get_player(2).pills == 10
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS - 4
    assert "p1c1" in state.get_player(1).played_card_ids
    assert "p2c1" in state.get_player(2).played_card_ids
    assert state.current_round == 2
    assert len(state.history) == 1


def test_round_selection_defaults_to_no_overload() -> None:
    """Legacy round selections should keep working without specifying Overload."""
    selection = RoundSelection(card_id="card", pills_committed=3)

    assert selection.overload is False


def test_overload_consumes_extra_pills_without_changing_attack(card_factory) -> None:
    """Overload should cost two extra pills while keeping attack pills separate."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 5), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(1, 1), (6, 4), (4, 7), (8, 3)]),
    )

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c1", pills_committed=2, overload=True),
        player_2_selection=RoundSelection(card_id="p2c1", pills_committed=1),
    )

    assert result.player_1_attack == 21
    assert result.damage_dealt == 8
    assert result.overload_damage_bonus == 3
    assert result.player_1_overload is True
    assert result.player_2_overload is False
    assert state.get_player(1).pills == 8
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS - 8


def test_overload_does_not_add_damage_when_overloaded_card_loses(card_factory) -> None:
    """The Overload damage bonus should not apply when the overloaded card loses."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(5, 5), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(9, 2), (6, 4), (4, 7), (8, 3)]),
    )

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c1", pills_committed=2, overload=True),
        player_2_selection=RoundSelection(card_id="p2c1", pills_committed=2),
    )

    assert result.outcome is RoundOutcome.PLAYER_2_WINS
    assert result.damage_dealt == 2
    assert result.overload_damage_bonus == 0
    assert result.player_1_overload is True
    assert state.get_player(1).pills == 8
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS - 2


def test_overload_does_not_add_damage_when_attack_tie_is_lost_by_non_initiative(card_factory) -> None:
    """An attack tie should be won by initiative, so the non-initiative Overload still loses."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(5, 5), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(5, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=2,
    )

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c1", pills_committed=2, overload=True),
        player_2_selection=RoundSelection(card_id="p2c1", pills_committed=2),
    )

    assert result.outcome is RoundOutcome.PLAYER_2_WINS
    assert result.winner_id == 2
    assert result.damage_dealt == 2
    assert result.overload_damage_bonus == 0
    assert state.get_player(1).pills == 8
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS - 2


def test_overload_rejects_total_cost_above_available_pills(card_factory) -> None:
    """Validation should include Overload's extra cost without changing pills_committed."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 5), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(1, 1), (6, 4), (4, 7), (8, 3)]),
    )
    state.get_player(1).pills = 5

    with pytest.raises(NotEnoughPillsError, match="enough pills"):
        engine.play_round(
            state=state,
            player_1_selection=RoundSelection(card_id="p1c1", pills_committed=4, overload=True),
            player_2_selection=RoundSelection(card_id="p2c1", pills_committed=1),
        )


def test_play_round_rejects_reusing_a_card(card_factory) -> None:
    """A player should not be able to play the same card twice."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
    )

    engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c1", pills_committed=1),
        player_2_selection=RoundSelection(card_id="p2c1", pills_committed=1),
    )

    with pytest.raises(CardAlreadyPlayedError, match="already been played"):
        engine.play_round(
            state=state,
            player_1_selection=RoundSelection(card_id="p1c1", pills_committed=1),
            player_2_selection=RoundSelection(card_id="p2c2", pills_committed=1),
        )


def test_play_round_rejects_spending_more_pills_than_available(card_factory) -> None:
    """A player should not be able to spend more pills than available."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
    )

    with pytest.raises(NotEnoughPillsError, match="enough pills"):
        engine.play_round(
            state=state,
            player_1_selection=RoundSelection(card_id="p1c1", pills_committed=13),
            player_2_selection=RoundSelection(card_id="p2c1", pills_committed=1),
        )


def test_play_round_awards_equal_attack_to_initiative_player(card_factory) -> None:
    """Equal attacks should be broken by the player who had initiative."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=1,
    )

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c2", pills_committed=2),
        player_2_selection=RoundSelection(card_id="p2c2", pills_committed=2),
    )

    assert result.outcome is RoundOutcome.PLAYER_1_WINS
    assert result.winner_id == 1
    assert result.loser_id == 2
    assert result.damage_dealt == 5
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS - 5
    assert state.get_player(1).pills == 10
    assert state.get_player(2).pills == 10
    assert state.current_round == 2


def test_play_round_awards_equal_attack_to_player_2_when_player_2_has_initiative(card_factory) -> None:
    """The initiative tie-breaker should work for either starting player."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=2,
    )

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="p1c2", pills_committed=2),
        player_2_selection=RoundSelection(card_id="p2c2", pills_committed=2),
    )

    assert result.outcome is RoundOutcome.PLAYER_2_WINS
    assert result.winner_id == 2
    assert result.loser_id == 1
    assert result.damage_dealt == 4
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS - 4
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS


def test_play_round_stops_immediately_when_a_player_reaches_zero_hit_points(card_factory) -> None:
    """A knockout should end the match as soon as it happens."""
    engine = GameEngine()
    player_1_hand = [
        card_factory("finisher", power=9, damage=25),
        card_factory("p1c2"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory("p2c1", power=1, damage=1),
        card_factory("p2c2", power=1, damage=1),
        card_factory("p2c3", power=1, damage=1),
        card_factory("p2c4", power=1, damage=1),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection(card_id="finisher", pills_committed=3),
        player_2_selection=RoundSelection(card_id="p2c1", pills_committed=1),
    )

    assert result.winner_id == 1
    assert state.get_player(2).hit_points == 0
    assert state.status is GameStatus.PLAYER_1_WON
    assert state.winner_id == 1
    assert state.is_over is True
    assert state.current_round == 1

    with pytest.raises(GameAlreadyFinishedError, match="match is over"):
        engine.play_round(
            state=state,
            player_1_selection=RoundSelection(card_id="p1c2", pills_committed=1),
            player_2_selection=RoundSelection(card_id="p2c2", pills_committed=1),
        )


def test_game_uses_score_to_pick_the_winner_after_four_rounds(card_factory) -> None:
    """After four rounds without knockout, the highest remaining hit points should win."""
    engine = GameEngine()
    player_1_hand = _simple_hand(card_factory, "p1c", [(7, 4), (6, 3), (4, 1), (8, 2)])
    player_2_hand = _simple_hand(card_factory, "p2c", [(5, 2), (5, 2), (7, 1), (3, 1)])
    state = engine.create_game(player_1_hand, player_2_hand)

    engine.play_round(state=state, player_1_selection=RoundSelection("p1c1", 2), player_2_selection=RoundSelection("p2c1", 2))
    engine.play_round(state=state, player_1_selection=RoundSelection("p1c2", 1), player_2_selection=RoundSelection("p2c2", 2))
    engine.play_round(state=state, player_1_selection=RoundSelection("p1c3", 1), player_2_selection=RoundSelection("p2c3", 1))
    result = engine.play_round(state=state, player_1_selection=RoundSelection("p1c4", 3), player_2_selection=RoundSelection("p2c4", 1))

    assert result.round_number == 4
    assert state.status is GameStatus.PLAYER_1_WON
    assert state.winner_id == 1
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS - 3
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS - 6
    assert state.current_round == 4
    assert len(state.history) == 4


def test_complete_match_keeps_history_resources_and_played_cards_consistent(card_factory) -> None:
    """A full match should preserve all key invariants from start to finish."""
    engine = GameEngine()
    state = engine.create_game(
        _simple_hand(card_factory, "p1c", [(7, 4), (6, 5), (8, 3), (5, 6)]),
        _simple_hand(card_factory, "p2c", [(7, 2), (6, 4), (4, 7), (8, 3)]),
        starting_initiative_player_id=2,
    )

    scripted_rounds = [
        (RoundSelection("p1c1", 3), RoundSelection("p2c1", 2)),
        (RoundSelection("p1c2", 2), RoundSelection("p2c2", 2)),
        (RoundSelection("p1c3", 4), RoundSelection("p2c3", 1)),
        (RoundSelection("p1c4", 3), RoundSelection("p2c4", 3)),
    ]

    for player_1_selection, player_2_selection in scripted_rounds:
        engine.play_round(state=state, player_1_selection=player_1_selection, player_2_selection=player_2_selection)

    assert state.is_over is True
    assert state.status is GameStatus.PLAYER_1_WON
    assert state.winner_id == 1
    assert len(state.history) == 4
    assert [round_result.round_number for round_result in state.history] == [1, 2, 3, 4]
    assert state.get_player(1).pills == 0
    assert state.get_player(2).pills == 4
    assert state.get_player(1).hit_points == STARTING_HIT_POINTS - 3
    assert state.get_player(2).hit_points == STARTING_HIT_POINTS - 12
    assert state.get_player(1).played_card_ids == {"p1c1", "p1c2", "p1c3", "p1c4"}
    assert state.get_player(2).played_card_ids == {"p2c1", "p2c2", "p2c3", "p2c4"}
    assert state.get_player(1).available_cards() == []
    assert state.get_player(2).available_cards() == []
