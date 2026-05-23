"""Focused tests for the centralized multiplayer room state machine."""

from collections import Counter
from itertools import combinations

import pytest

from core.draft import DRAFT_OFFER_SIZE, TEAM_STAR_CAP
from core.errors import InvalidMoveError
from rooms.state_machine import CLAN_SELECTION_SIZE, RoomStateMachine
from rooms.states import MatchState, PlayerRoomState


def _first_valid_team_ids(offer) -> list[str]:
    """Return the first legal 4-card team from a draft offer."""
    for team in combinations(offer, 4):
        if sum(card.stars for card in team) <= TEAM_STAR_CAP:
            return [card.id for card in team]
    raise AssertionError("Expected at least one legal team in the draft offer.")


def _first_invalid_star_cap_team_ids(offer) -> list[str]:
    """Return the first 4-card team that exceeds the legal star cap."""
    for team in combinations(offer, 4):
        if sum(card.stars for card in team) > TEAM_STAR_CAP:
            return [card.id for card in team]
    raise AssertionError("Expected at least one illegal over-cap team in the draft offer.")


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


def _default_clan_ids(room) -> list[str]:
    """Return the first three clan ids from the available room options."""
    return [clan.id for clan in room.clan_options[:CLAN_SELECTION_SIZE]]


def _alternate_clan_ids(room) -> list[str]:
    """Return a different three-clan combination for player two."""
    return [clan.id for clan in room.clan_options[2 : 2 + CLAN_SELECTION_SIZE]]


def _start_draft(machine: RoomStateMachine, room, *, player_1_clans: list[str] | None = None, player_2_clans: list[str] | None = None) -> None:
    """Advance a room from lobby into the drafting phase."""
    machine.join_room(room, player_name="Bob")
    machine.select_clans(room, player_id=1, clan_ids=player_1_clans or _default_clan_ids(room))
    machine.select_clans(room, player_id=2, clan_ids=player_2_clans or _default_clan_ids(room))


def test_room_initialization_starts_in_waiting_for_players(sample_cards) -> None:
    """The first player should land in lobby state and the room should wait for a second player."""
    machine = RoomStateMachine()

    room, player = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")

    assert room.match_state is MatchState.WAITING_FOR_PLAYERS
    assert player.state is PlayerRoomState.IN_LOBBY
    assert room.game_state is None


def test_joining_second_player_starts_clan_selection(sample_cards) -> None:
    """Adding the second player should open the pre-draft clan selection phase."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")

    outcome = machine.join_room(room, player_name="Bob")

    assert outcome.game_started is False
    assert room.match_state is MatchState.CLAN_SELECTION
    assert room.players[1].state is PlayerRoomState.SELECTING
    assert room.players[2].state is PlayerRoomState.SELECTING
    assert room.selected_clans_by_player == {1: [], 2: []}
    assert room.clan_selection_locked == {1: False, 2: False}
    assert room.draft_phases == {}


def test_clan_selection_rejects_less_than_three_clans(sample_cards) -> None:
    """A player must lock exactly three clans before the draft can start."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    machine.join_room(room, player_name="Bob")

    with pytest.raises(InvalidMoveError, match="Select exactly 3 clans"):
        machine.select_clans(room, player_id=1, clan_ids=_default_clan_ids(room)[:2])


def test_clan_selection_rejects_unknown_clans(sample_cards) -> None:
    """Only known clan ids should be accepted by the room logic."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    machine.join_room(room, player_name="Bob")

    with pytest.raises(InvalidMoveError, match="Unknown clan selection"):
        machine.select_clans(room, player_id=1, clan_ids=["solaires", "corsaires_du_port", "unknown"])


def test_clan_selection_starts_draft_only_after_both_players_lock(sample_cards) -> None:
    """The draft should begin only after both players validate three clans."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    machine.join_room(room, player_name="Bob")

    started = machine.select_clans(room, player_id=1, clan_ids=_default_clan_ids(room))

    assert started is False
    assert room.match_state is MatchState.CLAN_SELECTION
    assert room.players[1].state is PlayerRoomState.LOCKED
    assert room.players[2].state is PlayerRoomState.SELECTING

    started = machine.select_clans(room, player_id=2, clan_ids=_default_clan_ids(room))

    assert started is True
    assert room.match_state is MatchState.DRAFTING
    assert set(room.draft_phases) == {1, 2}
    assert len(room.draft_phases[1].offer) == DRAFT_OFFER_SIZE
    assert len(room.draft_phases[2].offer) == DRAFT_OFFER_SIZE


def test_draft_offers_are_filtered_by_each_players_selected_clans(sample_cards) -> None:
    """Each player should draft only from their own three selected clans."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    _start_draft(
        machine,
        room,
        player_1_clans=_default_clan_ids(room),
        player_2_clans=_alternate_clan_ids(room),
    )

    player_1_offer_clans = {card.clan for card in room.draft_phases[1].offer}
    player_2_offer_clans = {card.clan for card in room.draft_phases[2].offer}
    clan_name_by_id = {clan.id: clan.name for clan in room.clan_options}
    expected_player_1_clans = {clan_name_by_id[clan_id] for clan_id in _default_clan_ids(room)}
    expected_player_2_clans = {clan_name_by_id[clan_id] for clan_id in _alternate_clan_ids(room)}

    assert player_1_offer_clans <= expected_player_1_clans
    assert player_2_offer_clans <= expected_player_2_clans
    assert player_1_offer_clans != player_2_offer_clans


def test_first_draft_confirmation_keeps_room_in_drafting(sample_cards) -> None:
    """One locked draft team should keep the room in drafting until the second player locks too."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    _start_draft(machine, room)

    offer = room.draft_phases[1].offer
    for card_id in _first_valid_team_ids(offer):
        machine.select_card(room, player_id=1, card_id=card_id)

    outcome = machine.confirm_selection(room, player_id=1)

    assert outcome.round_result is None
    assert room.match_state is MatchState.DRAFTING
    assert room.players[1].state is PlayerRoomState.LOCKED
    assert room.players[2].state is PlayerRoomState.SELECTING


def test_draft_snapshot_shows_bonus_preview_from_private_offer(sample_cards) -> None:
    """The authoritative snapshot should expose bonus preview data from each player's filtered offer."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    _start_draft(machine, room)

    team_ids = _team_ids_with_active_bonus(room.draft_phases[1].offer)
    _select_team(machine, room, player_id=1, card_ids=team_ids)

    snapshot_1 = machine.snapshot_for(room, local_player_id=1)
    snapshot_2 = machine.snapshot_for(room, local_player_id=2)

    player_1_from_opponent_view = next(player for player in snapshot_2.players if player.player_id == 1)
    assert player_1_from_opponent_view.draft_is_valid is True
    active_clans = set(player_1_from_opponent_view.active_clan_bonuses)
    assert active_clans
    offer_by_id = {card.id: card for card in snapshot_1.draft_offer}
    assert any(card.bonus_active is True for card in player_1_from_opponent_view.draft_selected_cards)
    assert all(
        card.bonus_active is (offer_by_id[card.id].clan in active_clans)
        for card in player_1_from_opponent_view.draft_selected_cards
    )


def test_two_valid_locked_draft_teams_start_online_match(sample_cards) -> None:
    """Locking two legal teams should start the live match with clan bonuses resolved."""
    machine = RoomStateMachine()
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    _start_draft(machine, room)

    team_ids_1 = _team_ids_with_active_bonus(room.draft_phases[1].offer)
    team_ids_2 = _team_ids_with_active_bonus(room.draft_phases[2].offer)
    _select_team(machine, room, player_id=1, card_ids=team_ids_1)
    _select_team(machine, room, player_id=2, card_ids=team_ids_2)

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
    room, _ = machine.create_room("ROOM01", cards=sample_cards, player_name="Alice")
    _start_draft(machine, room)

    _select_team(
        machine,
        room,
        player_id=1,
        card_ids=_first_invalid_star_cap_team_ids(room.draft_phases[1].offer),
    )

    with pytest.raises(InvalidMoveError, match="cannot exceed 8 stars"):
        machine.confirm_selection(room, player_id=1)


def test_disconnect_during_active_flow_declares_opponent_winner(sample_cards) -> None:
    """Disconnecting after both players joined should explicitly end the room by abandonment."""
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
