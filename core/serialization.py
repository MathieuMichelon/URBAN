"""Shared serializers for domain objects."""

from __future__ import annotations

from core.models import Card, EffectCondition, EffectDefinition, OngoingPoison, OngoingRegeneration, RoundResult


def serialize_card(card: Card) -> dict[str, object]:
    """Convert one card into a serializable payload."""
    return {
        "id": card.id,
        "name": card.name,
        "clan": card.clan,
        "stars": card.stars,
        "power": card.power,
        "damage": card.damage,
        "power_text": card.power_text,
        "bonus_text": card.bonus_text,
        "illustration": card.illustration,
        "info": card.info,
        "power_effects": [serialize_effect(effect) for effect in card.power_effects],
        "bonus_effects": [serialize_effect(effect) for effect in card.bonus_effects],
    }


def serialize_effect(effect: EffectDefinition) -> dict[str, object]:
    """Convert one effect definition into a serializable payload."""
    payload: dict[str, object] = {
        "trigger": effect.trigger,
        "target": effect.target,
        "effect_type": effect.effect_type,
        "value": effect.value,
    }
    if effect.minimum is not None:
        payload["minimum"] = effect.minimum
    if effect.condition is not None:
        payload["condition"] = serialize_effect_condition(effect.condition)
    return payload


def serialize_effect_condition(condition: EffectCondition) -> dict[str, object]:
    """Convert one generic effect condition into a serializable payload."""
    return {"kind": condition.kind, "value": condition.value}


def serialize_poison(poison: OngoingPoison | None) -> dict[str, int] | None:
    """Convert a poison state into a serializable payload."""
    if poison is None:
        return None
    return {
        "amount": poison.amount,
        "minimum_hit_points": poison.minimum_hit_points,
    }


def serialize_regeneration(regeneration: OngoingRegeneration | None) -> dict[str, int] | None:
    """Convert a regeneration state into a serializable payload."""
    if regeneration is None:
        return None
    return {"amount": regeneration.amount}


def serialize_round_result(result: RoundResult) -> dict[str, object]:
    """Convert one resolved round into a serializable payload."""
    return {
        "round_number": result.round_number,
        "player_1_card_id": result.player_1_card_id,
        "player_2_card_id": result.player_2_card_id,
        "player_1_attack": result.player_1_attack,
        "player_2_attack": result.player_2_attack,
        "outcome": result.outcome.value,
        "winner_id": result.winner_id,
        "loser_id": result.loser_id,
        "damage_dealt": result.damage_dealt,
        "player_1_pills_committed": result.player_1_pills_committed,
        "player_2_pills_committed": result.player_2_pills_committed,
        "life_swing_player_1": result.life_swing_player_1,
        "life_swing_player_2": result.life_swing_player_2,
        "pills_gained_player_1": result.pills_gained_player_1,
        "pills_gained_player_2": result.pills_gained_player_2,
        "player_1_overload": result.player_1_overload,
        "player_2_overload": result.player_2_overload,
        "overload_damage_bonus": result.overload_damage_bonus,
    }
