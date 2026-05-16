"""Application services orchestrating a full match."""

from collections.abc import Mapping

from core.engine import GameEngine
from core.interfaces import ChoiceProvider, MatchObserver, NullMatchObserver
from core.models import GameState


class MatchService:
    """Run a full match using pluggable choice providers."""

    def __init__(self, engine: GameEngine) -> None:
        """Store the engine dependency."""
        self.engine = engine

    def play_match(
        self,
        state: GameState,
        providers: Mapping[int, ChoiceProvider],
        observer: MatchObserver | None = None,
    ) -> GameState:
        """Play rounds until the match finishes."""
        active_observer = observer or NullMatchObserver()
        active_observer.on_match_started(state)

        while not state.is_over:
            player_1 = state.get_player(1)
            player_2 = state.get_player(2)

            player_1_selection = providers[1].choose_action(state, player_1)
            player_2_selection = providers[2].choose_action(state, player_2)

            result = self.engine.play_round(
                state=state,
                player_1_selection=player_1_selection,
                player_2_selection=player_2_selection,
            )
            active_observer.on_round_resolved(state, result)

        active_observer.on_match_finished(state)
        return state
