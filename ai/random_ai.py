"""Backward-compatible random AI implementation."""

from __future__ import annotations

from ai.bot import AIBot, RandomStrategy


class RandomAIChoiceProvider(AIBot):
    """Play a random available card with a random number of pills."""

    def __init__(self, seed: int | None = None) -> None:
        """Create a deterministic or non-deterministic RNG."""
        super().__init__(strategy=RandomStrategy(seed=seed))
