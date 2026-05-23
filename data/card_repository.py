"""Load and validate card sets from JSON files."""

from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from pathlib import Path

from core.errors import CardSetFormatError, CardSetLoadError, InvalidCardDefinitionError
from core.models import Card, EffectCondition, EffectDefinition

REQUIRED_SET_KEYS = {"set_id", "name", "cards"}
REQUIRED_CARD_KEYS = {
    "id",
    "name",
    "clan",
    "stars",
    "power",
    "damage",
    "power_text",
    "bonus_text",
    "illustration",
}


@dataclass(frozen=True, slots=True)
class CardSet:
    """Represent one named set of playable cards."""

    set_id: str
    name: str
    cards: list[Card]


def load_card_set(path: str | Path) -> CardSet:
    """Load a full card set definition from JSON."""
    json_path = Path(path)
    raw_payload = _read_json_file(json_path)

    if not isinstance(raw_payload, dict):
        raise CardSetFormatError(
            f"Card set file '{json_path.name}' must contain a JSON object at the root."
        )

    if _is_urban2_source_payload(raw_payload):
        from data.urban2_loader import load_urban2_roster

        urban2_roster = load_urban2_roster(json_path)
        return CardSet(
            set_id=urban2_roster.set_id,
            name=urban2_roster.name,
            cards=urban2_roster.cards,
        )

    missing_keys = REQUIRED_SET_KEYS - set(raw_payload)
    if missing_keys:
        joined_keys = ", ".join(sorted(missing_keys))
        raise CardSetFormatError(
            f"Card set file '{json_path.name}' is missing required keys: {joined_keys}."
        )

    set_id = _read_required_string(raw_payload, key="set_id", context="card set")
    name = _read_required_string(raw_payload, key="name", context="card set")
    raw_cards = raw_payload["cards"]

    if not isinstance(raw_cards, list):
        raise CardSetFormatError(
            f"Card set '{set_id}' must define 'cards' as a JSON array."
        )

    cards = [_build_card(entry=entry, index=index, set_id=set_id) for index, entry in enumerate(raw_cards)]

    card_ids = [card.id for card in cards]
    if len(set(card_ids)) != len(card_ids):
        raise CardSetFormatError(
            f"Card set '{set_id}' contains duplicate card ids."
        )

    return CardSet(set_id=set_id, name=name, cards=cards)


def load_cards(path: str | Path) -> list[Card]:
    """Load cards from a card set JSON file."""
    return load_card_set(path).cards


def _is_urban2_source_payload(payload: dict[str, object]) -> bool:
    """Return whether the JSON uses the new Urban 2 source shape."""
    return isinstance(payload.get("metadata"), dict) and isinstance(payload.get("clans"), list) and isinstance(payload.get("characters"), list)


def _read_json_file(path: Path) -> object:
    """Read and parse one JSON file with explicit errors."""
    if not path.exists():
        raise CardSetLoadError(f"Card set file not found: {path}")

    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CardSetLoadError(f"Unable to read card set file '{path}': {error}") from error

    try:
        return json.loads(payload)
    except JSONDecodeError as error:
        raise CardSetFormatError(
            f"Invalid JSON in card set file '{path.name}' at line {error.lineno}, column {error.colno}: {error.msg}."
        ) from error


def _build_card(entry: object, index: int, set_id: str) -> Card:
    """Create one card from raw JSON data."""
    if not isinstance(entry, dict):
        raise CardSetFormatError(
            f"Card entry at index {index} in set '{set_id}' must be a JSON object."
        )

    missing_keys = REQUIRED_CARD_KEYS - set(entry)
    if missing_keys:
        joined_keys = ", ".join(sorted(missing_keys))
        raise CardSetFormatError(
            f"Card entry at index {index} in set '{set_id}' is missing required keys: {joined_keys}."
        )

    try:
        return Card(
            id=_read_required_string(entry, key="id", context=f"card entry #{index}"),
            name=_read_required_string(entry, key="name", context=f"card entry #{index}"),
            clan=_read_required_string(entry, key="clan", context=f"card '{entry.get('id', index)}'"),
            stars=_read_required_int(entry, key="stars", context=f"card '{entry.get('id', index)}'"),
            power=_read_required_int(entry, key="power", context=f"card '{entry.get('id', index)}'"),
            damage=_read_required_int(entry, key="damage", context=f"card '{entry.get('id', index)}'"),
            power_text=_read_required_string(entry, key="power_text", context=f"card '{entry.get('id', index)}'"),
            bonus_text=_read_required_string(entry, key="bonus_text", context=f"card '{entry.get('id', index)}'"),
            illustration=_read_required_string(
                entry,
                key="illustration",
                context=f"card '{entry.get('id', index)}'",
            ),
            power_effects=tuple(_read_effects(entry.get("power_effects", []), context=f"card '{entry.get('id', index)}' power_effects")),
            bonus_effects=tuple(_read_effects(entry.get("bonus_effects", []), context=f"card '{entry.get('id', index)}' bonus_effects")),
            info=_read_optional_string(entry, key="info", context=f"card '{entry.get('id', index)}'"),
        )
    except InvalidCardDefinitionError as error:
        raise CardSetFormatError(
            f"Invalid definition for card at index {index} in set '{set_id}': {error}"
        ) from error


def _read_effects(payload: object, *, context: str) -> list[EffectDefinition]:
    """Read a list of effect definitions from raw JSON."""
    if not isinstance(payload, list):
        raise CardSetFormatError(f"{context} must be a JSON array.")

    return [_build_effect(entry, context=f"{context}[{index}]") for index, entry in enumerate(payload)]


def _build_effect(entry: object, *, context: str) -> EffectDefinition:
    """Create one effect definition from raw JSON."""
    if not isinstance(entry, dict):
        raise CardSetFormatError(f"{context} must be a JSON object.")

    required_keys = {"trigger", "target", "effect_type", "value"}
    missing_keys = required_keys - set(entry)
    if missing_keys:
        joined_keys = ", ".join(sorted(missing_keys))
        raise CardSetFormatError(f"{context} is missing required keys: {joined_keys}.")

    condition = entry.get("condition")
    built_condition = _build_condition(condition, context=f"{context}.condition") if condition is not None else None

    try:
        return EffectDefinition(
            trigger=_read_required_string(entry, key="trigger", context=context),
            target=_read_required_string(entry, key="target", context=context),
            effect_type=_read_required_string(entry, key="effect_type", context=context),
            value=_read_required_int(entry, key="value", context=context),
            minimum=_read_optional_int(entry, key="minimum", context=context),
            condition=built_condition,
        )
    except InvalidCardDefinitionError as error:
        raise CardSetFormatError(f"Invalid effect definition for {context}: {error}") from error


def _build_condition(entry: object, *, context: str) -> EffectCondition:
    """Create one effect condition from raw JSON."""
    if not isinstance(entry, dict):
        raise CardSetFormatError(f"{context} must be a JSON object.")
    if "kind" not in entry or "value" not in entry:
        raise CardSetFormatError(f"{context} must contain 'kind' and 'value'.")
    kind = _read_required_string(entry, key="kind", context=context)
    value = entry["value"]
    if not isinstance(value, (str, int, bool)):
        raise CardSetFormatError(f"{context} field 'value' must be a string, integer, or boolean.")
    return EffectCondition(kind=kind, value=value)


def _read_required_string(payload: dict[str, object], *, key: str, context: str) -> str:
    """Read a non-empty string value from a JSON object."""
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise CardSetFormatError(f"{context} field '{key}' must be a non-empty string.")
    return value


def _read_required_int(payload: dict[str, object], *, key: str, context: str) -> int:
    """Read an integer value from a JSON object."""
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise CardSetFormatError(f"{context} field '{key}' must be an integer.")
    return value


def _read_optional_int(payload: dict[str, object], *, key: str, context: str) -> int | None:
    """Read an optional integer value from a JSON object."""
    if key not in payload or payload[key] is None:
        return None
    return _read_required_int(payload, key=key, context=context)


def _read_optional_string(payload: dict[str, object], *, key: str, context: str) -> str | None:
    """Read an optional non-empty string value from a JSON object."""
    if key not in payload or payload[key] is None:
        return None
    return _read_required_string(payload, key=key, context=context)
