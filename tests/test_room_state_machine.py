"""Focused tests for the centralized multiplayer room state machine."""

from collections import Counter
from itertools import combinations

import pytest

from core.draft import TEAM_STAR_CAP
from core.errors import InvalidMoveError
from rooms.state_machine import RoomStateMachine
from rooms.states import MatchState, PlayerRoomState


def test_room_initialization_starts_in_waiting_for_players(sample_cards) -> None:
    """The first player should land in lobby state and the room should wait for a second player."""
    machine = RoomStateMachine()

    room, player = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")

    assert room.match_state is MatchState.WAITING_FOR_PLAYERS
    assert player.state is PlayerRoomState.IN_LOBBY
    assert room.game_state is None


def _first_valid_team_ids(offer) -> list[str]:
    """Return the first legal 4-card team from a draft offer."""
    for team in combinations(offer, 4):
        if sum(card.stars for card in team) <= TEAM_STAR_CAP:
            return [card.id for card in team]
    raise AssertionError("Expected at least one legal team in the draft offer.")


def _build_online_test_roster(sample_cards, card_ids: list[str]):
    """Return a deterministic 10-card roster used to stabilize online draft tests."""
    cards_by_id = {card.id: card for card in sample_cards}
    return [cards_by_id[card_id] for card_id in card_ids]


def _team_ids_with_active_bonus(offer) -> list[str]:
    """Return the first legal 4-card team that activates at least one clan bonus."""
    for team in combinations(offer, 4):
        if sum(card.stars for card in team) > TEAM_STAR_CAP:
            continue
        if any(count >= 2 for count in Counter(card.clan for card in team).values()):
            return [card.id for card in team]
    raise AssertionError("Expected the draft offer to contain a legal team with an active clan bonus.")


def _select_team(machine: RoomStateMachine, room, *, player_id: int, card_ids: list[str]) -> None:
    """Select one full team in draft order."""
    for card_id in card_ids:
        machine.select_card(room, player_id=player_id, card_id=card_id)


def test_joining_second_player_starts_drafting(sample_cards) -> None:
    """Adding the second player should start the draft and move both players to selecting."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")

    outcome = machine.join_room(room, player_name="Bob")

    assert outcome.game_started is False
    assert room.match_state is MatchState.DRAFTING
    assert room.players[1].state is PlayerRoomState.SELECTING
    assert room.players[2].state is PlayerRoomState.SELECTING
    assert room.draft_phase is not None
    assert len(room.draft_phase.offer) == 10


def test_first_draft_confirmation_keeps_room_in_drafting(sample_cards) -> None:
    """One locked draft team should keep the room in drafting until the second player locks too."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    machine.join_room(room, player_name="Bob")
    assert room.draft_phase is not None

    for card_id in _first_valid_team_ids(room.draft_phase.offer):
        machine.select_card(room, player_id=1, card_id=card_id)

    outcome = machine.confirm_selection(room, player_id=1)

    assert outcome.round_result is None
    assert room.match_state is MatchState.DRAFTING
    assert room.players[1].state is PlayerRoomState.LOCKED
    assert room.players[2].state is PlayerRoomState.SELECTING


def test_draft_snapshot_shows_shared_offer_and_bonus_preview(sample_cards) -> None:
    """Both players should see the same draft pool and synchronized bonus previews from the authoritative room."""
    machine = RoomStateMachine()
    room, _ = machine.create_room(
        "ROOM01",
        cards=_build_online_test_roster(
            sample_cards,
            [
                "glitch",
                "pix",
                "nox",
                "vibe",
                "rivet",
                "boulon",
                "cendre",
                "nita",
                "mousse",
                "rosee",
            ],
        ),
        player_name="Alice",
    )
    machine.join_room(room, player_name="Bob")
    assert room.draft_phase is not None

    team_ids = _team_ids_with_active_bonus(room.draft_phase.offer)
    _select_team(machine, room, player_id=1, card_ids=team_ids)

    snapshot_1 = machine.snapshot_for(room, local_player_id=1)
    snapshot_2 = machine.snapshot_for(room, local_player_id=2)

    assert [card.id for card in snapshot_1.draft_offer] == [card.id for card in snapshot_2.draft_offer]
    player_1_from_opponent_view = next(player for player in snapshot_2.players if player.player_id == 1)
    assert player_1_from_opponent_view.draft_is_valid is True
    active_clans = set(player_1_from_opponent_view.active_clan_bonuses)
    assert active_clans
    offer_by_id = {card.id: card for card in snapshot_2.draft_offer}
    assert any(card.bonus_active is True for card in player_1_from_opponent_view.draft_selected_cards)
    assert all(
        card.bonus_active is (offer_by_id[card.id].clan in active_clans)
        for card in player_1_from_opponent_view.draft_selected_cards
    )


def test_two_valid_locked_draft_teams_start_online_match(sample_cards) -> None:
    """Locking two legal teams should start the live match with clan bonuses resolved from the shared core engine."""
    machine = RoomStateMachine()
    room, _ = machine.create_room(
        "ROOM01",
        cards=_build_online_test_roster(
            sample_cards,
            [
                "glitch",
                "pix",
                "nox",
                "vibe",
                "rivet",
                "boulon",
                "cendre",
                "nita",
                "mousse",
                "rosee",
            ],
        ),
        player_name="Alice",
    )
    machine.join_room(room, player_name="Bob")
    assert room.draft_phase is not None

    team_ids = _team_ids_with_active_bonus(room.draft_phase.offer)
    _select_team(machine, room, player_id=1, card_ids=team_ids)
    _select_team(machine, room, player_id=2, card_ids=team_ids)

    machine.confirm_selection(room, player_id=1)
    outcome = machine.confirm_selection(room, player_id=2)

    assert outcome.game_started is True
    assert room.match_state is MatchState.ROUND_SELECTION
    assert room.game_state is not None
    assert room.game_state.get_player(1).active_clan_bonuses
    assert room.game_state.get_player(2).active_clan_bonuses


def test_invalid_star_cap_team_is_rejected_during_online_draft(sample_cards) -> None:
    """The authoritative room must reject online draft locks above the shared 8-star cap."""
    machine = RoomStateMachine()
    room, _ = machine.create_room(
        "ROOM01",
        cards=_build_online_test_roster(
            sample_cards,
            [
                "nova_byte",
                "null",
                "atlas",
                "ferrox",
                "kiro",
                "druun",
                "maelis",
                "torque",
                "magna",
                "sylfa",
            ],
        ),
        player_name="Alice",
    )
    machine.join_room(room, player_name="Bob")

    _select_team(
        machine,
        room,
        player_id=1,
        card_ids=["nova_byte", "null", "atlas", "ferrox"],
    )

    with pytest.raises(InvalidMoveError, match="cannot exceed 8 stars"):
        machine.confirm_selection(room, player_id=1)


def test_disconnect_during_active_game_declares_opponent_winner(sample_cards) -> None:
    """Disconnecting during an active match should explicitly end the game by abandonment."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    machine.join_room(room, player_name="Bob")

    outcome = machine.disconnect_player(room, player_id=2)

    assert outcome.winner_by_abandon == 1
    assert room.match_state is MatchState.GAME_OVER
    assert room.end_reason == "opponent_disconnected"
    assert room.players[2].state is PlayerRoomState.DISCONNECTED


def test_resume_player_session_restores_explicit_player_state(sample_cards) -> None:
    """A valid session token should restore the same player seat after a reload."""
    machine = RoomStateMachine()
    room, player_1 = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    machine.disconnect_player(room, player_id=1)

    resumed = machine.join_room(room, player_name="Alice", session_token=player_1.session_token)

    assert resumed.resumed is True
    assert resumed.player.player_id == 1
    assert resumed.player.state is PlayerRoomState.IN_LOBBY
