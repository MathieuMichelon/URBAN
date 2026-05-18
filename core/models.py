"""Dataclasses representing the pure game state."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import GameStatus, RoundOutcome
from core.errors import (
    CardNotFoundError,
    InvalidCardDefinitionError,
    InvalidGameSetupError,
    InvalidMoveError,
)

SUPPORTED_EFFECT_TRIGGERS = {"passive", "courage", "revenge", "victory", "defeat"}
SUPPORTED_EFFECT_TARGETS = {"self", "opponent", "winner", "loser"}
SUPPORTED_EFFECT_TYPES = {
    "attack_modifier",
    "power_modifier",
    "damage_modifier",
    "life_gain",
    "life_loss",
    "poison",
    "pill_gain",
    "pill_steal",
    "stop_opponent_power",
    "stop_opponent_bonus",
    "protection_bonus",
    "protection_power",
}


def _require_non_empty_string(value: str, field_name: str) -> None:
    """Validate a required string field."""
    if not value.strip():
        raise InvalidCardDefinitionError(f"{field_name} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class EffectCondition:
    """Optional extra condition attached to one effect definition."""

    kind: str
    value: str | int | bool

    def __post_init__(self) -> None:
        """Validate a generic effect condition payload."""
        _require_non_empty_string(self.kind, "Effect condition kind")


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """Data-driven effect definition used by powers and clan bonuses."""

    trigger: str
    target: str
    effect_type: str
    value: int = 0
    minimum: int | None = None
    condition: EffectCondition | None = None

    def __post_init__(self) -> None:
        """Validate a reusable effect definition."""
        if self.trigger not in SUPPORTED_EFFECT_TRIGGERS:
            raise InvalidCardDefinitionError(
                f"Unsupported effect trigger '{self.trigger}'."
            )

        if self.target not in SUPPORTED_EFFECT_TARGETS:
            raise InvalidCardDefinitionError(
                f"Unsupported effect target '{self.target}'."
            )

        if self.effect_type not in SUPPORTED_EFFECT_TYPES:
            raise InvalidCardDefinitionError(
                f"Unsupported effect type '{self.effect_type}'."
            )

        if self.minimum is not None and self.minimum < 0:
            raise InvalidCardDefinitionError("Effect minimum must be greater than or equal to 0.")

        if self.effect_type == "pill_steal" and (self.value < 0 or self.value > 1):
            raise InvalidCardDefinitionError("Pill steal value must be 0 or 1.")


@dataclass(frozen=True, slots=True)
class Card:
    """Define a playable card."""

    id: str
    name: str
    clan: str
    stars: int
    power: int
    damage: int
    power_text: str
    bonus_text: str
    illustration: str
    power_effects: tuple[EffectDefinition, ...] = ()
    bonus_effects: tuple[EffectDefinition, ...] = ()
    info: str | None = None

    def __post_init__(self) -> None:
        """Validate card attributes."""
        _require_non_empty_string(self.id, "Card id")
        _require_non_empty_string(self.name, "Card name")
        _require_non_empty_string(self.clan, "Card clan")
        _require_non_empty_string(self.power_text, "Card power text")
        _require_non_empty_string(self.bonus_text, "Card bonus text")
        _require_non_empty_string(self.illustration, "Card illustration")
        if self.info is not None and not self.info.strip():
            raise InvalidCardDefinitionError("Card info must be a non-empty string when provided.")

        if self.stars not in {1, 2, 3}:
            raise InvalidCardDefinitionError("Card stars must be between 1 and 3.")

        if self.power <= 0:
            raise InvalidCardDefinitionError("Card power must be greater than 0.")

        if self.damage < 0:
            raise InvalidCardDefinitionError("Card damage must be greater than or equal to 0.")


@dataclass(frozen=True, slots=True)
class RoundSelection:
    """Store a player's decision for one round."""

    card_id: str
    pills_committed: int
    overload: bool = False

    def __post_init__(self) -> None:
        """Validate a round selection."""
        if not self.card_id.strip():
            raise InvalidMoveError("Selected card id must be a non-empty string.")

        if self.pills_committed < 0:
            raise InvalidMoveError("Spent pills must be greater than or equal to 0.")


RoundChoice = RoundSelection


@dataclass(slots=True)
class OngoingPoison:
    """Persistent poison applied at end of each round."""

    amount: int
    minimum_hit_points: int = 0

    def __post_init__(self) -> None:
        """Validate poison values."""
        if self.amount <= 0:
            raise InvalidGameSetupError("Poison amount must be greater than 0.")
        if self.minimum_hit_points < 0:
            raise InvalidGameSetupError("Poison minimum hit points cannot be negative.")


@dataclass(slots=True)
class PlayerState:
    """Track resources and cards for one player."""

    player_id: int
    hit_points: int
    pills: int
    hand: list[Card]
    played_card_ids: set[str] = field(default_factory=set)
    active_clan_bonuses: set[str] = field(default_factory=set)
    poison: OngoingPoison | None = None

    def __post_init__(self) -> None:
        """Validate player state on creation."""
        if self.player_id not in {1, 2}:
            raise InvalidGameSetupError("Player id must be 1 or 2.")

        if self.hit_points < 0:
            raise InvalidGameSetupError("Player hit points cannot be negative.")

        if self.pills < 0:
            raise InvalidGameSetupError("Player pills cannot be negative.")

        if len(self.hand) == 0:
            raise InvalidGameSetupError("A player must have at least one card in hand.")

        hand_ids = [card.id for card in self.hand]
        if len(set(hand_ids)) != len(hand_ids):
            raise InvalidGameSetupError("A player's hand cannot contain duplicate card ids.")

    def available_cards(self) -> list[Card]:
        """Return cards that can still be played."""
        return [card for card in self.hand if card.id not in self.played_card_ids]

    def has_card(self, card_id: str) -> bool:
        """Return whether the card belongs to the player's hand."""
        return any(card.id == card_id for card in self.hand)

    def get_card(self, card_id: str) -> Card:
        """Return one card from the player's hand."""
        for card in self.hand:
            if card.id == card_id:
                return card
        raise CardNotFoundError(f"Card '{card_id}' does not belong to player {self.player_id}.")

    def has_played(self, card_id: str) -> bool:
        """Return whether the card was already used."""
        return card_id in self.played_card_ids

    def has_active_bonus_for(self, clan: str) -> bool:
        """Return whether this player's team activates the bonus for a clan."""
        return clan in self.active_clan_bonuses


@dataclass(frozen=True, slots=True)
class RoundResult:
    """Describe the result of a resolved round."""

    round_number: int
    player_1_card_id: str
    player_2_card_id: str
    player_1_attack: int
    player_2_attack: int
    outcome: RoundOutcome
    winner_id: int | None
    loser_id: int | None
    damage_dealt: int
    player_1_pills_committed: int = 0
    player_2_pills_committed: int = 0
    life_swing_player_1: int = 0
    life_swing_player_2: int = 0
    pills_gained_player_1: int = 0
    pills_gained_player_2: int = 0
    player_1_overload: bool = False
    player_2_overload: bool = False
    overload_damage_bonus: int = 0


@dataclass(slots=True)
class GameState:
    """Represent the full state of the current match."""

    players: dict[int, PlayerState]
    current_round: int = 1
    history: list[RoundResult] = field(default_factory=list)
    status: GameStatus = GameStatus.IN_PROGRESS
    winner_id: int | None = None
    starting_initiative_player_id: int = 1

    def __post_init__(self) -> None:
        """Validate the global game state."""
        if set(self.players) != {1, 2}:
            raise InvalidGameSetupError("Game state must contain exactly two players: 1 and 2.")

        if self.current_round < 1:
            raise InvalidGameSetupError("Current round must start at 1 or greater.")

        if self.starting_initiative_player_id not in {1, 2}:
            raise InvalidGameSetupError("Starting initiative player must be player 1 or 2.")

    @property
    def is_over(self) -> bool:
        """Return whether the match has finished."""
        return self.status is not GameStatus.IN_PROGRESS

    @property
    def initiative_player_id(self) -> int:
        """Return which player has courage on the current round."""
        if self.current_round % 2 == 1:
            return self.starting_initiative_player_id
        return 2 if self.starting_initiative_player_id == 1 else 1

    @property
    def previous_round_winner_id(self) -> int | None:
        """Return the winner of the previous round when available."""
        if not self.history:
            return None
        return self.history[-1].winner_id

    def get_player(self, player_id: int) -> PlayerState:
        """Return one player state by identifier."""
        try:
            return self.players[player_id]
        except KeyError as error:
            raise InvalidGameSetupError(f"Player '{player_id}' is missing from the game state.") from error

    def get_opponent(self, player_id: int) -> PlayerState:
        """Return the other player state."""
        return self.players[1 if player_id == 2 else 2]
