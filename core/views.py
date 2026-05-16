"""Serializable projections of game state for UI or future networking."""

from __future__ import annotations

from collections.abc import Iterable

from core.draft import compute_team_stars
from core.models import Card, GameState, PlayerState
from core.serialization import serialize_card, serialize_round_result


def build_game_snapshot(
    state: GameState,
    *,
    perspective_player_id: int | None = None,
    pending_player_ids: Iterable[int] = (),
    reveal_hidden: bool = False,
) -> dict[str, object]:
    """Build a serializable snapshot of the current match state."""
    return {
        "current_round": state.current_round,
        "status": state.status.value,
        "winner_id": state.winner_id,
        "pending_player_ids": sorted(set(pending_player_ids)),
        "players": {
            str(player_id): build_player_snapshot(
                state.get_player(player_id),
                perspective_player_id=perspective_player_id,
                reveal_hidden=reveal_hidden,
            )
            for player_id in (1, 2)
        },
        "history": [serialize_round_result(result) for result in state.history],
    }


def build_player_snapshot(
    player: PlayerState,
    *,
    perspective_player_id: int | None = None,
    reveal_hidden: bool = False,
) -> dict[str, object]:
    """Build a serializable snapshot of one player state."""
    owns_hand = perspective_player_id == player.player_id

    return {
        "player_id": player.player_id,
        "hit_points": player.hit_points,
        "pills": player.pills,
        "team_stars": compute_team_stars(player.hand),
        "active_clan_bonuses": sorted(player.active_clan_bonuses),
        "played_card_ids": sorted(player.played_card_ids),
        "hand": [
            _serialize_hand_slot(
                slot_index=index,
                card=card,
                played=card.id in player.played_card_ids,
                reveal_card=reveal_hidden or owns_hand or card.id in player.played_card_ids,
                bonus_active=card.clan in player.active_clan_bonuses,
            )
            for index, card in enumerate(player.hand)
        ],
    }


def _serialize_hand_slot(
    *,
    slot_index: int,
    card: Card,
    played: bool,
    reveal_card: bool,
    bonus_active: bool,
) -> dict[str, object]:
    """Serialize one hand slot, hiding secret information when required."""
    return {
        "slot_index": slot_index,
        "played": played,
        "bonus_active": bonus_active if reveal_card else None,
        "card": serialize_card(card) if reveal_card else None,
    }
