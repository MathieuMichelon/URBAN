"""Base classes for AI choice providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Card, GameState, PlayerState, RoundSelection


class BaseAIChoiceProvider(ABC):
    """Base class for AI-controlled players."""

    @abstractmethod
    def choose_action(self, game_state: GameState, player: PlayerState) -> RoundSelection:
        """Return the action selected by the AI."""

        raise NotImplementedError

    def choose_team(self, offered_cards: list[Card]) -> list[Card]:
        """Return a drafted team from the shared offer."""
        raise NotImplementedError

    # TODO: Add helper hooks for heuristics and simulation-based decisions.
