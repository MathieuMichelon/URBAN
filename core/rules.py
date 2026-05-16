"""Pure helpers and constants for game rules."""

from core.errors import (
    CardAlreadyPlayedError,
    CardNotFoundError,
    InvalidGameSetupError,
    InvalidMoveError,
    NotEnoughPillsError,
)
from core.models import Card, GameState, PlayerState, RoundSelection

STARTING_HIT_POINTS = 20
STARTING_PILLS = 12
HAND_SIZE = 4
MAX_ROUNDS = 4


def compute_attack(card: Card, pills_committed: int) -> int:
    """Compute attack from card power and spent pills."""
    return card.power * pills_committed


def validate_hand(hand: list[Card]) -> None:
    """Validate a starting hand."""
    if len(hand) != HAND_SIZE:
        raise InvalidGameSetupError(f"A hand must contain exactly {HAND_SIZE} cards.")

    ids = [card.id for card in hand]
    if len(set(ids)) != len(ids):
        raise InvalidGameSetupError("A hand cannot contain duplicate card identifiers.")


def validate_unique_hands(player_1_hand: list[Card], player_2_hand: list[Card]) -> None:
    """Keep a compatibility helper; mirrored draft pools may legally share cards."""
    validate_hand(player_1_hand)
    validate_hand(player_2_hand)


def validate_game_state(state: GameState) -> None:
    """Validate generic state invariants before resolving a round."""
    if state.current_round > MAX_ROUNDS:
        raise InvalidGameSetupError(f"Current round cannot exceed {MAX_ROUNDS}.")


def validate_round_selection(player: PlayerState, selection: RoundSelection) -> None:
    """Validate one player's round choice."""
    if selection.pills_committed > player.pills:
        raise NotEnoughPillsError("Player does not have enough pills.")

    if not player.has_card(selection.card_id):
        raise CardNotFoundError(
            f"Card '{selection.card_id}' does not belong to player {player.player_id}."
        )

    if player.has_played(selection.card_id):
        raise CardAlreadyPlayedError(
            f"Card '{selection.card_id}' has already been played by player {player.player_id}."
        )


validate_round_choice = validate_round_selection
