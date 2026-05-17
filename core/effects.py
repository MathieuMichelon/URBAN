"""Generic power and clan bonus resolution for round combat."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from core.enums import RoundOutcome
from core.models import Card, EffectDefinition, GameState, OngoingPoison, PlayerState

PRE_FIGHT_RESOLUTION_ORDER = (
    "collect_pre_fight_sources",
    "apply_protections",
    "apply_stop_flags",
    "disable_opponent_power_and_bonus",
    "apply_pre_fight_stat_modifiers",
    "compute_attack",
)

POST_FIGHT_RESOLUTION_ORDER = (
    "collect_post_fight_sources",
    "apply_victory_and_defeat_effects",
    "apply_poison_end_of_round",
)

TRIGGER_LABELS = {
    "passive": "",
    "courage": "Courage: ",
    "revenge": "Revenge: ",
    "victory": "Victory: ",
    "defeat": "Defeat: ",
}

EFFECT_TYPE_LABELS = {
    "attack_modifier": "Attack {value:+d}",
    "power_modifier": "Power {value:+d}",
    "damage_modifier": "Damage {value:+d}",
    "life_gain": "Life +{value}",
    "life_loss": "Opponent life -{value}",
    "poison": "Poison {value}",
    "pill_gain": "Pills +{value}",
    "pill_steal": "Steal {value} pill",
    "stop_opponent_power": "Stop opponent power",
    "stop_opponent_bonus": "Stop opponent bonus",
    "protection_bonus": "Protection: Bonus",
    "protection_power": "Protection: Power",
}


@dataclass(slots=True)
class FighterEffects:
    """Computed pre-fight and post-fight state for one fighter."""

    player: PlayerState
    card: Card
    pills_committed: int
    attack_modifier: int = 0
    power_modifier: int = 0
    damage_modifier: int = 0
    stop_opponent_power: bool = False
    stop_opponent_bonus: bool = False
    protection_power: bool = False
    protection_bonus: bool = False
    power_disabled: bool = False
    bonus_disabled: bool = False

    @property
    def effective_power(self) -> int:
        """Return the power used to compute attack."""
        return max(0, self.card.power + self.power_modifier)

    @property
    def effective_damage(self) -> int:
        """Return the damage dealt when this fighter wins."""
        return max(0, self.card.damage + self.damage_modifier)

    @property
    def attack(self) -> int:
        """Return the final attack after modifiers."""
        return max(0, (self.effective_power * self.pills_committed) + self.attack_modifier)


@dataclass(frozen=True, slots=True)
class RoundEffectResult:
    """Resolved fight output consumed by the engine."""

    player_1_attack: int
    player_2_attack: int
    outcome: RoundOutcome
    winner_id: int | None
    loser_id: int | None
    damage_dealt: int
    life_swing_player_1: int
    life_swing_player_2: int
    pills_gained_player_1: int
    pills_gained_player_2: int


@dataclass(slots=True)
class PostRoundLedger:
    """Track non-damage side effects applied after combat."""

    life_swing: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0})
    pill_gain: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0})


def compute_active_clans(cards: list[Card]) -> set[str]:
    """Return the clans whose team bonus is active for the given team."""
    clan_counts = Counter(card.clan for card in cards)
    return {clan for clan, count in clan_counts.items() if count >= 2}


def describe_effect(effect: EffectDefinition) -> str:
    """Return a UI-readable description for one structured effect."""
    trigger_prefix = TRIGGER_LABELS.get(effect.trigger, f"{effect.trigger.title()}: ")
    template = EFFECT_TYPE_LABELS.get(effect.effect_type, effect.effect_type.replace("_", " ").title())
    detail = template.format(value=effect.value)

    if effect.effect_type == "poison" and effect.minimum is not None:
        detail = f"{detail}, min {effect.minimum}"
    elif effect.minimum is not None and effect.effect_type in {"attack_modifier", "power_modifier", "damage_modifier", "life_loss"}:
        detail = f"{detail}, min {effect.minimum}"

    return f"{trigger_prefix}{detail}".strip()


def describe_effects(effects: tuple[EffectDefinition, ...], *, fallback: str = "No effect") -> str:
    """Return a UI-readable description for a power or clan bonus payload."""
    if not effects:
        return fallback
    return " | ".join(describe_effect(effect) for effect in effects)


def resolve_round_effects(
    state: GameState,
    *,
    player_1_card: Card,
    player_2_card: Card,
    player_1_pills: int,
    player_2_pills: int,
) -> RoundEffectResult:
    """Resolve the fight outcome without mutating end-of-round resources."""
    fighter_1 = FighterEffects(player=state.get_player(1), card=player_1_card, pills_committed=player_1_pills)
    fighter_2 = FighterEffects(player=state.get_player(2), card=player_2_card, pills_committed=player_2_pills)

    _resolve_pre_fight_effects(state, fighter_1, fighter_2)

    player_1_attack = fighter_1.attack
    player_2_attack = fighter_2.attack

    outcome = RoundOutcome.TIE
    winner_id = None
    loser_id = None
    damage_dealt = 0

    if player_1_attack > player_2_attack:
        outcome = RoundOutcome.PLAYER_1_WINS
        winner_id = 1
        loser_id = 2
        damage_dealt = fighter_1.effective_damage
    elif player_2_attack > player_1_attack:
        outcome = RoundOutcome.PLAYER_2_WINS
        winner_id = 2
        loser_id = 1
        damage_dealt = fighter_2.effective_damage

    return RoundEffectResult(
        player_1_attack=player_1_attack,
        player_2_attack=player_2_attack,
        outcome=outcome,
        winner_id=winner_id,
        loser_id=loser_id,
        damage_dealt=damage_dealt,
        life_swing_player_1=0,
        life_swing_player_2=0,
        pills_gained_player_1=0,
        pills_gained_player_2=0,
    )


def apply_round_aftermath(
    state: GameState,
    *,
    player_1_card: Card,
    player_2_card: Card,
    player_1_pills: int,
    player_2_pills: int,
    winner_id: int | None,
    loser_id: int | None,
) -> PostRoundLedger:
    """Apply victory, defeat, and poison effects after damage is resolved."""
    fighter_1 = FighterEffects(player=state.get_player(1), card=player_1_card, pills_committed=player_1_pills)
    fighter_2 = FighterEffects(player=state.get_player(2), card=player_2_card, pills_committed=player_2_pills)
    _resolve_pre_fight_effects(state, fighter_1, fighter_2)

    ledger = PostRoundLedger()
    _apply_post_fight_effects(state, fighter_1, fighter_2, winner_id=winner_id, loser_id=loser_id, ledger=ledger)
    _apply_poison_end_of_round(state, ledger)
    return ledger


def _resolve_pre_fight_effects(state: GameState, fighter_1: FighterEffects, fighter_2: FighterEffects) -> None:
    """Apply pre-fight protections, stops, and stat modifiers in order."""
    _ = PRE_FIGHT_RESOLUTION_ORDER
    pre_sources_1 = _collect_effect_sources(state, fighter_1, stage="pre")
    pre_sources_2 = _collect_effect_sources(state, fighter_2, stage="pre")

    _apply_protections(fighter_1, pre_sources_1)
    _apply_protections(fighter_2, pre_sources_2)
    _apply_stop_flags(fighter_1, pre_sources_1)
    _apply_stop_flags(fighter_2, pre_sources_2)

    if fighter_1.stop_opponent_power and not fighter_2.protection_power:
        fighter_2.power_disabled = True
    if fighter_2.stop_opponent_power and not fighter_1.protection_power:
        fighter_1.power_disabled = True
    if fighter_1.stop_opponent_bonus and not fighter_2.protection_bonus:
        fighter_2.bonus_disabled = True
    if fighter_2.stop_opponent_bonus and not fighter_1.protection_bonus:
        fighter_1.bonus_disabled = True

    _apply_stat_modifiers(fighter_1, fighter_2, pre_sources_1)
    _apply_stat_modifiers(fighter_2, fighter_1, pre_sources_2)


def _apply_post_fight_effects(
    state: GameState,
    fighter_1: FighterEffects,
    fighter_2: FighterEffects,
    *,
    winner_id: int | None,
    loser_id: int | None,
    ledger: PostRoundLedger,
) -> None:
    """Apply victory and defeat effects after the winner is known."""
    _ = POST_FIGHT_RESOLUTION_ORDER
    for actor, opponent in ((fighter_1, fighter_2), (fighter_2, fighter_1)):
        for source_kind, effect in _collect_effect_sources(state, actor, stage="post"):
            if not _source_enabled(actor, source_kind):
                continue
            if not _targets_round_result(actor.player.player_id, effect, winner_id=winner_id, loser_id=loser_id):
                continue
            _apply_post_effect(actor, opponent, effect, ledger=ledger)


def _apply_poison_end_of_round(state: GameState, ledger: PostRoundLedger) -> None:
    """Apply persistent poison after victory and defeat effects."""
    for player_id in (1, 2):
        player = state.get_player(player_id)
        poison = player.poison
        if poison is None:
            continue

        next_hit_points = max(poison.minimum_hit_points, player.hit_points - poison.amount)
        damage = max(0, player.hit_points - next_hit_points)
        if damage == 0:
            continue

        player.hit_points = next_hit_points
        ledger.life_swing[player_id] -= damage


def _collect_effect_sources(
    state: GameState,
    fighter: FighterEffects,
    *,
    stage: str,
) -> list[tuple[str, EffectDefinition]]:
    """Collect active effect definitions for the requested stage."""
    collected: list[tuple[str, EffectDefinition]] = []

    for effect in fighter.card.power_effects:
        if _trigger_matches(state, fighter.player.player_id, effect.trigger, stage=stage):
            collected.append(("power", effect))

    if fighter.player.has_active_bonus_for(fighter.card.clan):
        for effect in fighter.card.bonus_effects:
            if _trigger_matches(state, fighter.player.player_id, effect.trigger, stage=stage):
                collected.append(("bonus", effect))

    return collected


def _trigger_matches(state: GameState, player_id: int, trigger: str, *, stage: str) -> bool:
    """Return whether one effect trigger is active in the current context."""
    if stage == "pre" and trigger == "passive":
        return True
    if stage == "pre" and trigger == "courage":
        return state.initiative_player_id == player_id
    if stage == "pre" and trigger == "revenge":
        previous_winner = state.previous_round_winner_id
        return previous_winner is not None and previous_winner != player_id
    if stage == "post" and trigger in {"victory", "defeat"}:
        return True
    return False


def _apply_protections(fighter: FighterEffects, sources: list[tuple[str, EffectDefinition]]) -> None:
    """Read protection flags before stop effects are resolved."""
    for _source_kind, effect in sources:
        if effect.effect_type == "protection_power":
            fighter.protection_power = True
        elif effect.effect_type == "protection_bonus":
            fighter.protection_bonus = True


def _apply_stop_flags(fighter: FighterEffects, sources: list[tuple[str, EffectDefinition]]) -> None:
    """Read stop flags from the fighter sources."""
    for _source_kind, effect in sources:
        if effect.effect_type == "stop_opponent_power":
            fighter.stop_opponent_power = True
        elif effect.effect_type == "stop_opponent_bonus":
            fighter.stop_opponent_bonus = True


def _apply_stat_modifiers(
    actor: FighterEffects,
    opponent: FighterEffects,
    sources: list[tuple[str, EffectDefinition]],
) -> None:
    """Apply pre-fight stat modifiers from enabled effects."""
    for source_kind, effect in sources:
        if not _source_enabled(actor, source_kind):
            continue
        if effect.effect_type in {
            "protection_power",
            "protection_bonus",
            "stop_opponent_power",
            "stop_opponent_bonus",
            "life_gain",
            "life_loss",
            "poison",
            "pill_gain",
            "pill_steal",
        }:
            continue

        target = _select_pre_target(actor, opponent, effect)
        if target is None:
            continue

        if effect.effect_type == "attack_modifier":
            target.attack_modifier = _apply_with_minimum(
                target.attack_modifier,
                effect.value,
                minimum=effect.minimum,
                base=target.card.power * target.pills_committed,
            )
        elif effect.effect_type == "power_modifier":
            target.power_modifier = _apply_with_minimum(target.power_modifier, effect.value, minimum=effect.minimum, base=target.card.power)
        elif effect.effect_type == "damage_modifier":
            target.damage_modifier = _apply_with_minimum(target.damage_modifier, effect.value, minimum=effect.minimum, base=target.card.damage)


def _apply_post_effect(
    actor: FighterEffects,
    opponent: FighterEffects,
    effect: EffectDefinition,
    *,
    ledger: PostRoundLedger,
) -> None:
    """Apply a victory/defeat effect after combat."""
    target_player = _select_post_target(actor, opponent, effect)
    if target_player is None:
        return

    if effect.effect_type == "life_gain":
        target_player.hit_points += effect.value
        ledger.life_swing[target_player.player_id] += effect.value
        return

    if effect.effect_type == "life_loss":
        minimum = effect.minimum or 0
        next_hit_points = max(minimum, target_player.hit_points - effect.value)
        delta = target_player.hit_points - next_hit_points
        target_player.hit_points = next_hit_points
        ledger.life_swing[target_player.player_id] -= delta
        return

    if effect.effect_type == "pill_gain":
        target_player.pills += effect.value
        ledger.pill_gain[target_player.player_id] += effect.value
        return

    if effect.effect_type == "pill_steal":
        stolen_pills = min(effect.value, target_player.pills)
        if stolen_pills <= 0:
            return

        target_player.pills -= stolen_pills
        actor.player.pills += stolen_pills
        ledger.pill_gain[target_player.player_id] -= stolen_pills
        ledger.pill_gain[actor.player.player_id] += stolen_pills
        return

    if effect.effect_type == "poison":
        current_poison = target_player.poison
        minimum = effect.minimum or 0
        if current_poison is None or effect.value > current_poison.amount:
            target_player.poison = OngoingPoison(effect.value, minimum)


def _source_enabled(fighter: FighterEffects, source_kind: str) -> bool:
    """Return whether a power or bonus source still applies."""
    if source_kind == "power":
        return not fighter.power_disabled
    if source_kind == "bonus":
        return not fighter.bonus_disabled
    return False


def _targets_round_result(
    player_id: int,
    effect: EffectDefinition,
    *,
    winner_id: int | None,
    loser_id: int | None,
) -> bool:
    """Return whether a victory/defeat effect is active for the round result."""
    if effect.trigger == "victory":
        return winner_id == player_id
    if effect.trigger == "defeat":
        return loser_id == player_id
    return False


def _select_pre_target(
    actor: FighterEffects,
    opponent: FighterEffects,
    effect: EffectDefinition,
) -> FighterEffects | None:
    """Resolve the effect target during pre-fight resolution."""
    if effect.target == "self":
        return actor
    if effect.target == "opponent":
        return opponent
    return None


def _select_post_target(
    actor: FighterEffects,
    opponent: FighterEffects,
    effect: EffectDefinition,
) -> PlayerState | None:
    """Resolve the effect target after combat."""
    if effect.target in {"self", "winner"}:
        return actor.player
    if effect.target in {"opponent", "loser"}:
        return opponent.player
    return None


def _apply_with_minimum(current: int, delta: int, *, minimum: int | None, base: int = 0) -> int:
    """Apply a delta and clamp the final stat to a minimum when requested."""
    next_value = current + delta
    if minimum is None:
        return next_value

    return max(minimum - base, next_value)
