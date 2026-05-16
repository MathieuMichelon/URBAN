"""Enumerations used by the game engine."""

from enum import Enum


class GameStatus(str, Enum):
    """Represent the global state of a match."""

    IN_PROGRESS = "in_progress"
    PLAYER_1_WON = "player_1_won"
    PLAYER_2_WON = "player_2_won"
    DRAW = "draw"


class RoundOutcome(str, Enum):
    """Represent the outcome of a single round."""

    PLAYER_1_WINS = "player_1_wins"
    PLAYER_2_WINS = "player_2_wins"
    TIE = "tie"
