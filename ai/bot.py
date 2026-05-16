"""Bot strategies for the player-vs-AI mode."""

from __future__ import annotations

from abc import ABC, abstractmethod
from itertools import combinations
from math import ceil
import random

from ai.base import BaseAIChoiceProvider
from core.draft import TEAM_SIZE, TEAM_STAR_CAP, resolve_team_from_ids
from core.models import Card, EffectDefinition, GameState, PlayerState, RoundSelection
from core.rules import MAX_ROUNDS, compute_attack


class BotStrategy(ABC):
    """Strategy interface for AI decision making."""

    @abstractmethod
    def choose_selection(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Return a legal round selection for the current state."""


class RandomStrategy(BotStrategy):
    """Pseudo-random strategy used mainly for fallback or testing."""

    def __init__(self, seed: int | None = None) -> None:
        """Create a deterministic random generator when a seed is provided."""
        self._random = random.Random(seed)

    def choose_selection(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Pick any legal card and any legal pill count."""
        available_cards = player.available_cards()
        selected_card = self._random.choice(available_cards)
        pills = self._random.randint(0, player.pills)
        return RoundSelection(card_id=selected_card.id, pills_committed=pills)


class HeuristicStrategy(BotStrategy):
    """Simple non-cheating heuristic that favors sensible legal plays."""

    def choose_selection(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Choose a card and pills from public information plus the AI hand."""
        available_cards = player.available_cards()
        opponent = game_state.get_opponent(player.player_id)

        best_candidate: tuple[float, int, int, int, str, RoundSelection] | None = None
        for card in available_cards:
            for pills in self._candidate_pill_counts(game_state, player, opponent, card):
                selection = RoundSelection(card_id=card.id, pills_committed=pills)
                score = self._score_selection(game_state, player, opponent, card, pills)
                candidate = (
                    score,
                    compute_attack(card, pills),
                    card.damage,
                    -pills,
                    card.id,
                    selection,
                )
                if best_candidate is None or candidate > best_candidate:
                    best_candidate = candidate

        if best_candidate is None:
            raise ValueError("HeuristicStrategy could not find a legal move.")

        return best_candidate[-1]

    def _candidate_pill_counts(
        self,
        game_state: GameState,
        player: PlayerState,
        opponent: PlayerState,
        card: Card,
    ) -> list[int]:
        """Return a compact set of useful pill counts to evaluate."""
        if player.pills == 0:
            return [0]

        remaining_turns = len(player.available_cards())
        baseline = max(1, ceil(player.pills / max(1, remaining_turns)))
        opponent_baseline = 0
        if opponent.pills > 0:
            opponent_baseline = max(1, ceil(opponent.pills / max(1, len(opponent.available_cards()))))

        safe_max = self._safe_max_commit(game_state, player, opponent)
        lethal_push = min(player.pills, max(1, baseline + 1))

        candidate_values = {
            0,
            1,
            min(player.pills, baseline),
            min(player.pills, baseline + 1),
            min(player.pills, opponent_baseline),
            min(player.pills, opponent_baseline + 1),
            safe_max,
            lethal_push,
        }

        if len(player.available_cards()) == 1 or game_state.current_round == MAX_ROUNDS:
            candidate_values.add(player.pills)

        if card.damage >= opponent.hit_points:
            candidate_values.add(min(player.pills, max(1, baseline + 1)))

        return sorted(value for value in candidate_values if 0 <= value <= player.pills)

    def _safe_max_commit(
        self,
        game_state: GameState,
        player: PlayerState,
        opponent: PlayerState,
    ) -> int:
        """Return a conservative upper bound for pills in the current round."""
        remaining_turns = len(player.available_cards())
        future_turns = max(0, remaining_turns - 1)

        if future_turns == 0 or game_state.current_round == MAX_ROUNDS:
            return player.pills

        baseline = max(1, ceil(player.pills / remaining_turns))
        reserve = min(player.pills, future_turns)
        safe_max = min(player.pills - reserve, baseline + 2)
        safe_max = max(1, safe_max)

        if player.hit_points < opponent.hit_points:
            safe_max = min(player.pills, safe_max + 1)

        return safe_max

    def _score_selection(
        self,
        game_state: GameState,
        player: PlayerState,
        opponent: PlayerState,
        card: Card,
        pills: int,
    ) -> float:
        """Score one candidate move with a lightweight heuristic."""
        attack = compute_attack(card, pills)
        remaining_turns = len(player.available_cards())
        safe_max = self._safe_max_commit(game_state, player, opponent)
        hp_gap = opponent.hit_points - player.hit_points

        score = 0.0
        score += card.damage * 30
        score += attack * 2.8
        score += card.power * 6

        if pills == 0 and player.pills > 0:
            score -= 140

        if pills > safe_max and game_state.current_round < MAX_ROUNDS:
            score -= (pills - safe_max) * 40

        if hp_gap > 0:
            score += pills * 6
            score += card.damage * 8
        elif hp_gap < 0:
            score -= pills * 2.5

        if game_state.current_round == MAX_ROUNDS:
            score += pills * 12

        if remaining_turns > 2:
            score -= pills * 3

        if card.damage >= opponent.hit_points and pills > 0:
            score += 260

        return score


class ScriptedStrategy(BotStrategy):
    """Deterministic strategy for fixtures and solo regression checks."""

    def __init__(self, selections: list[RoundSelection]) -> None:
        """Store a fixed list of round selections."""
        self._selections = list(selections)
        self._cursor = 0

    def choose_selection(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Return the next scripted selection."""
        if self._cursor >= len(self._selections):
            raise ValueError("ScriptedStrategy ran out of round selections.")

        selection = self._selections[self._cursor]
        self._cursor += 1
        return selection


class AIBot(BaseAIChoiceProvider):
    """AI provider that delegates its choice to a pluggable strategy."""

    def __init__(self, strategy: BotStrategy | None = None) -> None:
        """Create a bot with a default heuristic strategy."""
        self.strategy = strategy or HeuristicStrategy()

    def choose_action(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Return the strategy decision."""
        return self.strategy.choose_selection(game_state, player)

    def choose_team(self, offered_cards: list[Card]) -> list[Card]:
        """Draft a legal 4-card team under the shared 8-star cap."""
        best_team: tuple[float, tuple[str, ...], list[Card]] | None = None

        for team_tuple in combinations(offered_cards, TEAM_SIZE):
            team = list(team_tuple)
            total_stars = sum(card.stars for card in team)
            if total_stars > TEAM_STAR_CAP:
                continue

            score = sum(self._draft_card_score(card) for card in team)
            candidate = (score, tuple(sorted(card.id for card in team)), team)
            if best_team is None or candidate > best_team:
                best_team = candidate

        if best_team is None:
            raise ValueError("AI could not draft a legal team from the offer.")

        return best_team[-1]

    def _draft_card_score(self, card: Card) -> float:
        """Estimate a card's draft value using its raw stats and effect pressure."""
        effect_weight = sum(self._effect_value(effect) for effect in (*card.power_effects, *card.bonus_effects))
        return (card.power * 2.8) + (card.damage * 4.2) + effect_weight - (card.stars * 1.1)

    def _effect_value(self, effect: EffectDefinition) -> float:
        """Assign a coarse value to a data-driven effect for drafting."""
        weights = {
            "attack_modifier": 0.35,
            "power_modifier": 1.2,
            "damage_modifier": 1.6,
            "life_gain": 1.3,
            "life_loss": 1.4,
            "poison": 1.5,
            "pill_gain": 1.1,
            "stop_opponent_power": 2.6,
            "stop_opponent_bonus": 1.9,
            "protection_bonus": 1.3,
            "protection_power": 1.6,
        }
        weight = weights.get(effect.effect_type, 0.5)
        return max(0.0, weight * max(1, effect.value or 1))


class HeuristicAIChoiceProvider(AIBot):
    """Convenience provider using the default heuristic strategy."""

    def __init__(self) -> None:
        """Initialize the heuristic AI."""
        super().__init__(strategy=HeuristicStrategy())


class ScriptedAIChoiceProvider(AIBot):
    """Deterministic AI provider for solo fixtures and regression tests."""

    def __init__(
        self,
        selections: list[RoundSelection],
        *,
        team_card_ids: list[str] | None = None,
    ) -> None:
        """Store scripted round decisions and an optional scripted drafted team."""
        super().__init__(strategy=ScriptedStrategy(selections))
        self._team_card_ids = list(team_card_ids) if team_card_ids is not None else None

    def choose_team(self, offered_cards: list[Card]) -> list[Card]:
        """Return the scripted team when provided, otherwise fall back to default drafting."""
        if self._team_card_ids is None:
            return super().choose_team(offered_cards)
        return resolve_team_from_ids(offered_cards, self._team_card_ids)
