"""Shared pytest fixtures and small factories."""

from collections.abc import Callable
from pathlib import Path

import pytest

from core.models import Card, PlayerState
from core.rules import STARTING_HIT_POINTS, STARTING_PILLS
from data.card_repository import load_cards


@pytest.fixture()
def sample_cards() -> list[Card]:
    """Return the active Urban 2 roster used by the game."""
    project_root = Path(__file__).resolve().parents[1]
    return load_cards(project_root / "assets" / "data" / "urban2_personnages_base.json")


@pytest.fixture()
def card_factory() -> Callable[..., Card]:
    """Build cards with sensible defaults for tests."""

    def _build_card(
        card_id: str,
        *,
        name: str | None = None,
        clan: str = "Test Clan",
        stars: int = 2,
        power: int = 5,
        damage: int = 2,
        power_text: str = "No power",
        bonus_text: str = "No bonus",
        illustration: str = "assets/test.png",
        power_effects=(),
        bonus_effects=(),
    ) -> Card:
        return Card(
            id=card_id,
            name=name or card_id.title(),
            clan=clan,
            stars=stars,
            power=power,
            damage=damage,
            power_text=power_text,
            bonus_text=bonus_text,
            illustration=illustration,
            power_effects=power_effects,
            bonus_effects=bonus_effects,
        )

    return _build_card


@pytest.fixture()
def player_factory(card_factory: Callable[..., Card]) -> Callable[..., PlayerState]:
    """Build player states with sensible defaults for tests."""

    def _build_player(
        player_id: int,
        *,
        hit_points: int = STARTING_HIT_POINTS,
        pills: int = STARTING_PILLS,
        hand: list[Card] | None = None,
    ) -> PlayerState:
        cards = hand or [
            card_factory(f"p{player_id}c1"),
            card_factory(f"p{player_id}c2"),
            card_factory(f"p{player_id}c3"),
            card_factory(f"p{player_id}c4"),
        ]
        return PlayerState(
            player_id=player_id,
            hit_points=hit_points,
            pills=pills,
            hand=cards,
        )

    return _build_player
