"""Protocols used to decouple engine, UI, and AI."""

from __future__ import annotations

from typing import Protocol

from core.models import GameState, PlayerState, RoundResult, RoundSelection


class ChoiceProvider(Protocol):
    """Provide a round choice for a player."""

    def choose_action(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Return the choice for the current round."""


class MatchObserver(Protocol):
    """Observe match lifecycle events."""

    def on_match_started(self, state: GameState) -> None:
        """React to match start."""

    def on_round_resolved(self, state: GameState, result: RoundResult) -> None:
        """React to a resolved round."""

    def on_match_finished(self, state: GameState) -> None:
        """React to match end."""


class NullMatchObserver:
    """Default observer that does nothing."""

    def on_match_started(self, state: GameState) -> None:
        """Ignore match start."""

    def on_round_resolved(self, state: GameState, result: RoundResult) -> None:
        """Ignore round resolution."""

    def on_match_finished(self, state: GameState) -> None:
        """Ignore match end."""
