"""Focused tests for AI strategies."""

from collections.abc import Callable
from itertools import combinations

from ai.bot import AIBot, HeuristicStrategy, RandomStrategy, ScriptedAIChoiceProvider
from core.engine import GameEngine
from core.models import Card, RoundSelection


def test_heuristic_strategy_returns_a_legal_selection(sample_cards: list[Card]) -> None:
    """The heuristic bot should always return a playable card and a valid pill count."""
    engine = GameEngine()
    state = engine.create_game(sample_cards[:4], sample_cards[4:8])
    ai_player = state.get_player(2)

    selection = HeuristicStrategy().choose_selection(state, ai_player)

    assert selection.card_id in {card.id for card in ai_player.available_cards()}
    assert 0 <= selection.pills_committed <= ai_player.pills


def test_heuristic_strategy_ignores_already_played_cards(sample_cards: list[Card]) -> None:
    """The heuristic bot should not reuse a card already marked as played."""
    engine = GameEngine()
    state = engine.create_game(sample_cards[:4], sample_cards[4:8])
    ai_player = state.get_player(2)
    already_played = {card.id for card in ai_player.hand[:3]}
    ai_player.played_card_ids.update(already_played)

    selection = HeuristicStrategy().choose_selection(state, ai_player)

    assert selection.card_id in {card.id for card in ai_player.available_cards()}
    assert selection.card_id not in already_played
    assert 0 <= selection.pills_committed <= ai_player.pills


def test_heuristic_strategy_avoids_zero_pill_opening_when_resources_are_available(
    card_factory: Callable[..., Card],
) -> None:
    """The heuristic bot should avoid obvious zero-pill openings."""
    engine = GameEngine()
    player_1_hand = [
        card_factory("p1c1", power=5, damage=2),
        card_factory("p1c2", power=5, damage=2),
        card_factory("p1c3", power=5, damage=2),
        card_factory("p1c4", power=5, damage=2),
    ]
    player_2_hand = [
        card_factory("p2c1", power=6, damage=3),
        card_factory("p2c2", power=7, damage=2),
        card_factory("p2c3", power=4, damage=5),
        card_factory("p2c4", power=5, damage=4),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    selection = HeuristicStrategy().choose_selection(state, state.get_player(2))

    assert selection.pills_committed >= 1


def test_heuristic_strategy_prefers_a_finishing_card_when_opponent_is_low_on_hp(
    card_factory: Callable[..., Card],
) -> None:
    """The heuristic bot should favor lethal damage opportunities."""
    engine = GameEngine()
    player_1_hand = [
        card_factory("p1c1", power=5, damage=2),
        card_factory("p1c2", power=5, damage=2),
        card_factory("p1c3", power=5, damage=2),
        card_factory("p1c4", power=5, damage=2),
    ]
    player_2_hand = [
        card_factory("safe", power=7, damage=2),
        card_factory("burst", power=6, damage=5),
        card_factory("tempo", power=8, damage=1),
        card_factory("guard", power=5, damage=3),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)
    state.get_player(1).hit_points = 4

    selection = HeuristicStrategy().choose_selection(state, state.get_player(2))

    assert selection.card_id == "burst"
    assert selection.pills_committed >= 1


def test_random_strategy_is_seeded_and_repeatable(sample_cards: list[Card]) -> None:
    """The random strategy should be reproducible when seeded."""
    engine = GameEngine()
    first_state = engine.create_game(sample_cards[:4], sample_cards[4:8])
    second_state = engine.create_game(sample_cards[:4], sample_cards[4:8])

    first = RandomStrategy(seed=7).choose_selection(first_state, first_state.get_player(2))
    second = RandomStrategy(seed=7).choose_selection(second_state, second_state.get_player(2))

    assert first == second


def test_ai_bot_provider_delegates_to_the_configured_strategy(
    sample_cards: list[Card],
) -> None:
    """The wrapper provider should delegate the decision to its strategy."""
    engine = GameEngine()
    state = engine.create_game(sample_cards[:4], sample_cards[4:8])
    scripted_card_id = state.get_player(2).hand[0].id
    scripted = _ScriptedStrategy(RoundSelection(scripted_card_id, 2))

    selection = AIBot(strategy=scripted).choose_action(state, state.get_player(2))

    assert scripted.calls == 1
    assert selection == RoundSelection(scripted_card_id, 2)


def test_scripted_ai_choice_provider_uses_scripted_team_and_rounds(
    sample_cards: list[Card],
) -> None:
    """The scripted provider should expose deterministic draft and round behavior."""
    engine = GameEngine()
    offered_cards = sample_cards[:10]
    scripted_team_ids = next(
        [card.id for card in team]
        for team in combinations(offered_cards, 4)
        if sum(card.stars for card in team) <= 8
    )
    scripted_rounds = [RoundSelection(scripted_team_ids[0], 2), RoundSelection(scripted_team_ids[1], 1)]
    provider = ScriptedAIChoiceProvider(scripted_rounds, team_card_ids=scripted_team_ids)

    drafted_team = provider.choose_team(offered_cards)
    state = engine.create_game(sample_cards[10:14], drafted_team)

    first = provider.choose_action(state, state.get_player(2))
    second = provider.choose_action(state, state.get_player(2))

    assert [card.id for card in drafted_team] == scripted_team_ids
    assert first == scripted_rounds[0]
    assert second == scripted_rounds[1]


class _ScriptedStrategy:
    """Tiny fake strategy for delegation tests."""

    def __init__(self, selection: RoundSelection) -> None:
        """Store the scripted selection."""
        self.selection = selection
        self.calls = 0

    def choose_selection(self, game_state, player) -> RoundSelection:
        """Return the pre-configured selection."""
        self.calls += 1
        return self.selection
