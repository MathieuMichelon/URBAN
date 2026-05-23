"""Load the Urban 2 character JSON into runtime card objects."""

from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from pathlib import Path
import re
import unicodedata

from core.errors import CardSetFormatError, CardSetLoadError
from core.models import Card, EffectDefinition


@dataclass(frozen=True, slots=True)
class Urban2Clan:
    """UI-ready clan data derived from the Urban 2 source file."""

    id: str
    display_name: str
    bonus_text: str
    gameplay: str
    description: str
    sheet_path: str


@dataclass(frozen=True, slots=True)
class Urban2Roster:
    """Runtime cards plus the clan metadata they came from."""

    set_id: str
    name: str
    clans: tuple[Urban2Clan, ...]
    cards: list[Card]


SHEET_BY_CLAN_ID = {
    "solaires": "assets/clans/solaires.png",
    "corsaires_du_port": "assets/clans/corsaires.png",
    "palmeros": "assets/clans/palmeros.png",
    "egoutiers": "assets/clans/egoutiers.png",
    "jardiniers_de_beton": "assets/clans/jardiniers.png",
}


def slugify(value: str) -> str:
    """Return a stable ASCII technical identifier while preserving display names elsewhere."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_value = ascii_value.replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def load_urban2_roster(path: str | Path) -> Urban2Roster:
    """Read an Urban 2 source JSON file and return runtime cards."""
    json_path = Path(path)
    payload = _read_json_file(json_path)
    if not isinstance(payload, dict):
        raise CardSetFormatError(f"Urban 2 roster '{json_path.name}' must contain a JSON object.")

    raw_clans = payload.get("clans")
    raw_characters = payload.get("characters")
    if not isinstance(raw_clans, list) or not isinstance(raw_characters, list):
        raise CardSetFormatError("Urban 2 roster must define 'clans' and 'characters' arrays.")

    clans = tuple(_build_clan(entry, index=index) for index, entry in enumerate(raw_clans))
    clan_by_name = {clan.display_name: clan for clan in clans}
    bonus_by_clan_name = {
        clan.display_name: _parse_effects(clan.bonus_text, source="bonus")
        for clan in clans
    }

    cards = [
        _build_card(
            entry,
            index=index,
            clan_by_name=clan_by_name,
            bonus_by_clan_name=bonus_by_clan_name,
        )
        for index, entry in enumerate(raw_characters)
    ]

    ids = [card.id for card in cards]
    if len(set(ids)) != len(ids):
        raise CardSetFormatError("Urban 2 roster contains duplicate generated card ids.")

    cards.sort(key=lambda card: (card.clan, card.stars, card.name))
    return Urban2Roster(
        set_id="urban2_personnages_base",
        name="Urban 2 Personnages Base",
        clans=clans,
        cards=cards,
    )


def _read_json_file(path: Path) -> object:
    if not path.exists():
        raise CardSetLoadError(f"Urban 2 roster file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CardSetLoadError(f"Unable to read Urban 2 roster file '{path}': {error}") from error
    except JSONDecodeError as error:
        raise CardSetFormatError(
            f"Invalid JSON in Urban 2 roster '{path.name}' at line {error.lineno}, column {error.colno}: {error.msg}."
        ) from error


def _build_clan(entry: object, *, index: int) -> Urban2Clan:
    if not isinstance(entry, dict):
        raise CardSetFormatError(f"Urban 2 clan entry #{index} must be an object.")

    display_name = _required_string(entry, "name", f"clan #{index}")
    clan_id = slugify(display_name)
    return Urban2Clan(
        id=clan_id,
        display_name=display_name,
        bonus_text=_required_string(entry, "bonus", display_name),
        gameplay=_optional_string(entry, "gameplay"),
        description=_optional_string(entry, "description"),
        sheet_path=SHEET_BY_CLAN_ID.get(clan_id, _optional_string(entry, "illustration_sheet")),
    )


def _build_card(
    entry: object,
    *,
    index: int,
    clan_by_name: dict[str, Urban2Clan],
    bonus_by_clan_name: dict[str, tuple[EffectDefinition, ...]],
) -> Card:
    if not isinstance(entry, dict):
        raise CardSetFormatError(f"Urban 2 character entry #{index} must be an object.")

    display_name = _required_string(entry, "name", f"character #{index}")
    clan_name = _required_string(entry, "clan", display_name)
    try:
        clan = clan_by_name[clan_name]
    except KeyError as error:
        raise CardSetFormatError(f"Character '{display_name}' references unknown clan '{clan_name}'.") from error

    card_id = slugify(display_name)
    ability_text = _required_string(entry, "ability", display_name)
    sheet_position = entry.get("sheet_position", {})
    position_label = ""
    if isinstance(sheet_position, dict):
        position_label = str(sheet_position.get("position") or "")

    return Card(
        id=card_id,
        name=display_name,
        clan=clan.display_name,
        stars=_required_int(entry, "level", display_name),
        power=_required_int(entry, "power", display_name),
        damage=_required_int(entry, "damage", display_name),
        power_text=ability_text,
        bonus_text=clan.bonus_text,
        illustration=f"assets/cards/urban2/{clan.id}/{card_id}.png",
        power_effects=_parse_effects(ability_text, source="power"),
        bonus_effects=bonus_by_clan_name[clan.display_name],
        info=_build_info(entry, position_label=position_label),
    )


def _build_info(entry: dict[str, object], *, position_label: str) -> str:
    parts = [
        _optional_string(entry, "role"),
        _optional_string(entry, "description"),
    ]
    if position_label:
        parts.append(f"Planche {position_label}")
    return " — ".join(part for part in parts if part)


def _parse_effects(text: str, *, source: str) -> tuple[EffectDefinition, ...]:
    trigger, body = _parse_trigger(text)
    normalized = _normalize(body).replace("−", "-").strip()
    lowered = normalized.lower()

    simple_patterns: list[tuple[str, str, str]] = [
        (r"^\+(\d+)\s+attaque$", "self", "attack_modifier"),
        (r"^\+(\d+)\s+puissance$", "self", "power_modifier"),
        (r"^\+(\d+)\s+degat[s]?$", "self", "damage_modifier"),
        (r"^\+(\d+)\s+pv$", "self", "life_gain"),
        (r"^\+(\d+)\s+pill[s]?$", "self", "pill_gain"),
    ]
    for pattern, target, effect_type in simple_patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return (_effect(trigger, target, effect_type, int(match.group(1))),)

    opponent_stat_patterns: list[tuple[str, str]] = [
        (r"^-(\d+)\s+attaque\s+adv\.,\s*min\.?\s*(\d+)$", "attack_modifier"),
        (r"^-(\d+)\s+puissance\s+adv\.,\s*min\.?\s*(\d+)$", "power_modifier"),
        (r"^-(\d+)\s+degat[s]?\s+adverses,\s*min\.?\s*(\d+)$", "damage_modifier"),
        (r"^-(\d+)\s+degat[s]?\s+adv\.,\s*min\.?\s*(\d+)$", "damage_modifier"),
    ]
    for pattern, effect_type in opponent_stat_patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return (
                _effect(
                    trigger,
                    "opponent",
                    effect_type,
                    -int(match.group(1)),
                    minimum=int(match.group(2)),
                ),
            )

    life_loss_match = re.match(r"^-(\d+)\s+pv\s+adv\.,\s*min\.?\s*(\d+)$", normalized, flags=re.IGNORECASE)
    if life_loss_match:
        return (
            _effect(
                trigger,
                "opponent",
                "life_loss",
                int(life_loss_match.group(1)),
                minimum=int(life_loss_match.group(2)),
            ),
        )

    poison_match = re.match(r"^poison\s+(\d+),\s*min\.?\s*(\d+)$", normalized, flags=re.IGNORECASE)
    if poison_match:
        return (_effect(trigger, "opponent", "poison", int(poison_match.group(1)), minimum=int(poison_match.group(2))),)

    pill_pressure_match = re.match(r"^-(\d+)\s+pill\s+adv\.,\s*min\.?\s*(\d+)$", normalized, flags=re.IGNORECASE)
    if lowered == "vol 1 pill" or pill_pressure_match:
        return (_effect(trigger, "opponent", "pill_steal", 1),)

    if lowered == "stop bonus adv.":
        return (_effect(trigger, "self", "stop_opponent_bonus", 0),)
    if lowered == "stop pouvoir adv.":
        return (_effect(trigger, "self", "stop_opponent_power", 0),)

    regeneration_match = re.match(r"^regeneration\s+(\d+)$", normalized, flags=re.IGNORECASE)
    if regeneration_match:
        return (_effect(trigger, "self", "regeneration", int(regeneration_match.group(1))),)

    raise CardSetFormatError(f"Unsupported Urban 2 {source} effect text: {text}")


def _parse_trigger(text: str) -> tuple[str, str]:
    stripped = text.strip()
    normalized = _normalize(stripped).lower()
    prefixes = {
        "victoire :": "victory",
        "defaite :": "defeat",
        "courage :": "courage",
        "revanche :": "revenge",
    }
    for prefix, trigger in prefixes.items():
        if normalized.startswith(prefix):
            return trigger, stripped[len(prefix):].strip()
    return "passive", stripped


def _effect(trigger: str, target: str, effect_type: str, value: int, *, minimum: int | None = None) -> EffectDefinition:
    return EffectDefinition(trigger=trigger, target=target, effect_type=effect_type, value=value, minimum=minimum)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _required_string(payload: dict[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CardSetFormatError(f"Urban 2 {context} field '{key}' must be a non-empty string.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _required_int(payload: dict[str, object], key: str, context: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CardSetFormatError(f"Urban 2 {context} field '{key}' must be an integer.")
    return value
