"""Tests for the isolated Urban 2 roster loader."""

from collections import Counter
from pathlib import Path

from data.card_repository import load_card_set
from data.urban2_loader import load_urban2_roster, slugify


def test_slugify_keeps_display_names_separate_from_ids() -> None:
    """Technical ids should be stable ASCII while UI names keep their accents."""
    assert slugify("P'tit Kraken") == "ptit_kraken"
    assert slugify("P’tit Kraken") == "ptit_kraken"
    assert slugify("Corsaires du Port") == "corsaires_du_port"
    assert slugify("Égoutiers") == "egoutiers"


def test_load_urban2_roster_builds_cards_and_clans() -> None:
    """The new source JSON should load without touching the old runtime catalog."""
    project_root = Path(__file__).resolve().parents[1]
    roster = load_urban2_roster(project_root / "assets" / "data" / "urban2_personnages_base.json")

    assert roster.set_id == "urban2_personnages_base"
    assert len(roster.clans) == 5
    assert len(roster.cards) == 50
    assert Counter(card.clan for card in roster.cards) == {
        "Solaïres": 10,
        "Corsaires du Port": 10,
        "Palmeros": 10,
        "Égoutiers": 10,
        "Jardiniers de Béton": 10,
    }
    assert all(card.id != card.name for card in roster.cards)
    assert any(card.name == "Naya Brûle-Ciel" and card.id == "naya_brule_ciel" for card in roster.cards)


def test_card_repository_accepts_urban2_source_shape() -> None:
    """The shared card repository should convert Urban 2 JSON into normal Card objects."""
    project_root = Path(__file__).resolve().parents[1]
    card_set = load_card_set(project_root / "assets" / "data" / "urban2_personnages_base.json")

    assert card_set.name == "Urban 2 Personnages Base"
    assert len(card_set.cards) == 50
    assert all(card.power_text for card in card_set.cards)
    assert all(card.bonus_text for card in card_set.cards)
    assert all(card.illustration.startswith("assets/cards/urban2/") for card in card_set.cards)


def test_urban2_clan_bonuses_map_to_supported_effects() -> None:
    """The five new clan bonuses should stay simple and data-driven."""
    project_root = Path(__file__).resolve().parents[1]
    card_set = load_card_set(project_root / "assets" / "data" / "urban2_personnages_base.json")
    signatures_by_clan = {
        card.clan: tuple(
            (effect.trigger, effect.target, effect.effect_type, effect.value, effect.minimum)
            for effect in card.bonus_effects
        )
        for card in card_set.cards
    }

    assert signatures_by_clan == {
        "Solaïres": (("passive", "self", "power_modifier", 2, None),),
        "Corsaires du Port": (("victory", "opponent", "pill_steal", 1, None),),
        "Palmeros": (("passive", "opponent", "damage_modifier", -2, 1),),
        "Égoutiers": (("victory", "opponent", "poison", 2, 4),),
        "Jardiniers de Béton": (("victory", "self", "regeneration", 2, None),),
    }


def test_urban2_generated_illustrations_exist() -> None:
    """Every loaded Urban 2 card should point to a generated individual image."""
    project_root = Path(__file__).resolve().parents[1]
    roster = load_urban2_roster(project_root / "assets" / "data" / "urban2_personnages_base.json")

    for card in roster.cards:
        assert (project_root / card.illustration).exists()
