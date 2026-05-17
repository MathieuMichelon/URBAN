"""Explicit WebSocket protocol schemas for the online multiplayer mode."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator
from rooms.states import MatchState, PlayerRoomState


def utc_now() -> datetime:
    """Return an aware UTC timestamp for protocol envelopes."""
    return datetime.now(timezone.utc)


class ProtocolModel(BaseModel):
    """Base Pydantic model used by every protocol schema."""

    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
    }


class CardPayload(ProtocolModel):
    """Serializable card data sent to the frontend."""

    id: str
    name: str
    clan: str
    stars: int
    power: int
    damage: int
    power_text: str
    bonus_text: str
    illustration: str
    info: str | None = None
    bonus_active: bool | None = None


class RoundResultPayload(ProtocolModel):
    """Serializable round result sent by the authoritative backend."""

    round_number: int
    player_1_card_id: str
    player_2_card_id: str
    player_1_attack: int
    player_2_attack: int
    outcome: str
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


class PlayerStatePayload(ProtocolModel):
    """Authoritative view of one player inside a room snapshot."""

    player_id: int
    name: str
    connected: bool
    player_state: PlayerRoomState
    hit_points: int | None = None
    pills: int | None = None
    hand: list[CardPayload] = Field(default_factory=list)
    played_card_ids: list[str] = Field(default_factory=list)
    team_stars: int | None = None
    active_clan_bonuses: list[str] = Field(default_factory=list)
    ready: bool = False
    draft_card_id: str | None = None
    drafted_pills: int | None = None
    drafted_overload: bool | None = None
    draft_selected_cards: list[CardPayload] = Field(default_factory=list)
    draft_locked: bool = False
    draft_is_valid: bool = False


class StateSnapshotPayload(ProtocolModel):
    """Full authoritative room snapshot rendered by the frontend."""

    match_state: MatchState
    game_started: bool
    local_player_id: int
    current_round: int | None = None
    game_status: str | None = None
    winner_id: int | None = None
    initiative_player_id: int | None = None
    pending_player_ids: list[int] = Field(default_factory=list)
    draft_offer: list[CardPayload] = Field(default_factory=list)
    draft_locked_player_ids: list[int] = Field(default_factory=list)
    draft_team_size: int | None = None
    draft_star_cap: int | None = None
    players: list[PlayerStatePayload] = Field(default_factory=list)
    history: list[RoundResultPayload] = Field(default_factory=list)
    end_reason: str | None = None


class ErrorPayload(ProtocolModel):
    """Machine-readable backend error."""

    code: str
    message: str


class PongPayload(ProtocolModel):
    """Heartbeat acknowledgement."""

    heartbeat: Literal["pong"] = "pong"


class PlayerIdentityPayload(ProtocolModel):
    """Identity fields returned when a player enters a room."""

    player_name: str = Field(min_length=1, max_length=24)
    session_token: str | None = None

    @field_validator("player_name")
    @classmethod
    def normalize_player_name(cls, value: str) -> str:
        """Normalize protocol player names and reject empty strings."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("player_name must not be empty.")
        return normalized


class CreateRoomPayload(PlayerIdentityPayload):
    """Payload used to create a new room."""


class JoinRoomPayload(PlayerIdentityPayload):
    """Payload used to join an existing room."""


class SelectCardPayload(ProtocolModel):
    """Payload used to update the drafted card."""

    card_id: str = Field(min_length=1)


class SetPillsPayload(ProtocolModel):
    """Payload used to update the drafted number of pills."""

    pills: int = Field(ge=0)


class SetOverloadPayload(ProtocolModel):
    """Payload used to update the drafted Overload flag."""

    overload: bool = False


class EmptyPayload(ProtocolModel):
    """Empty payload for commands without extra parameters."""


class PingPayload(ProtocolModel):
    """Optional heartbeat ping payload."""

    nonce: str | None = None


class RoomCreatedPayload(ProtocolModel):
    """Server acknowledgement for a newly created room."""

    player_name: str
    session_token: str


class RoomJoinedPayload(ProtocolModel):
    """Server acknowledgement for a joined room."""

    player_name: str
    session_token: str
    resumed: bool = False


class PlayerJoinedPayload(ProtocolModel):
    """Broadcast when the second player enters the room."""

    joined_player_id: int
    joined_player_name: str


class GameStartedPayload(ProtocolModel):
    """Broadcast emitted when the room becomes a live match."""

    state: StateSnapshotPayload


class PlayerReadyPayload(ProtocolModel):
    """Broadcast emitted when a player locks a round selection."""

    ready_player_id: int
    round_number: int
    state: StateSnapshotPayload


class RoundResolvedPayload(ProtocolModel):
    """Broadcast emitted after the server resolves a round."""

    round_result: RoundResultPayload
    state: StateSnapshotPayload


class GameFinishedPayload(ProtocolModel):
    """Broadcast emitted after the final result is known."""

    winner_id: int | None
    state: StateSnapshotPayload


class OpponentDisconnectedPayload(ProtocolModel):
    """Broadcast emitted when the other player disconnects."""

    disconnected_player_id: int
    disconnected_player_name: str


class MessageEnvelope(ProtocolModel):
    """Base envelope shared by all WebSocket messages."""

    type: str
    payload: ProtocolModel
    timestamp: datetime | None = None
    room_id: str | None = None
    player_id: int | None = None


class ClientCreateRoomMessage(MessageEnvelope):
    """`create_room` command."""

    type: Literal["create_room"]
    payload: CreateRoomPayload
    timestamp: datetime | None = None
    room_id: None = None
    player_id: int | None = None


class ClientJoinRoomMessage(MessageEnvelope):
    """`join_room` command."""

    type: Literal["join_room"]
    payload: JoinRoomPayload
    room_id: str
    player_id: int | None = None


class ClientSelectCardMessage(MessageEnvelope):
    """`select_card` command."""

    type: Literal["select_card"]
    payload: SelectCardPayload
    room_id: str
    player_id: int | None = None


class ClientSetPillsMessage(MessageEnvelope):
    """`set_pills` command."""

    type: Literal["set_pills"]
    payload: SetPillsPayload
    room_id: str
    player_id: int | None = None


class ClientSetOverloadMessage(MessageEnvelope):
    """`set_overload` command."""

    type: Literal["set_overload"]
    payload: SetOverloadPayload
    room_id: str
    player_id: int | None = None


class ClientConfirmSelectionMessage(MessageEnvelope):
    """`confirm_selection` command."""

    type: Literal["confirm_selection"]
    payload: EmptyPayload
    room_id: str
    player_id: int | None = None


class ClientPingMessage(MessageEnvelope):
    """`ping` heartbeat."""

    type: Literal["ping"]
    payload: PingPayload = Field(default_factory=PingPayload)
    room_id: str | None = None
    player_id: int | None = None


class ClientRequestStateMessage(MessageEnvelope):
    """`request_state` command."""

    type: Literal["request_state"]
    payload: EmptyPayload = Field(default_factory=EmptyPayload)
    room_id: str | None = None
    player_id: int | None = None


class ServerRoomCreatedMessage(MessageEnvelope):
    """`room_created` event."""

    type: Literal["room_created"] = "room_created"
    payload: RoomCreatedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerRoomJoinedMessage(MessageEnvelope):
    """`room_joined` event."""

    type: Literal["room_joined"] = "room_joined"
    payload: RoomJoinedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerPlayerJoinedMessage(MessageEnvelope):
    """`player_joined` event."""

    type: Literal["player_joined"] = "player_joined"
    payload: PlayerJoinedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerGameStartedMessage(MessageEnvelope):
    """`game_started` event."""

    type: Literal["game_started"] = "game_started"
    payload: GameStartedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerStateSnapshotMessage(MessageEnvelope):
    """`state_snapshot` event."""

    type: Literal["state_snapshot"] = "state_snapshot"
    payload: StateSnapshotPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerPlayerReadyMessage(MessageEnvelope):
    """`player_ready` event."""

    type: Literal["player_ready"] = "player_ready"
    payload: PlayerReadyPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerRoundResolvedMessage(MessageEnvelope):
    """`round_resolved` event."""

    type: Literal["round_resolved"] = "round_resolved"
    payload: RoundResolvedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerGameFinishedMessage(MessageEnvelope):
    """`game_finished` event."""

    type: Literal["game_finished"] = "game_finished"
    payload: GameFinishedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerOpponentDisconnectedMessage(MessageEnvelope):
    """`opponent_disconnected` event."""

    type: Literal["opponent_disconnected"] = "opponent_disconnected"
    payload: OpponentDisconnectedPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str
    player_id: int


class ServerErrorMessage(MessageEnvelope):
    """`error` event."""

    type: Literal["error"] = "error"
    payload: ErrorPayload
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str | None = None
    player_id: int | None = None


class ServerPongMessage(MessageEnvelope):
    """Extra `pong` event used for heartbeat replies."""

    type: Literal["pong"] = "pong"
    payload: PongPayload = Field(default_factory=PongPayload)
    timestamp: datetime = Field(default_factory=utc_now)
    room_id: str | None = None
    player_id: int | None = None


ClientMessage = Annotated[
    (
        ClientCreateRoomMessage
        | ClientJoinRoomMessage
        | ClientSelectCardMessage
        | ClientSetPillsMessage
        | ClientSetOverloadMessage
        | ClientConfirmSelectionMessage
        | ClientPingMessage
        | ClientRequestStateMessage
    ),
    Field(discriminator="type"),
]

ServerMessage = (
    ServerRoomCreatedMessage
    | ServerRoomJoinedMessage
    | ServerPlayerJoinedMessage
    | ServerGameStartedMessage
    | ServerStateSnapshotMessage
    | ServerPlayerReadyMessage
    | ServerRoundResolvedMessage
    | ServerGameFinishedMessage
    | ServerOpponentDisconnectedMessage
    | ServerErrorMessage
    | ServerPongMessage
)

_CLIENT_MESSAGE_ADAPTER = TypeAdapter(ClientMessage)


def parse_client_message(payload: object) -> ClientMessage:
    """Validate one incoming client payload against the explicit protocol."""
    return _CLIENT_MESSAGE_ADAPTER.validate_python(payload)


def dump_message(message: ServerMessage) -> dict[str, object]:
    """Serialize a server message for FastAPI WebSocket transport."""
    return message.model_dump(mode="json")
