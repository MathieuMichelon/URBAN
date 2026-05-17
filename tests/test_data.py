"""Unit tests for card set loading."""

from collections import Counter
from pathlib import Path

import pytest

from core.errors import CardSetFormatError, CardSetLoadError
from data.card_repository import load_card_set, load_cards


LEGACY_ACTIVE_ROSTER_IDS = {
    "blade",
    "nyra",
    "brakk",
    "sola",
    "luna",
    "selen",
    "vextor",
    "orkan",
}


def test_load_card_set_reads_example_catalog_metadata() -> None:
    """The example catalog should expose both set metadata and card objects."""
    project_root = Path(__file__).resolve().parents[1]

    card_set = load_card_set(project_root / "data" / "cards.json")

    assert card_set.set_id == "urban_duel_roster_v2"
    assert card_set.name == "Urban Duel 30 Character Roster"
    assert len(card_set.cards) == 30
    assert {card.clan for card in card_set.cards} == {"Pulse 404", "Verdelune", "Bastion-9"}
    assert min(card.stars for card in card_set.cards) == 1
    assert max(card.stars for card in card_set.cards) == 3


def test_load_cards_returns_domain_cards_from_a_set_file() -> None:
    """The convenience loader should return only Card objects."""
    project_root = Path(__file__).resolve().parents[1]

    cards = load_cards(project_root / "data" / "cards.json")

    assert len(cards) == 30
    assert any(card.power_text for card in cards)
    assert any(card.bonus_text for card in cards)
    assert any(card.bonus_effects for card in cards)


def test_load_card_set_uses_only_the_new_active_roster_ids() -> None:
    """The runtime roster should no longer expose legacy active character ids."""
    project_root = Path(__file__).resolve().parents[1]

    card_set = load_card_set(project_root / "data" / "cards.json")
    active_ids = {card.id for card in card_set.cards}

    assert len(active_ids) == 30
    assert active_ids.isdisjoint(LEGACY_ACTIVE_ROSTER_IDS)


def test_load_card_set_contains_three_clans_with_ten_cards_each() -> None:
    """The migrated roster should be evenly distributed across the 3 clans."""
    project_root = Path(__file__).resolve().parents[1]

    card_set = load_card_set(project_root / "data" / "cards.json")
    cards_per_clan = Counter(card.clan for card in card_set.cards)

    assert cards_per_clan == {
        "Pulse 404": 10,
        "Verdelune": 10,
        "Bastion-9": 10,
    }


def test_load_card_set_keeps_clan_bonus_data_consistent_per_clan() -> None:
    """Each clan should resolve to one shared bonus definition across its cards."""
    project_root = Path(__file__).resolve().parents[1]

    card_set = load_card_set(project_root / "data" / "cards.json")
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
        assert card.illustration.startswith("assets/cards/")
        assert card.info
        assert card.power_effects or card.bonus_effects

    assert bonus_texts_by_clan == {
        "Pulse 404": {"+8 Attaque"},
        "Verdelune": {"Victoire : +2 Vie"},
        "Bastion-9": {"+2 Dégâts"},
    }
    assert bonus_effect_signatures_by_clan == {
        "Pulse 404": {(("passive", "self", "attack_modifier", 8, None),)},
        "Verdelune": {(("victory", "self", "life_gain", 2, None),)},
        "Bastion-9": {(("passive", "self", "damage_modifier", 2, None),)},
    }


def test_load_card_set_resolves_generated_illustration_paths() -> None:
    """Every runtime illustration path should point to a generated card art file."""
    project_root = Path(__file__).resolve().parents[1]
    card_set = load_card_set(project_root / "data" / "cards.json")

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
    """A card set file must expose the required root structure."""
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
