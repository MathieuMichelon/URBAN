"""Unit tests for core model creation and validation."""

import pytest

from core.errors import InvalidCardDefinitionError, InvalidGameSetupError
from core.models import Card, PlayerState


def test_card_creation_stores_expected_attributes() -> None:
    """A valid card should expose its declared data unchanged."""
    card = Card(
        id="blade",
        name="Blade",
        clan="Test Clan",
        stars=2,
        power=7,
        damage=4,
        power_text="No power",
        bonus_text="No bonus",
        illustration="assets/blade.png",
    )

    assert card.id == "blade"
    assert card.name == "Blade"
    assert card.clan == "Test Clan"
    assert card.stars == 2
    assert card.power == 7
    assert card.damage == 4
    assert card.illustration == "assets/blade.png"


def test_card_creation_rejects_invalid_power() -> None:
    """A card must have a strictly positive power value."""
    with pytest.raises(InvalidCardDefinitionError, match="power must be greater than 0"):
        Card(
            id="broken",
            name="Broken",
            clan="Test Clan",
            stars=1,
            power=0,
            damage=3,
            power_text="None",
            bonus_text="None",
            illustration="assets/broken.png",
        )


def test_player_creation_initializes_resources_and_available_cards(card_factory) -> None:
    """A valid player should start with the provided cards and resources."""
    hand = [
        card_factory("c1"),
        card_factory("c2"),
        card_factory("c3"),
        card_factory("c4"),
    ]

    player = PlayerState(player_id=1, hit_points=20, pills=12, hand=hand)

    assert player.player_id == 1
    assert player.hit_points == 20
    assert player.pills == 12
    assert player.available_cards() == hand
    assert player.played_card_ids == set()


def test_player_creation_rejects_duplicate_cards_in_hand(card_factory) -> None:
    """A player hand cannot contain duplicate card identifiers."""
    duplicate = card_factory("dup")

    with pytest.raises(InvalidGameSetupError, match="duplicate card ids"):
        PlayerState(
            player_id=1,
            hit_points=20,
            pills=12,
            hand=[duplicate, duplicate],
        )
