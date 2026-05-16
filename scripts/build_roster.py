"""Build the runtime card catalog from the source roster JSON."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROSTER_PATH = PROJECT_ROOT / "data" / "roster_source.json"
OUTPUT_ROSTER_PATH = PROJECT_ROOT / "data" / "cards.json"


def normalize_text(value: str) -> str:
    """Return an ASCII-ish representation for stable parsing."""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def slugify(value: str) -> str:
    """Return a deterministic filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def load_source_roster(path: Path) -> dict[str, object]:
    """Read the source roster JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def parse_trigger(text: str) -> tuple[str, str]:
    """Extract a supported trigger prefix when present."""
    stripped = text.strip()
    normalized = normalize_text(stripped)
    trigger_prefixes = {
        "courage": "courage",
        "revanche": "revenge",
        "victoire": "victory",
        "defaite": "defeat",
    }
    for label, trigger in trigger_prefixes.items():
        prefix = f"{label} :"
        if normalized.lower().startswith(prefix):
            return trigger, stripped[len(prefix):].strip()
    return "passive", stripped


def build_effect(*, trigger: str, target: str, effect_type: str, value: int, minimum: int | None = None) -> dict[str, object]:
    """Create one runtime effect payload."""
    payload: dict[str, object] = {
        "trigger": trigger,
        "target": target,
        "effect_type": effect_type,
        "value": value,
    }
    if minimum is not None:
        payload["minimum"] = minimum
    return payload


def parse_ability_effects(ability_text: str) -> list[dict[str, object]]:
    """Translate source ability text into runtime effect data."""
    trigger, body = parse_trigger(ability_text)
    normalized = normalize_text(body).replace("−", "-").strip()

    simple_patterns: list[tuple[str, str, str, str]] = [
        (r"^\+(\d+)\s+Attaque$", "self", "attack_modifier", "value"),
        (r"^\+(\d+)\s+Puissance$", "self", "power_modifier", "value"),
        (r"^\+(\d+)\s+Degat[s]?$", "self", "damage_modifier", "value"),
        (r"^\+(\d+)\s+Vie$", "self", "life_gain", "value"),
        (r"^\+(\d+)\s+pill[s]?$", "self", "pill_gain", "value"),
        (r"^Vie\s+adv\.\s*-(\d+)$", "opponent", "life_loss", "value"),
    ]
    for pattern, target, effect_type, group_name in simple_patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return [build_effect(trigger=trigger, target=target, effect_type=effect_type, value=int(match.group(1)))]

    conditional_patterns: list[tuple[str, str, str]] = [
        (r"^-(\d+)\s+Attaque\s+adv\.,\s*min\.?\s*(\d+)$", "opponent", "attack_modifier"),
        (r"^-(\d+)\s+Puissance\s+adv\.,\s*min\.?\s*(\d+)$", "opponent", "power_modifier"),
        (r"^-(\d+)\s+Degat[s]?\s+adv\.,\s*min\.?\s*(\d+)$", "opponent", "damage_modifier"),
    ]
    for pattern, target, effect_type in conditional_patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return [
                build_effect(
                    trigger=trigger,
                    target=target,
                    effect_type=effect_type,
                    value=-int(match.group(1)),
                    minimum=int(match.group(2)),
                )
            ]

    poison_match = re.match(r"^Poison\s+(\d+),\s*min\.?\s*(\d+)$", normalized, flags=re.IGNORECASE)
    if poison_match:
        return [
            build_effect(
                trigger=trigger,
                target="opponent",
                effect_type="poison",
                value=int(poison_match.group(1)),
                minimum=int(poison_match.group(2)),
            )
        ]

    if normalized.lower() == "stop bonus adv.":
        return [build_effect(trigger=trigger, target="self", effect_type="stop_opponent_bonus", value=0)]
    if normalized.lower() == "stop pouvoir adv.":
        return [build_effect(trigger=trigger, target="self", effect_type="stop_opponent_power", value=0)]
    if normalized.lower() == "protection : bonus":
        return [build_effect(trigger=trigger, target="self", effect_type="protection_bonus", value=0)]
    if normalized.lower() == "protection : puissance":
        return [build_effect(trigger=trigger, target="self", effect_type="protection_power", value=0)]

    raise ValueError(f"Unsupported ability text: {ability_text}")


def build_bonus_payload(bonus: dict[str, object]) -> tuple[str, list[dict[str, object]]]:
    """Translate clan bonus source data into runtime text plus effect definitions."""
    bonus_text = str(bonus["text"])
    bonus_type = str(bonus["type"])
    bonus_value = int(bonus.get("value", 0) or 0)

    if bonus_type == "attack_modifier":
        return bonus_text, [build_effect(trigger="passive", target="self", effect_type="attack_modifier", value=bonus_value)]
    if bonus_type == "life_gain_on_win":
        return bonus_text, [build_effect(trigger="victory", target="self", effect_type="life_gain", value=bonus_value)]
    if bonus_type == "protect_power":
        return bonus_text, [build_effect(trigger="passive", target="self", effect_type="protection_power", value=0)]

    raise ValueError(f"Unsupported clan bonus type: {bonus_type}")


def build_runtime_roster() -> dict[str, object]:
    """Convert the source roster into the runtime card-set shape."""
    payload = load_source_roster(SOURCE_ROSTER_PATH)
    cards: list[dict[str, object]] = []

    for clan in payload["clans"]:
        clan_name = clan["name"]
        clan_id = clan["id"]
        bonus_text, bonus_effects = build_bonus_payload(clan["bonus"])

        for character in clan["characters"]:
            card_id = character["id"]
            cards.append(
                {
                    "id": card_id,
                    "name": character["name"],
                    "clan": clan_name,
                    "stars": character["stars"],
                    "power": character["power"],
                    "damage": character["damage"],
                    "power_text": character["ability_text"],
                    "bonus_text": bonus_text,
                    "illustration": f"assets/cards/{clan_id}/{slugify(card_id)}.png",
                    "info": character.get("info"),
                    "power_effects": parse_ability_effects(character["ability_text"]),
                    "bonus_effects": bonus_effects,
                }
            )

    cards.sort(key=lambda entry: (entry["clan"], entry["stars"], entry["name"]))
    return {
        "set_id": "urban_duel_roster_v2",
        "name": "Urban Duel 30 Character Roster",
        "cards": cards,
    }


def main() -> None:
    """Build and write the runtime roster file."""
    roster = build_runtime_roster()
    OUTPUT_ROSTER_PATH.write_text(json.dumps(roster, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(roster['cards'])} cards to {OUTPUT_ROSTER_PATH}")


if __name__ == "__main__":
    main()
