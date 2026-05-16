"""Centralized room and player state machines for the online mode."""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets

from core.draft import TEAM_SIZE, TEAM_STAR_CAP, DraftPhase, build_draft_offer, compute_team_stars
from core.engine import GameEngine
from core.enums import GameStatus
from core.errors import InvalidMoveError, NotEnoughPillsError, SelectionAlreadySubmittedError
from core.models import Card, GameState, RoundResult, RoundSelection
from core.rules import validate_round_selection
from core.serialization import serialize_round_result
from net.protocol import CardPayload, PlayerStatePayload, RoundResultPayload, StateSnapshotPayload
from rooms.states import MatchState, PlayerRoomState


class RoomStateError(Exception):
    """Base exception for authoritative room state machine errors."""


class RoomNotFoundError(RoomStateError):
    """Raised when a room identifier does not exist."""


class RoomFullError(RoomStateError):
    """Raised when a room already contains two active seats."""


class RoomClosedError(RoomStateError):
    """Raised when a room no longer accepts the attempted action."""


class PlayerNotInRoomError(RoomStateError):
    """Raised when a player id or session token is not valid for the room."""


@dataclass(slots=True)
class DraftSelection:
    """Current in-progress round selection owned by one player."""

    card_id: str | None = None
    pills_committed: int = 0


@dataclass(slots=True)
class RoomPlayer:
    """Runtime metadata and state for one room participant."""

    player_id: int
    name: str
    session_token: str
    state: PlayerRoomState = PlayerRoomState.CONNECTED


@dataclass(slots=True)
class OnlineRoom:
    """Authoritative room aggregate used by the backend."""

    room_id: str
    cards: list[Card]
    engine: GameEngine
    players: dict[int, RoomPlayer] = field(default_factory=dict)
    draft_phase: DraftPhase | None = None
    game_state: GameState | None = None
    match_state: MatchState = MatchState.WAITING_FOR_PLAYERS
    round_drafts: dict[int, DraftSelection] = field(default_factory=dict)
    end_reason: str | None = None
    abandonment_winner_id: int | None = None

    @property
    def initiative_player_id(self) -> int | None:
        """Return which player must lock first for the current round."""
        if self.game_state is None:
            return None
        return self.game_state.initiative_player_id


@dataclass(frozen=True, slots=True)
class JoinRoomOutcome:
    """Describe the result of a create/join/resume action."""

    player: RoomPlayer
    resumed: bool
    game_started: bool


@dataclass(frozen=True, slots=True)
class ConfirmSelectionOutcome:
    """Describe the effect of confirming one draft or round selection."""

    ready_player_id: int
    round_result: RoundResult | None
    game_finished: bool
    game_started: bool = False
    draft_completed: bool = False


@dataclass(frozen=True, slots=True)
class DisconnectOutcome:
    """Describe the effect of a player disconnect on the authoritative room."""

    disconnected_player: RoomPlayer | None
    opponent_player_id: int | None
    room_cancelled: bool
    winner_by_abandon: int | None


class RoomStateMachine:
    """Single place where every room and player transition is defined."""

    def create_room(self, room_id: str, *, cards: list[Card], player_name: str) -> tuple[OnlineRoom, RoomPlayer]:
        """Create a new room with its first player in lobby state."""
        room = OnlineRoom(room_id=room_id, cards=list(cards), engine=GameEngine())
        player = self._create_player(player_id=1, player_name=player_name)
        room.players[player.player_id] = player
        self._transition_player(player, PlayerRoomState.IN_LOBBY)
        return room, player

    def join_room(self, room: OnlineRoom, *, player_name: str, session_token: str | None = None) -> JoinRoomOutcome:
        """Join an existing room or resume a previous session."""
        if session_token is not None:
            resumed_player = self._resume_player(room, player_name=player_name, session_token=session_token)
            return JoinRoomOutcome(player=resumed_player, resumed=True, game_started=room.game_state is not None)

        if len(room.players) >= 2:
            raise RoomFullError(f"Room '{room.room_id}' is already full.")
        if room.match_state is not MatchState.WAITING_FOR_PLAYERS:
            raise RoomClosedError(f"Room '{room.room_id}' is no longer accepting new players.")

        player_id = 1 if 1 not in room.players else 2
        player = self._create_player(player_id=player_id, player_name=player_name)
        room.players[player.player_id] = player
        self._transition_player(player, PlayerRoomState.IN_LOBBY)

        if len(room.players) == 2:
            self._start_draft(room)

        return JoinRoomOutcome(player=player, resumed=False, game_started=room.game_state is not None)

    def select_card(self, room: OnlineRoom, *, player_id: int, card_id: str) -> None:
        """Update one player's draft card or round card based on the current phase."""
        player = self._player(room, player_id)

        if room.match_state is MatchState.DRAFTING:
            self._require_player_state(player, {PlayerRoomState.SELECTING})
            if room.draft_phase is None:
                raise RoomClosedError("Draft phase is not initialized.")
            room.draft_phase.toggle_card(player_id, card_id)
            return

        self._require_match_state(room, {MatchState.ROUND_SELECTION, MatchState.ROUND_LOCKED})
        self._require_player_state(player, {PlayerRoomState.SELECTING})

        player_state = self._game_player(room, player_id)
        if not player_state.has_card(card_id):
            raise InvalidMoveError(f"Card '{card_id}' does not belong to player {player_id}.")
        if player_state.has_played(card_id):
            raise InvalidMoveError(f"Card '{card_id}' has already been played.")

        room.round_drafts[player_id].card_id = card_id

    def set_pills(self, room: OnlineRoom, *, player_id: int, pills: int) -> None:
        """Update the drafted pills during round selection phases."""
        self._require_match_state(room, {MatchState.ROUND_SELECTION, MatchState.ROUND_LOCKED})
        player = self._player(room, player_id)
        self._require_player_state(player, {PlayerRoomState.SELECTING})

        player_state = self._game_player(room, player_id)
        if pills < 0 or pills > player_state.pills:
            raise NotEnoughPillsError("Player does not have enough pills.")

        room.round_drafts[player_id].pills_committed = pills

    def confirm_selection(self, room: OnlineRoom, *, player_id: int) -> ConfirmSelectionOutcome:
        """Lock one selection and advance draft or round flow."""
        player = self._player(room, player_id)

        if room.match_state is MatchState.DRAFTING:
            return self._confirm_draft(room, player)

        self._require_match_state(room, {MatchState.ROUND_SELECTION, MatchState.ROUND_LOCKED})
        self._require_player_state(player, {PlayerRoomState.SELECTING})

        initiative_player_id = room.initiative_player_id
        if initiative_player_id is None:
            raise RoomClosedError("The game has not started yet.")

        if player_id != initiative_player_id and self._player(room, initiative_player_id).state is not PlayerRoomState.LOCKED:
            raise InvalidMoveError("The initiative player must confirm first.")

        draft = room.round_drafts[player_id]
        if draft.card_id is None:
            raise InvalidMoveError("Select a card before confirming the round.")

        selection = RoundSelection(card_id=draft.card_id, pills_committed=draft.pills_committed)
        validate_round_selection(self._game_player(room, player_id), selection)

        self._transition_player(player, PlayerRoomState.LOCKED)
        room.end_reason = None

        if not all(self._player(room, expected_id).state is PlayerRoomState.LOCKED for expected_id in (1, 2)):
            self._transition_match(room, MatchState.ROUND_LOCKED)
            return ConfirmSelectionOutcome(ready_player_id=player_id, round_result=None, game_finished=False)

        self._transition_match(room, MatchState.ROUND_RESOLUTION)
        result = room.engine.play_round(
            state=room.game_state,
            player_1_selection=self._selection_from_draft(room, 1),
            player_2_selection=self._selection_from_draft(room, 2),
        )

        for room_player in room.players.values():
            if room_player.state is not PlayerRoomState.DISCONNECTED:
                self._transition_player(room_player, PlayerRoomState.IN_ROOM)

        if room.game_state is not None and room.game_state.is_over:
            self._finish_game(room, end_reason="completed")
            return ConfirmSelectionOutcome(ready_player_id=player_id, round_result=result, game_finished=True)

        self._begin_round_selection(room)
        return ConfirmSelectionOutcome(ready_player_id=player_id, round_result=result, game_finished=False)

    def disconnect_player(self, room: OnlineRoom, *, player_id: int) -> DisconnectOutcome:
        """Apply the explicit disconnect policy for lobby, draft, and live games."""
        player = room.players.get(player_id)
        if player is None:
            return DisconnectOutcome(
                disconnected_player=None,
                opponent_player_id=None,
                room_cancelled=False,
                winner_by_abandon=None,
            )

        self._transition_player(player, PlayerRoomState.DISCONNECTED)
        opponent_player_id = 1 if player_id == 2 and 1 in room.players else 2 if player_id == 1 and 2 in room.players else None

        if room.match_state is MatchState.WAITING_FOR_PLAYERS:
            return DisconnectOutcome(
                disconnected_player=player,
                opponent_player_id=opponent_player_id,
                room_cancelled=False,
                winner_by_abandon=None,
            )

        if room.match_state is not MatchState.GAME_OVER and opponent_player_id is not None:
            self._declare_winner_by_abandon(room, winner_id=opponent_player_id)
            self._finish_game(room, end_reason="opponent_disconnected", winner_id=opponent_player_id)
            return DisconnectOutcome(
                disconnected_player=player,
                opponent_player_id=opponent_player_id,
                room_cancelled=False,
                winner_by_abandon=opponent_player_id,
            )

        return DisconnectOutcome(
            disconnected_player=player,
            opponent_player_id=opponent_player_id,
            room_cancelled=False,
            winner_by_abandon=None,
        )

    def snapshot_for(self, room: OnlineRoom, *, local_player_id: int) -> StateSnapshotPayload:
        """Build the only authoritative client-facing snapshot."""
        players_payload: list[PlayerStatePayload] = []
        history: list[RoundResultPayload] = []
        draft_offer: list[CardPayload] = []
        draft_locked_player_ids: list[int] = []

        if room.game_state is not None:
            history = [
                RoundResultPayload.model_validate(serialize_round_result(result))
                for result in room.game_state.history
            ]

        if room.draft_phase is not None:
            draft_offer = [self._card_payload(card, bonus_active=False) for card in room.draft_phase.offer]
            draft_locked_player_ids = [
                player_id
                for player_id, seat in room.draft_phase.seats.items()
                if seat.locked
            ]

        for player_id in sorted(room.players):
            room_player = room.players[player_id]
            game_player = room.game_state.get_player(player_id) if room.game_state is not None else None
            hand: list[CardPayload] = []
            played_card_ids: list[str] = []
            hit_points: int | None = None
            pills: int | None = None
            team_stars: int | None = None
            active_clan_bonuses: list[str] = []
            draft_selected_cards: list[CardPayload] = []
            draft_locked = False
            draft_is_valid = False

            if room.draft_phase is not None:
                selected_cards = room.draft_phase.selected_cards(player_id)
                validation = room.draft_phase.validation_for(player_id)
                preview_by_id = {
                    preview.card_id: preview
                    for preview in validation.selected_card_previews
                }
                draft_selected_cards = [
                    self._card_payload(
                        card,
                        bonus_active=preview_by_id.get(card.id).bonus_active if card.id in preview_by_id else False,
                    )
                    for card in selected_cards
                ]
                draft_locked = room.draft_phase.seats[player_id].locked
                draft_is_valid = validation.is_valid
                if room.game_state is None:
                    team_stars = validation.total_stars
                    active_clan_bonuses = list(validation.active_clans)

            if game_player is not None:
                hand = [
                    self._card_payload(card, bonus_active=card.clan in game_player.active_clan_bonuses)
                    for card in game_player.hand
                ]
                played_card_ids = sorted(game_player.played_card_ids)
                hit_points = game_player.hit_points
                pills = game_player.pills
                team_stars = compute_team_stars(game_player.hand)
                active_clan_bonuses = sorted(game_player.active_clan_bonuses)

            players_payload.append(
                PlayerStatePayload(
                    player_id=player_id,
                    name=room_player.name,
                    connected=room_player.state is not PlayerRoomState.DISCONNECTED,
                    player_state=room_player.state.value,
                    hit_points=hit_points,
                    pills=pills,
                    hand=hand,
                    played_card_ids=played_card_ids,
                    team_stars=team_stars,
                    active_clan_bonuses=active_clan_bonuses,
                    ready=room_player.state is PlayerRoomState.LOCKED,
                    draft_card_id=self._visible_round_card_id(room, target_player_id=player_id, perspective_player_id=local_player_id),
                    drafted_pills=room.round_drafts.get(player_id, DraftSelection()).pills_committed if player_id == local_player_id else None,
                    draft_selected_cards=draft_selected_cards,
                    draft_locked=draft_locked,
                    draft_is_valid=draft_is_valid,
                )
            )

        return StateSnapshotPayload(
            match_state=room.match_state.value,
            game_started=room.game_state is not None,
            local_player_id=local_player_id,
            current_round=room.game_state.current_round if room.game_state is not None else None,
            game_status=room.game_state.status.value if room.game_state is not None else None,
            winner_id=room.game_state.winner_id if room.game_state is not None else room.abandonment_winner_id,
            initiative_player_id=room.initiative_player_id,
            pending_player_ids=sorted(
                player_id
                for player_id, room_player in room.players.items()
                if room_player.state is PlayerRoomState.LOCKED
            ),
            draft_offer=draft_offer,
            draft_locked_player_ids=draft_locked_player_ids,
            draft_team_size=TEAM_SIZE if room.draft_phase is not None else None,
            draft_star_cap=TEAM_STAR_CAP if room.draft_phase is not None else None,
            players=players_payload,
            history=history,
            end_reason=room.end_reason,
        )

    def _confirm_draft(self, room: OnlineRoom, player: RoomPlayer) -> ConfirmSelectionOutcome:
        """Lock one drafted team and start the match when both teams are ready."""
        self._require_match_state(room, {MatchState.DRAFTING})
        self._require_player_state(player, {PlayerRoomState.SELECTING})

        if room.draft_phase is None:
            raise RoomClosedError("Draft phase is not initialized.")

        room.draft_phase.lock_team(player.player_id)
        self._transition_player(player, PlayerRoomState.LOCKED)

        if not room.draft_phase.teams_ready():
            return ConfirmSelectionOutcome(
                ready_player_id=player.player_id,
                round_result=None,
                game_finished=False,
                game_started=False,
                draft_completed=False,
            )

        self._start_match_from_draft(room)
        return ConfirmSelectionOutcome(
            ready_player_id=player.player_id,
            round_result=None,
            game_finished=False,
            game_started=True,
            draft_completed=True,
        )

    def _resume_player(self, room: OnlineRoom, *, player_name: str, session_token: str) -> RoomPlayer:
        """Rebind a disconnected player session after a page reload."""
        for player in room.players.values():
            if player.session_token != session_token:
                continue

            if player_name and player.name != player_name:
                player.name = player_name

            if room.match_state is MatchState.WAITING_FOR_PLAYERS:
                self._transition_player(player, PlayerRoomState.IN_LOBBY)
            elif room.match_state is MatchState.DRAFTING:
                draft_phase = room.draft_phase
                if draft_phase is not None and draft_phase.seats[player.player_id].locked:
                    self._transition_player(player, PlayerRoomState.LOCKED)
                else:
                    self._transition_player(player, PlayerRoomState.SELECTING)
            elif room.match_state is MatchState.GAME_OVER:
                self._transition_player(player, PlayerRoomState.IN_ROOM)
            else:
                if room.players[player.player_id].state is PlayerRoomState.LOCKED:
                    self._transition_player(player, PlayerRoomState.LOCKED)
                else:
                    self._transition_player(player, PlayerRoomState.SELECTING)
            return player

        raise PlayerNotInRoomError("Session token is not valid for this room.")

    def _start_draft(self, room: OnlineRoom) -> None:
        """Create a shared draft offer and move both players into draft selection."""
        room.draft_phase = DraftPhase(build_draft_offer(room.cards, seed=room.room_id))
        self._transition_match(room, MatchState.DRAFTING)
        for player in room.players.values():
            self._transition_player(player, PlayerRoomState.SELECTING)

    def _start_match_from_draft(self, room: OnlineRoom) -> None:
        """Create the live game state from both locked draft teams."""
        if room.draft_phase is None:
            raise RoomClosedError("Draft phase is not initialized.")

        teams = room.draft_phase.build_locked_teams()
        room.game_state = room.engine.create_game(player_1_hand=teams[1], player_2_hand=teams[2])
        room.draft_phase = None

        for player in room.players.values():
            if player.state is not PlayerRoomState.DISCONNECTED:
                self._transition_player(player, PlayerRoomState.IN_ROOM)
        self._begin_round_selection(room)

    def _begin_round_selection(self, room: OnlineRoom) -> None:
        """Enter the round selection phase and reset both round drafts."""
        room.round_drafts = {1: DraftSelection(), 2: DraftSelection()}
        self._transition_match(room, MatchState.ROUND_SELECTION)
        for player in room.players.values():
            if player.state is not PlayerRoomState.DISCONNECTED:
                self._transition_player(player, PlayerRoomState.SELECTING)

    def _finish_game(self, room: OnlineRoom, *, end_reason: str, winner_id: int | None = None) -> None:
        """Enter the terminal game-over state."""
        room.end_reason = end_reason
        room.abandonment_winner_id = winner_id
        self._transition_match(room, MatchState.GAME_OVER)
        for player in room.players.values():
            if player.state is not PlayerRoomState.DISCONNECTED:
                self._transition_player(player, PlayerRoomState.IN_ROOM)

    def _declare_winner_by_abandon(self, room: OnlineRoom, *, winner_id: int) -> None:
        """Project a forfeit win into the underlying authoritative game state."""
        room.abandonment_winner_id = winner_id
        if room.game_state is None:
            return

        room.game_state.winner_id = winner_id
        room.game_state.status = GameStatus.PLAYER_1_WON if winner_id == 1 else GameStatus.PLAYER_2_WON

    def _transition_match(self, room: OnlineRoom, new_state: MatchState) -> None:
        """Centralized match-state transition helper."""
        current = room.match_state
        if current is new_state:
            return

        allowed_transitions = {
            MatchState.WAITING_FOR_PLAYERS: {MatchState.DRAFTING, MatchState.GAME_OVER},
            MatchState.DRAFTING: {MatchState.ROUND_SELECTION, MatchState.GAME_OVER},
            MatchState.ROUND_SELECTION: {MatchState.ROUND_LOCKED, MatchState.ROUND_RESOLUTION, MatchState.GAME_OVER},
            MatchState.ROUND_LOCKED: {MatchState.ROUND_RESOLUTION, MatchState.GAME_OVER},
            MatchState.ROUND_RESOLUTION: {MatchState.ROUND_SELECTION, MatchState.GAME_OVER},
            MatchState.GAME_OVER: set(),
        }

        if new_state not in allowed_transitions[current]:
            raise RoomClosedError(f"Illegal match-state transition from '{current.value}' to '{new_state.value}'.")

        room.match_state = new_state

    def _transition_player(self, player: RoomPlayer, new_state: PlayerRoomState) -> None:
        """Centralized player-state transition helper."""
        current = player.state
        if current is new_state:
            return

        allowed_transitions = {
            PlayerRoomState.CONNECTED: {PlayerRoomState.IN_LOBBY, PlayerRoomState.IN_ROOM, PlayerRoomState.DISCONNECTED},
            PlayerRoomState.IN_LOBBY: {PlayerRoomState.IN_ROOM, PlayerRoomState.SELECTING, PlayerRoomState.DISCONNECTED},
            PlayerRoomState.IN_ROOM: {PlayerRoomState.SELECTING, PlayerRoomState.DISCONNECTED},
            PlayerRoomState.SELECTING: {PlayerRoomState.LOCKED, PlayerRoomState.IN_ROOM, PlayerRoomState.DISCONNECTED},
            PlayerRoomState.LOCKED: {PlayerRoomState.IN_ROOM, PlayerRoomState.SELECTING, PlayerRoomState.DISCONNECTED},
            PlayerRoomState.DISCONNECTED: {PlayerRoomState.IN_LOBBY, PlayerRoomState.IN_ROOM, PlayerRoomState.SELECTING, PlayerRoomState.LOCKED},
        }

        if new_state not in allowed_transitions[current]:
            raise RoomClosedError(f"Illegal player-state transition from '{current.value}' to '{new_state.value}'.")

        player.state = new_state

    def _create_player(self, *, player_id: int, player_name: str) -> RoomPlayer:
        """Create one player seat with a resumable session token."""
        return RoomPlayer(
            player_id=player_id,
            name=player_name,
            session_token=secrets.token_urlsafe(24),
        )

    def _player(self, room: OnlineRoom, player_id: int) -> RoomPlayer:
        """Return one room player by identifier."""
        player = room.players.get(player_id)
        if player is None:
            raise PlayerNotInRoomError(f"Player {player_id} is not registered in room '{room.room_id}'.")
        return player

    def _game_player(self, room: OnlineRoom, player_id: int):
        """Return the core game player state."""
        if room.game_state is None:
            raise RoomClosedError("Game has not started yet.")
        return room.game_state.get_player(player_id)

    def _selection_from_draft(self, room: OnlineRoom, player_id: int) -> RoundSelection:
        """Convert one stored round draft into a validated round selection."""
        draft = room.round_drafts[player_id]
        return RoundSelection(card_id=draft.card_id or "", pills_committed=draft.pills_committed)

    def _require_match_state(self, room: OnlineRoom, allowed_states: set[MatchState]) -> None:
        """Guard one room action by match state."""
        if room.match_state not in allowed_states:
            joined = ", ".join(sorted(state.value for state in allowed_states))
            raise RoomClosedError(f"Action not allowed while match state is '{room.match_state.value}'. Expected one of: {joined}.")

    def _require_player_state(self, player: RoomPlayer, allowed_states: set[PlayerRoomState]) -> None:
        """Guard one player action by player state."""
        if player.state not in allowed_states:
            joined = ", ".join(sorted(state.value for state in allowed_states))
            raise SelectionAlreadySubmittedError(
                f"Action not allowed while player state is '{player.state.value}'. Expected one of: {joined}."
            )

    def _visible_round_card_id(self, room: OnlineRoom, *, target_player_id: int, perspective_player_id: int) -> str | None:
        """Reveal only what the current perspective is allowed to know during round selection."""
        draft = room.round_drafts.get(target_player_id)
        if draft is None or draft.card_id is None:
            return None
        if target_player_id == perspective_player_id:
            return draft.card_id
        if room.match_state is MatchState.ROUND_LOCKED and target_player_id == room.initiative_player_id:
            return draft.card_id
        return None

    def _card_payload(self, card: Card, *, bonus_active: bool) -> CardPayload:
        """Build the protocol card payload for one card."""
        return CardPayload(
            id=card.id,
            name=card.name,
            clan=card.clan,
            stars=card.stars,
            power=card.power,
            damage=card.damage,
            power_text=card.power_text,
            bonus_text=card.bonus_text,
            illustration=card.illustration,
            bonus_active=bonus_active,
        )
