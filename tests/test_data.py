"""Unit tests for active card-set loading."""

from collections import Counter
from pathlib import Path

import pytest

from core.errors import CardSetFormatError, CardSetLoadError
from data.card_repository import load_card_set, load_cards


ACTIVE_URBAN2_PATH = Path(__file__).resolve().parents[1] / "assets" / "data" / "urban2_personnages_base.json"


def test_load_card_set_reads_active_urban2_roster_metadata() -> None:
    """The runtime roster should now come from the Urban 2 source file."""
    card_set = load_card_set(ACTIVE_URBAN2_PATH)

    assert card_set.set_id == "urban2_personnages_base"
    assert card_set.name == "Urban 2 Personnages Base"
    assert len(card_set.cards) == 50
    assert min(card.stars for card in card_set.cards) == 1
    assert max(card.stars for card in card_set.cards) == 3


def test_load_cards_returns_active_urban2_cards() -> None:
    """The convenience loader should resolve the active 50-card Urban 2 roster."""
    cards = load_cards(ACTIVE_URBAN2_PATH)

    assert len(cards) == 50
    assert all(card.power_text for card in cards)
    assert all(card.bonus_text for card in cards)
    assert all(card.illustration.startswith("assets/cards/urban2/") for card in cards)


def test_load_card_set_contains_five_clans_with_ten_cards_each() -> None:
    """The active roster should be evenly split across the five new clans."""
    card_set = load_card_set(ACTIVE_URBAN2_PATH)
    cards_per_clan = Counter(card.clan for card in card_set.cards)

    assert cards_per_clan == {
        "Solaïres": 10,
        "Corsaires du Port": 10,
        "Palmeros": 10,
        "Égoutiers": 10,
        "Jardiniers de Béton": 10,
    }


def test_load_card_set_keeps_clan_bonus_data_consistent_per_clan() -> None:
    """Each clan should resolve to one shared bonus definition across its cards."""
    card_set = load_card_set(ACTIVE_URBAN2_PATH)
    bonus_texts_by_clan: dict[str, set[str]] = {}
    bonus_effect_signatures_by_clan: dict[str, set[tuple[tuple[str, str, str, int, int | None], ...]]] = {}

    for card in card_set.cards:
        bonus_texts_by_clan.setdefault(card.clan, set()).add(card.bonus_text)
        bonus_effect_signatures_by_clan.setdefault(card.clan, set()).add(
            tuple(
                (effect.trigger, effect.target, effect.effect_type, effect.value, effect.minimum)
                for effect in card.bonus_effects
            )
        )
        assert card.info
        assert card.power_effects or card.bonus_effects

    assert bonus_texts_by_clan == {
        "Solaïres": {"+2 Puissance"},
        "Corsaires du Port": {"Victoire : Vol 1 pill"},
        "Palmeros": {"-2 dégâts adverses, min. 1"},
        "Égoutiers": {"Victoire : Poison 2, min. 4"},
        "Jardiniers de Béton": {"Victoire : Régénération 2"},
    }
    assert bonus_effect_signatures_by_clan == {
        "Solaïres": {(("passive", "self", "power_modifier", 2, None),)},
        "Corsaires du Port": {(("victory", "opponent", "pill_steal", 1, None),)},
        "Palmeros": {(("passive", "opponent", "damage_modifier", -2, 1),)},
        "Égoutiers": {(("victory", "opponent", "poison", 2, 4),)},
        "Jardiniers de Béton": {(("victory", "self", "regeneration", 2, None),)},
    }


def test_load_card_set_resolves_generated_urban2_illustration_paths() -> None:
    """Every runtime illustration path should point to a generated Urban 2 image."""
    project_root = Path(__file__).resolve().parents[1]
    card_set = load_card_set(ACTIVE_URBAN2_PATH)

    for card in card_set.cards:
        assert (project_root / card.illustration).exists()


def test_load_card_set_raises_clear_error_for_missing_file(tmp_path: Path) -> None:
    """Missing files should raise a dedicated loading error."""
    missing_path = tmp_path / "missing_cards.json"

    with pytest.raises(CardSetLoadError, match="Card set file not found"):
        load_card_set(missing_path)


def test_load_card_set_raises_clear_error_for_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON should produce a readable parsing error."""
    invalid_json_path = tmp_path / "broken_cards.json"
    invalid_json_path.write_text('{"set_id": "starter", "cards": [}', encoding="utf-8")

    with pytest.raises(CardSetFormatError, match="Invalid JSON"):
        load_card_set(invalid_json_path)


def test_load_card_set_rejects_missing_required_root_keys(tmp_path: Path) -> None:
    """A legacy card set file must expose the required root structure."""
    invalid_set_path = tmp_path / "invalid_cards.json"
    invalid_set_path.write_text('{"set_id": "starter", "cards": []}', encoding="utf-8")

    with pytest.raises(CardSetFormatError, match="missing required keys: name"):
        load_card_set(invalid_set_path)


def test_load_card_set_rejects_duplicate_card_ids(tmp_path: Path) -> None:
    """Duplicate card ids should be rejected explicitly."""
    duplicate_set_path = tmp_path / "duplicate_cards.json"
    duplicate_set_path.write_text(
        """
        {
          "set_id": "starter",
          "name": "Starter Set",
          "cards": [
            {
              "id": "blade",
              "name": "Blade",
              "clan": "Test",
              "stars": 2,
              "power": 7,
              "damage": 4,
              "power_text": "None",
              "bonus_text": "None",
              "illustration": "a.png"
            },
            {
              "id": "blade",
              "name": "Blade Copy",
              "clan": "Test",
              "stars": 2,
              "power": 6,
              "damage": 3,
              "power_text": "None",
              "bonus_text": "None",
              "illustration": "b.png"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(CardSetFormatError, match="duplicate card ids"):
        load_card_set(duplicate_set_path)


def test_load_card_set_rejects_invalid_card_field_type(tmp_path: Path) -> None:
    """Invalid field types inside one card should be reported clearly."""
    invalid_set_path = tmp_path / "typed_cards.json"
    invalid_set_path.write_text(
        """
        {
          "set_id": "starter",
          "name": "Starter Set",
          "cards": [
            {
              "id": "blade",
              "name": "Blade",
              "clan": "Test",
              "stars": 2,
              "power": "7",
              "damage": 4,
              "power_text": "None",
              "bonus_text": "None",
              "illustration": "a.png"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(CardSetFormatError, match="field 'power' must be an integer"):
        load_card_set(invalid_set_path)
