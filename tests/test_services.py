"""Unit tests for match orchestration."""

from core.engine import GameEngine
from core.enums import GameStatus
from core.models import GameState, PlayerState, RoundSelection
from core.services import MatchService


class ScriptedProvider:
    """Return pre-defined choices in sequence."""

    def __init__(self, choices: list[RoundSelection]) -> None:
        """Store the scripted decisions."""
        self._choices = choices
        self._index = 0

    def choose_action(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Return the next scripted action."""
        choice = self._choices[self._index]
        self._index += 1
        return choice


def test_match_service_runs_until_completion(card_factory) -> None:
    """The service should resolve rounds until the match ends."""
    engine = GameEngine()
    state = engine.create_game(
        [card_factory(f"p1c{index}", clan=f"A{index}") for index in range(1, 5)],
        [card_factory(f"p2c{index}", clan=f"B{index}") for index in range(1, 5)],
    )
    service = MatchService(engine)

    player_1_provider = ScriptedProvider(
        [
            RoundSelection("p1c1", 3),
            RoundSelection("p1c2", 3),
            RoundSelection("p1c3", 3),
            RoundSelection("p1c4", 3),
        ]
    )
    player_2_provider = ScriptedProvider(
        [
            RoundSelection("p2c1", 1),
            RoundSelection("p2c2", 1),
            RoundSelection("p2c3", 1),
            RoundSelection("p2c4", 1),
        ]
    )

    final_state = service.play_match(
        state=state,
        providers={1: player_1_provider, 2: player_2_provider},
    )

    assert final_state.is_over is True
    assert final_state.status in {GameStatus.PLAYER_1_WON, GameStatus.PLAYER_2_WON, GameStatus.DRAW}
    assert len(final_state.history) >= 1
