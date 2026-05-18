"""Game engine and round resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets

from core.effects import apply_round_aftermath, compute_active_clans, resolve_round_effects
from core.enums import GameStatus, RoundOutcome
from core.errors import GameAlreadyFinishedError
from core.models import Card, GameState, PlayerState, RoundResult, RoundSelection
from core.rules import (
    MAX_ROUNDS,
    OVERLOAD_DAMAGE_BONUS,
    OVERLOAD_PILL_COST,
    STARTING_HIT_POINTS,
    STARTING_PILLS,
    validate_game_state,
    validate_hand,
    validate_round_selection,
)
from core.savegame import (
    deserialize_game_state,
    load_game_state,
    save_game_state,
    serialize_game_state,
)


@dataclass(slots=True)
class _RoundComputation:
    """Store computed values for one round resolution."""

    player_1_card: Card
    player_2_card: Card
    player_1_attack: int
    player_2_attack: int
    outcome: RoundOutcome
    winner_id: int | None
    loser_id: int | None
    damage_dealt: int
    player_1_pills_committed: int = 0
    player_2_pills_committed: int = 0
    life_swing_player_1: int = 0
    life_swing_player_2: int = 0
    pills_gained_player_1: int = 0
    pills_gained_player_2: int = 0
    player_1_overload: bool = False
    player_2_overload: bool = False
    overload_damage_bonus: int = 0


class GameEngine:
    """Resolve rounds and update the game state."""

    def create_game(
        self,
        player_1_hand: list[Card],
        player_2_hand: list[Card],
        *,
        starting_initiative_player_id: int | None = None,
    ) -> GameState:
        """Create a fresh game state for two players."""
        validate_hand(player_1_hand)
        validate_hand(player_2_hand)
        if starting_initiative_player_id is None:
            starting_initiative_player_id = secrets.choice((1, 2))

        players = {
            1: PlayerState(
                player_id=1,
                hit_points=STARTING_HIT_POINTS,
                pills=STARTING_PILLS,
                hand=list(player_1_hand),
                active_clan_bonuses=compute_active_clans(player_1_hand),
            ),
            2: PlayerState(
                player_id=2,
                hit_points=STARTING_HIT_POINTS,
                pills=STARTING_PILLS,
                hand=list(player_2_hand),
                active_clan_bonuses=compute_active_clans(player_2_hand),
            ),
        }
        return GameState(players=players, starting_initiative_player_id=starting_initiative_player_id)

    def export_state(self, state: GameState) -> dict[str, object]:
        """Return a JSON-serializable snapshot of the current game state."""
        return serialize_game_state(state)

    def import_state(self, payload: object) -> GameState:
        """Restore a game state from a JSON-decoded payload."""
        return deserialize_game_state(payload)

    def save_state(self, state: GameState, path: str | Path) -> None:
        """Write a game state to a JSON save file."""
        save_game_state(state, path)

    def load_state(self, path: str | Path) -> GameState:
        """Load a game state from a JSON save file."""
        return load_game_state(path)

    def play_round(
        self,
        state: GameState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> RoundResult:
        """Resolve one round and mutate the game state."""
        self._validate_round_request(state)
        player_1, player_2 = self._get_players(state)
        self._validate_selections(player_1, player_2, player_1_selection, player_2_selection)

        round_computation = self._compute_round(
            state=state,
            player_1=player_1,
            player_2=player_2,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
        )
        self._apply_overload_damage_bonus(
            round_computation=round_computation,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
        )

        self._consume_round_resources(
            player_1=player_1,
            player_2=player_2,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
            round_computation=round_computation,
        )
        self._apply_round_damage(player_1, player_2, round_computation)
        round_computation = self._apply_post_round_effects(
            state,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
            round_computation=round_computation,
        )

        result = self._build_round_result(state.current_round, round_computation)
        state.history.append(result)
        self._advance_match_state(state, player_1, player_2)
        return result

    def determine_winner(self, state: GameState) -> int | None:
        """Return the winner identifier, or None for a draw/in-progress game."""
        if state.status is GameStatus.PLAYER_1_WON:
            return 1

        if state.status is GameStatus.PLAYER_2_WON:
            return 2

        return None

    def _finalize_match(self, state: GameState) -> None:
        """Finalize a match after the last round."""
        player_1 = state.get_player(1)
        player_2 = state.get_player(2)

        if player_1.hit_points > player_2.hit_points:
            state.status = GameStatus.PLAYER_1_WON
            state.winner_id = 1
        elif player_2.hit_points > player_1.hit_points:
            state.status = GameStatus.PLAYER_2_WON
            state.winner_id = 2
        else:
            state.status = GameStatus.DRAW
            state.winner_id = None

    def _validate_round_request(self, state: GameState) -> None:
        """Ensure the match can accept a new round."""
        if state.is_over:
            raise GameAlreadyFinishedError("Cannot play a round after the match is over.")

        validate_game_state(state)

    def _get_players(self, state: GameState) -> tuple[PlayerState, PlayerState]:
        """Return the ordered player states used by the engine."""
        return state.get_player(1), state.get_player(2)

    def _validate_selections(
        self,
        player_1: PlayerState,
        player_2: PlayerState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> None:
        """Validate both player selections before applying them."""
        validate_round_selection(player_1, player_1_selection)
        validate_round_selection(player_2, player_2_selection)

    def _compute_round(
        self,
        *,
        state: GameState,
        player_1: PlayerState,
        player_2: PlayerState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> _RoundComputation:
        """Compute the round outcome without mutating the game state."""
        player_1_card = player_1.get_card(player_1_selection.card_id)
        player_2_card = player_2.get_card(player_2_selection.card_id)
        effect_result = resolve_round_effects(
            state=state,
            player_1_card=player_1_card,
            player_2_card=player_2_card,
            player_1_pills=player_1_selection.pills_committed,
            player_2_pills=player_2_selection.pills_committed,
        )

        return _RoundComputation(
            player_1_card=player_1_card,
            player_2_card=player_2_card,
            player_1_attack=effect_result.player_1_attack,
            player_2_attack=effect_result.player_2_attack,
            outcome=effect_result.outcome,
            winner_id=effect_result.winner_id,
            loser_id=effect_result.loser_id,
            damage_dealt=effect_result.damage_dealt,
            player_1_pills_committed=player_1_selection.pills_committed,
            player_2_pills_committed=player_2_selection.pills_committed,
        )

    def _apply_overload_damage_bonus(
        self,
        *,
        round_computation: _RoundComputation,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> None:
        """Apply Overload's damage-only win bonus after normal attack resolution."""
        round_computation.player_1_overload = player_1_selection.overload
        round_computation.player_2_overload = player_2_selection.overload

        if round_computation.winner_id == 1 and player_1_selection.overload:
            round_computation.damage_dealt += OVERLOAD_DAMAGE_BONUS
            round_computation.overload_damage_bonus = OVERLOAD_DAMAGE_BONUS
        elif round_computation.winner_id == 2 and player_2_selection.overload:
            round_computation.damage_dealt += OVERLOAD_DAMAGE_BONUS
            round_computation.overload_damage_bonus = OVERLOAD_DAMAGE_BONUS

    def _consume_round_resources(
        self,
        *,
        player_1: PlayerState,
        player_2: PlayerState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
        round_computation: _RoundComputation,
    ) -> None:
        """Consume pills and mark both played cards."""
        player_1.pills -= self._selection_pill_cost(player_1_selection)
        player_2.pills -= self._selection_pill_cost(player_2_selection)
        player_1.played_card_ids.add(round_computation.player_1_card.id)
        player_2.played_card_ids.add(round_computation.player_2_card.id)

    def _selection_pill_cost(self, selection: RoundSelection) -> int:
        """Return total pills paid while keeping attack pills separate."""
        return selection.pills_committed + (OVERLOAD_PILL_COST if selection.overload else 0)

    def _apply_round_damage(
        self,
        player_1: PlayerState,
        player_2: PlayerState,
        round_computation: _RoundComputation,
    ) -> None:
        """Apply the computed damage to the losing player if needed."""
        if round_computation.winner_id == 1:
            player_2.hit_points = max(0, player_2.hit_points - round_computation.damage_dealt)
        elif round_computation.winner_id == 2:
            player_1.hit_points = max(0, player_1.hit_points - round_computation.damage_dealt)

    def _apply_post_round_effects(
        self,
        state: GameState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
        round_computation: _RoundComputation,
    ) -> _RoundComputation:
        """Apply post-fight effects and return the enriched round computation."""
        ledger = apply_round_aftermath(
            state,
            player_1_card=round_computation.player_1_card,
            player_2_card=round_computation.player_2_card,
            player_1_pills=player_1_selection.pills_committed,
            player_2_pills=player_2_selection.pills_committed,
            winner_id=round_computation.winner_id,
            loser_id=round_computation.loser_id,
        )
        round_computation.life_swing_player_1 = ledger.life_swing[1]
        round_computation.life_swing_player_2 = ledger.life_swing[2]
        round_computation.pills_gained_player_1 = ledger.pill_gain[1]
        round_computation.pills_gained_player_2 = ledger.pill_gain[2]
        return round_computation

    def _build_round_result(
        self,
        round_number: int,
        round_computation: _RoundComputation,
    ) -> RoundResult:
        """Create the immutable round result payload."""
        return RoundResult(
            round_number=round_number,
            player_1_card_id=round_computation.player_1_card.id,
            player_2_card_id=round_computation.player_2_card.id,
            player_1_attack=round_computation.player_1_attack,
            player_2_attack=round_computation.player_2_attack,
            outcome=round_computation.outcome,
            winner_id=round_computation.winner_id,
            loser_id=round_computation.loser_id,
            damage_dealt=round_computation.damage_dealt,
            player_1_pills_committed=round_computation.player_1_pills_committed,
            player_2_pills_committed=round_computation.player_2_pills_committed,
            life_swing_player_1=round_computation.life_swing_player_1,
            life_swing_player_2=round_computation.life_swing_player_2,
            pills_gained_player_1=round_computation.pills_gained_player_1,
            pills_gained_player_2=round_computation.pills_gained_player_2,
            player_1_overload=round_computation.player_1_overload,
            player_2_overload=round_computation.player_2_overload,
            overload_damage_bonus=round_computation.overload_damage_bonus,
        )

    def _advance_match_state(
        self,
        state: GameState,
        player_1: PlayerState,
        player_2: PlayerState,
    ) -> None:
        """Advance the game to the next round or finalize the match."""
        if player_1.hit_points == 0:
            state.status = GameStatus.PLAYER_2_WON
            state.winner_id = 2
        elif player_2.hit_points == 0:
            state.status = GameStatus.PLAYER_1_WON
            state.winner_id = 1
        elif state.current_round >= MAX_ROUNDS:
            self._finalize_match(state)
        else:
            state.current_round += 1
