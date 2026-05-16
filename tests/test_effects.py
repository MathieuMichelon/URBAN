"""Unit tests for the generic power and clan bonus resolution engine."""

from core.effects import compute_active_clans, describe_effects
from core.engine import GameEngine
from core.models import EffectDefinition, RoundSelection


def test_bonus_activation_requires_two_cards_from_same_clan(card_factory) -> None:
    """A clan bonus should only activate when at least two team cards share the clan."""
    team = [
        card_factory("n1", clan="Neon"),
        card_factory("n2", clan="Neon"),
        card_factory("i1", clan="Iron"),
        card_factory("w1", clan="Wild"),
    ]

    assert compute_active_clans(team) == {"Neon"}


def test_create_game_computes_active_clan_bonuses_from_team_composition(card_factory) -> None:
    """Locked teams should carry their active clan bonuses into the game state."""
    engine = GameEngine()
    player_1_hand = [
        card_factory("n1", clan="Neon"),
        card_factory("n2", clan="Neon"),
        card_factory("i1", clan="Iron"),
        card_factory("w1", clan="Wild"),
    ]
    player_2_hand = [
        card_factory("i2", clan="Iron"),
        card_factory("w2", clan="Wild"),
        card_factory("w3", clan="Wild"),
        card_factory("n3", clan="Neon"),
    ]

    state = engine.create_game(player_1_hand, player_2_hand)

    assert state.get_player(1).active_clan_bonuses == {"Neon"}
    assert state.get_player(2).active_clan_bonuses == {"Wild"}


def test_attack_calculation_applies_power_attack_and_bonus_modifiers(card_factory) -> None:
    """Attack should use the explicit resolution order for power and attack modifiers."""
    engine = GameEngine()
    striker = card_factory(
        "striker",
        clan="Neon",
        power=5,
        damage=2,
        power_text="Power +2 | Attack +3",
        bonus_text="Attack +6",
        power_effects=(
            EffectDefinition("passive", "self", "power_modifier", 2),
            EffectDefinition("passive", "self", "attack_modifier", 3),
        ),
        bonus_effects=(EffectDefinition("passive", "self", "attack_modifier", 6),),
    )
    player_1_hand = [
        striker,
        card_factory("ally", clan="Neon", bonus_text="Attack +6"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory("p2c1", clan="Other", power=5, damage=2),
        card_factory("p2c2", clan="Else"),
        card_factory("p2c3", clan="Else"),
        card_factory("p2c4", clan="Else"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("striker", 2),
        player_2_selection=RoundSelection("p2c1", 2),
    )

    assert result.player_1_attack == 23
    assert result.player_2_attack == 10
    assert result.winner_id == 1


def test_courage_and_revenge_triggers_activate_in_the_right_round_context(card_factory) -> None:
    """Courage should use initiative and revenge should depend on the previous loss."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "courage",
            clan="Neon",
            power=4,
            damage=2,
            power_text="Courage: Power +2",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("courage", "self", "power_modifier", 2),),
        ),
        card_factory("p1c2", power=3, damage=1),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory("blocker", power=5, damage=2),
        card_factory(
            "revenge",
            clan="Wild",
            power=4,
            damage=2,
            power_text="Revenge: Power +3",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("revenge", "self", "power_modifier", 3),),
        ),
        card_factory("p2c3", power=3, damage=1),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    first_round = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("courage", 1),
        player_2_selection=RoundSelection("blocker", 1),
    )
    second_round = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("p1c2", 1),
        player_2_selection=RoundSelection("revenge", 1),
    )

    assert first_round.player_1_attack == 6
    assert first_round.winner_id == 1
    assert second_round.player_2_attack == 7
    assert second_round.winner_id == 2


def test_stop_opponent_power_disables_unprotected_power_effects(card_factory) -> None:
    """Stop power should disable the opponent power source before modifiers apply."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "stopper",
            clan="Wild",
            power=5,
            damage=2,
            power_text="Stop opponent power",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("passive", "self", "stop_opponent_power", 0),),
        ),
        card_factory("p1c2"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory(
            "boosted",
            clan="Iron",
            power=4,
            damage=2,
            power_text="Power +3",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("passive", "self", "power_modifier", 3),),
        ),
        card_factory("p2c2"),
        card_factory("p2c3"),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("stopper", 2),
        player_2_selection=RoundSelection("boosted", 2),
    )

    assert result.player_1_attack == 10
    assert result.player_2_attack == 8
    assert result.winner_id == 1


def test_stop_opponent_bonus_disables_unprotected_bonus_effects(card_factory) -> None:
    """Stop bonus should disable the opponent clan bonus when it is not protected."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "bonus_stopper",
            clan="Wild",
            power=6,
            damage=2,
            power_text="Stop opponent bonus",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("passive", "self", "stop_opponent_bonus", 0),),
        ),
        card_factory("p1c2"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory(
            "bonus_user",
            clan="Neon",
            power=5,
            damage=2,
            power_text="No power",
            bonus_text="Attack +6",
            bonus_effects=(EffectDefinition("passive", "self", "attack_modifier", 6),),
        ),
        card_factory("ally", clan="Neon", bonus_text="Attack +6"),
        card_factory("p2c3"),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("bonus_stopper", 2),
        player_2_selection=RoundSelection("bonus_user", 2),
    )

    assert result.player_1_attack == 12
    assert result.player_2_attack == 10
    assert result.winner_id == 1


def test_protection_bonus_blocks_stop_opponent_bonus(card_factory) -> None:
    """Protection bonus should keep an active clan bonus enabled against stop bonus."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "bonus_stopper",
            clan="Wild",
            power=6,
            damage=2,
            power_text="Stop opponent bonus",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("passive", "self", "stop_opponent_bonus", 0),),
        ),
        card_factory("p1c2"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    protected_bonus = (
        EffectDefinition("passive", "self", "protection_bonus", 0),
        EffectDefinition("passive", "self", "attack_modifier", 6),
    )
    player_2_hand = [
        card_factory(
            "protected_bonus_user",
            clan="Iron",
            power=5,
            damage=2,
            power_text="No power",
            bonus_text="Protection bonus | Attack +6",
            bonus_effects=protected_bonus,
        ),
        card_factory("ally", clan="Iron", bonus_text="Protection bonus | Attack +6"),
        card_factory("p2c3"),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("bonus_stopper", 2),
        player_2_selection=RoundSelection("protected_bonus_user", 2),
    )

    assert result.player_1_attack == 12
    assert result.player_2_attack == 16
    assert result.winner_id == 2


def test_protection_power_blocks_stop_opponent_power(card_factory) -> None:
    """Protection power should keep a card power active against stop power."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "stopper",
            clan="Wild",
            power=5,
            damage=2,
            power_text="Stop power",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("passive", "self", "stop_opponent_power", 0),),
        ),
        card_factory("p1c2"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    protected = card_factory(
        "protected",
        clan="Iron",
        power=5,
        damage=3,
        power_text="Power +3 and protection",
        bonus_text="No bonus",
        power_effects=(
            EffectDefinition("passive", "self", "power_modifier", 3),
            EffectDefinition("passive", "self", "protection_power", 0),
        ),
    )
    player_2_hand = [
        protected,
        card_factory("p2c2"),
        card_factory("p2c3"),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("stopper", 2),
        player_2_selection=RoundSelection("protected", 2),
    )

    assert result.player_1_attack == 10
    assert result.player_2_attack == 16
    assert result.winner_id == 2


def test_victory_and_defeat_triggers_apply_life_and_pill_gain(card_factory) -> None:
    """Victory and defeat effects should resolve after damage with official bookkeeping."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "winner",
            clan="Neon",
            power=7,
            damage=2,
            power_text="Victory: Life +2",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("victory", "self", "life_gain", 2),),
        ),
        card_factory("p1c2"),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory(
            "loser",
            clan="Iron",
            power=4,
            damage=1,
            power_text="Defeat: Pills +3",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("defeat", "self", "pill_gain", 3),),
        ),
        card_factory("p2c2"),
        card_factory("p2c3"),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("winner", 2),
        player_2_selection=RoundSelection("loser", 1),
    )

    assert result.winner_id == 1
    assert result.life_swing_player_1 == 2
    assert result.pills_gained_player_2 == 3
    assert state.get_player(1).hit_points == 22
    assert state.get_player(2).pills == 14


def test_poison_applies_after_damage_and_ticks_on_following_rounds(card_factory) -> None:
    """Poison should apply at end of round and continue on later rounds."""
    engine = GameEngine()
    player_1_hand = [
        card_factory(
            "venom",
            clan="Wild",
            power=7,
            damage=2,
            power_text="Victory: Poison 2",
            bonus_text="No bonus",
            power_effects=(EffectDefinition("victory", "opponent", "poison", 2, minimum=0),),
        ),
        card_factory("p1c2", power=4, damage=1),
        card_factory("p1c3"),
        card_factory("p1c4"),
    ]
    player_2_hand = [
        card_factory("target", clan="Iron", power=4, damage=1),
        card_factory("p2c2", power=1, damage=1),
        card_factory("p2c3"),
        card_factory("p2c4"),
    ]
    state = engine.create_game(player_1_hand, player_2_hand)

    first_result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("venom", 3),
        player_2_selection=RoundSelection("target", 1),
    )

    assert first_result.winner_id == 1
    assert first_result.life_swing_player_2 == -2
    assert state.get_player(2).hit_points == 16
    assert state.get_player(2).poison is not None

    second_result = engine.play_round(
        state=state,
        player_1_selection=RoundSelection("p1c2", 2),
        player_2_selection=RoundSelection("p2c2", 1),
    )

    assert second_result.winner_id == 1
    assert second_result.life_swing_player_2 == -2
    assert state.get_player(2).hit_points == 13


def test_describe_effects_returns_ui_readable_power_and_bonus_text() -> None:
    """Structured effect data should be convertible into readable UI strings."""
    power_text = describe_effects(
        (
            EffectDefinition("courage", "self", "power_modifier", 2),
            EffectDefinition("victory", "opponent", "life_loss", 2),
        )
    )
    bonus_text = describe_effects((EffectDefinition("passive", "self", "attack_modifier", 6),))

    assert power_text == "Courage: Power +2 | Victory: Opponent life -2"
    assert bonus_text == "Attack +6"
