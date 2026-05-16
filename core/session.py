"""Application-level match session for buffered player submissions."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.engine import GameEngine
from core.errors import GameAlreadyFinishedError, InvalidMoveError, RoundSynchronizationError, SelectionAlreadySubmittedError
from core.models import GameState, RoundResult, RoundSelection
from core.rules import validate_round_selection
from core.views import build_game_snapshot


@dataclass(slots=True)
class MatchSession:
    """Server-friendly wrapper around a game state and pending round selections."""

    engine: GameEngine
    state: GameState
    pending_selections: dict[int, RoundSelection] = field(default_factory=dict)

    def submit_selection(
        self,
        player_id: int,
        selection: RoundSelection,
        *,
        round_number: int | None = None,
    ) -> RoundResult | None:
        """Store one player selection and resolve the round when both are present."""
        if self.state.is_over:
            raise GameAlreadyFinishedError("Cannot submit a selection after the match is over.")

        if round_number is not None and round_number != self.state.current_round:
            raise RoundSynchronizationError(
                f"Selection targets round {round_number}, but current round is {self.state.current_round}."
            )

        if player_id not in {1, 2}:
            raise InvalidMoveError(f"Unknown player id: {player_id}.")

        if player_id in self.pending_selections:
            raise SelectionAlreadySubmittedError(
                f"Player {player_id} has already submitted a selection for round {self.state.current_round}."
            )

        player = self.state.get_player(player_id)
        validate_round_selection(player, selection)
        self.pending_selections[player_id] = selection

        if set(self.pending_selections) != {1, 2}:
            return None

        result = self.engine.play_round(
            state=self.state,
            player_1_selection=self.pending_selections[1],
            player_2_selection=self.pending_selections[2],
        )
        self.pending_selections.clear()
        return result

    def pending_player_ids(self) -> tuple[int, ...]:
        """Return the players who already submitted a selection this round."""
        return tuple(sorted(self.pending_selections))

    def build_snapshot(self, *, perspective_player_id: int | None = None) -> dict[str, object]:
        """Return a serializable session snapshot for a given player perspective."""
        return build_game_snapshot(
            self.state,
            perspective_player_id=perspective_player_id,
            pending_player_ids=self.pending_player_ids(),
        )
