"""Centralized round resolution pipeline for the authoritative core engine."""

from __future__ import annotations

from dataclasses import dataclass

from core.effects import apply_round_aftermath, compute_active_clans, resolve_round_effects
from core.enums import GameStatus
from core.errors import GameAlreadyFinishedError
from core.models import Card, GameState, PlayerState, RoundResult, RoundSelection
from core.rules import MAX_ROUNDS, validate_game_state, validate_round_selection

ROUND_RESOLUTION_PIPELINE = (
    "determine_team_bonuses_from_locked_teams",
    "apply_stop_power_and_stop_bonus_rules",
    "apply_protections",
    "apply_pre_fight_modifiers",
    "compute_final_attacks",
    "determine_round_outcome_with_initiative_tie_breaker",
    "apply_victory_and_defeat_effects",
    "apply_poison_and_end_of_round_effects",
    "persist_full_updated_state",
)


@dataclass(slots=True)
class _RoundComputation:
    """Store computed values for one round before final persistence."""

    player_1_card: Card
    player_2_card: Card
    player_1_attack: int
    player_2_attack: int
    winner_id: int | None
    loser_id: int | None
    damage_dealt: int
    outcome: str
    life_swing_player_1: int = 0
    life_swing_player_2: int = 0
    pills_gained_player_1: int = 0
    pills_gained_player_2: int = 0


class RoundResolutionPipeline:
    """Resolve a round through one explicit 9-step pipeline.

    The service owns the authoritative order:
    1. determine team bonuses from locked teams
    2. apply stop power / stop bonus rules
    3. apply protections
    4. apply pre-fight modifiers
    5. compute final attacks
    6. determine winner / loser, using initiative as the attack tie-breaker
    7. apply victory / defeat effects
    8. apply poison / end-of-round effects
    9. persist the full updated game state
    """

    pipeline_steps = ROUND_RESOLUTION_PIPELINE

    def resolve_and_persist(
        self,
        state: GameState,
        *,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> RoundResult:
        """Run the full round pipeline and mutate the official game state once."""
        self._validate_round_request(state)
        player_1, player_2 = state.get_player(1), state.get_player(2)
        self._validate_selections(player_1, player_2, player_1_selection, player_2_selection)
        self._synchronize_team_bonuses(state)

        round_computation = self._compute_round(
            state=state,
            player_1=player_1,
            player_2=player_2,
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
        self._apply_post_round_effects(
            state,
            player_1_selection=player_1_selection,
            player_2_selection=player_2_selection,
            round_computation=round_computation,
        )
        return self._persist_round_state(state, player_1, player_2, round_computation)

    def _validate_round_request(self, state: GameState) -> None:
        """Ensure the match can accept a new round."""
        if state.is_over:
            raise GameAlreadyFinishedError("Cannot play a round after the match is over.")
        validate_game_state(state)

    def _validate_selections(
        self,
        player_1: PlayerState,
        player_2: PlayerState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> None:
        """Validate both player selections before the pipeline mutates state."""
        validate_round_selection(player_1, player_1_selection)
        validate_round_selection(player_2, player_2_selection)

    def _synchronize_team_bonuses(self, state: GameState) -> None:
        """Refresh active clan bonuses from the locked 4-card teams before combat."""
        for player in state.players.values():
            player.active_clan_bonuses = compute_active_clans(player.hand)

    def _compute_round(
        self,
        *,
        state: GameState,
        player_1: PlayerState,
        player_2: PlayerState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
    ) -> _RoundComputation:
        """Resolve the pre-fight and winner-determination stages."""
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
            winner_id=effect_result.winner_id,
            loser_id=effect_result.loser_id,
            damage_dealt=effect_result.damage_dealt,
            outcome=effect_result.outcome,
        )

    def _consume_round_resources(
        self,
        *,
        player_1: PlayerState,
        player_2: PlayerState,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
        round_computation: _RoundComputation,
    ) -> None:
        """Consume pills and mark both cards as played before post-fight effects."""
        player_1.pills -= player_1_selection.pills_committed
        player_2.pills -= player_2_selection.pills_committed
        player_1.played_card_ids.add(round_computation.player_1_card.id)
        player_2.played_card_ids.add(round_computation.player_2_card.id)

    def _apply_round_damage(
        self,
        player_1: PlayerState,
        player_2: PlayerState,
        round_computation: _RoundComputation,
    ) -> None:
        """Apply the round damage before post-fight effects."""
        if round_computation.winner_id == 1:
            player_2.hit_points = max(0, player_2.hit_points - round_computation.damage_dealt)
        elif round_computation.winner_id == 2:
            player_1.hit_points = max(0, player_1.hit_points - round_computation.damage_dealt)

    def _apply_post_round_effects(
        self,
        state: GameState,
        *,
        player_1_selection: RoundSelection,
        player_2_selection: RoundSelection,
        round_computation: _RoundComputation,
    ) -> None:
        """Apply victory, defeat, and poison processing after damage."""
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

    def _persist_round_state(
        self,
        state: GameState,
        player_1: PlayerState,
        player_2: PlayerState,
        round_computation: _RoundComputation,
    ) -> RoundResult:
        """Persist history and advance the official match state."""
        result = RoundResult(
            round_number=state.current_round,
            player_1_card_id=round_computation.player_1_card.id,
            player_2_card_id=round_computation.player_2_card.id,
            player_1_attack=round_computation.player_1_attack,
            player_2_attack=round_computation.player_2_attack,
            outcome=round_computation.outcome,
            winner_id=round_computation.winner_id,
            loser_id=round_computation.loser_id,
            damage_dealt=round_computation.damage_dealt,
            life_swing_player_1=round_computation.life_swing_player_1,
            life_swing_player_2=round_computation.life_swing_player_2,
            pills_gained_player_1=round_computation.pills_gained_player_1,
            pills_gained_player_2=round_computation.pills_gained_player_2,
        )
        state.history.append(result)
        self._advance_match_state(state, player_1, player_2)
        return result

    def _advance_match_state(
        self,
        state: GameState,
        player_1: PlayerState,
        player_2: PlayerState,
    ) -> None:
        """Advance to the next round or finalize the match after persistence."""
        if player_1.hit_points == 0:
            state.status = GameStatus.PLAYER_2_WON
            state.winner_id = 2
            return
        if player_2.hit_points == 0:
            state.status = GameStatus.PLAYER_1_WON
            state.winner_id = 1
            return
        if state.current_round >= MAX_ROUNDS:
            self._finalize_match(state)
            return
        state.current_round += 1

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
