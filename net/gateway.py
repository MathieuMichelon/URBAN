"""FastAPI WebSocket gateway for the authoritative multiplayer backend."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import WebSocket
from pydantic import ValidationError

from core.errors import GameError
from net.protocol import (
    ClientConfirmSelectionMessage,
    ClientCancelMatchmakingMessage,
    ClientCreateRoomMessage,
    ClientFindMatchMessage,
    ClientJoinRoomMessage,
    ClientMessage,
    ClientPingMessage,
    ClientRequestRematchMessage,
    ClientRequestStateMessage,
    ClientSelectCardMessage,
    ClientSelectClansMessage,
    ClientSetOverloadMessage,
    ClientSetPillsMessage,
    ErrorPayload,
    GameFinishedPayload,
    GameStartedPayload,
    MatchmakingCancelledPayload,
    MatchmakingWaitingPayload,
    OpponentDisconnectedPayload,
    PlayerJoinedPayload,
    PlayerReadyPayload,
    PongPayload,
    RoundResolvedPayload,
    RoomCreatedPayload,
    RoomJoinedPayload,
    ServerErrorMessage,
    ServerGameFinishedMessage,
    ServerGameStartedMessage,
    ServerMatchmakingCancelledMessage,
    ServerMatchmakingWaitingMessage,
    ServerMessage,
    ServerOpponentDisconnectedMessage,
    ServerPlayerJoinedMessage,
    ServerPlayerReadyMessage,
    ServerPongMessage,
    ServerRoomCreatedMessage,
    ServerRoomJoinedMessage,
    ServerRoundResolvedMessage,
    ServerStateSnapshotMessage,
    StateSnapshotPayload,
    dump_message,
    parse_client_message,
)
from rooms.manager import RoomManager
from rooms.state_machine import PlayerNotInRoomError, RoomClosedError, RoomFullError, RoomNotFoundError, RoomStateError
from rooms.states import MatchState


@dataclass(slots=True)
class ClientConnection:
    """Runtime metadata bound to one WebSocket connection."""

    websocket: WebSocket
    room_id: str | None = None
    player_id: int | None = None
    player_name: str | None = None
    session_token: str | None = None


class ConnectionHub:
    """Track active WebSocket connections by room and player."""

    def __init__(self) -> None:
        """Initialize the in-memory connection registry."""
        self._connections: dict[str, dict[int, WebSocket]] = {}

    def bind(self, *, room_id: str, player_id: int, websocket: WebSocket) -> None:
        """Attach one live WebSocket to a room/player slot."""
        self._connections.setdefault(room_id, {})[player_id] = websocket

    def unbind(self, *, room_id: str, player_id: int) -> None:
        """Remove one live WebSocket from the registry."""
        room_connections = self._connections.get(room_id)
        if room_connections is None:
            return

        room_connections.pop(player_id, None)
        if not room_connections:
            self._connections.pop(room_id, None)

    def has_player(self, *, room_id: str, player_id: int) -> bool:
        """Return whether a live socket is currently bound for the player."""
        return player_id in self._connections.get(room_id, {})

    async def send(self, websocket: WebSocket, message: ServerMessage) -> None:
        """Send one server message to a specific WebSocket."""
        await websocket.send_json(dump_message(message))

    async def send_to_player(self, *, room_id: str, player_id: int, message: ServerMessage) -> None:
        """Send one server message to a bound player connection when present."""
        websocket = self._connections.get(room_id, {}).get(player_id)
        if websocket is None:
            return
        await self.send(websocket, message)


class WebSocketGateway:
    """Dispatch validated protocol messages onto the room manager."""

    def __init__(self, room_manager: RoomManager) -> None:
        """Create the gateway with its authoritative backend services."""
        self._room_manager = room_manager
        self._hub = ConnectionHub()
        self._matchmaking_waiters: list[ClientConnection] = []
        self._matchmaking_lock = asyncio.Lock()

    async def handle_raw_message(self, connection: ClientConnection, raw_payload: object) -> None:
        """Parse and dispatch one incoming JSON frame."""
        try:
            message = parse_client_message(raw_payload)
        except ValidationError as error:
            await self._send_error(connection, code="invalid_message", message=str(error))
            return

        try:
            await self._dispatch(connection, message)
        except (GameError, RoomStateError) as error:
            await self._send_error(connection, code=error.__class__.__name__.lower(), message=str(error))

    async def handle_disconnect(self, connection: ClientConnection) -> None:
        """Cleanup one disconnected client and notify the remaining opponent."""
        await self._remove_from_matchmaking(connection)
        if connection.room_id is None or connection.player_id is None:
            return

        room, disconnect_outcome = await self._room_manager.disconnect_player(connection.room_id, player_id=connection.player_id)
        self._hub.unbind(room_id=connection.room_id, player_id=connection.player_id)

        if disconnect_outcome.disconnected_player is None or disconnect_outcome.opponent_player_id is None:
            return

        if not self._hub.has_player(room_id=room.room_id, player_id=disconnect_outcome.opponent_player_id):
            return

        opponent_id = disconnect_outcome.opponent_player_id
        await self._hub.send_to_player(
            room_id=room.room_id,
            player_id=opponent_id,
            message=ServerOpponentDisconnectedMessage(
                room_id=room.room_id,
                player_id=opponent_id,
                payload=OpponentDisconnectedPayload(
                    disconnected_player_id=disconnect_outcome.disconnected_player.player_id,
                    disconnected_player_name=disconnect_outcome.disconnected_player.name,
                ),
            ),
        )

        snapshot = await self._room_manager.snapshot_for(room.room_id, player_id=opponent_id)
        await self._hub.send_to_player(
            room_id=room.room_id,
            player_id=opponent_id,
            message=ServerStateSnapshotMessage(
                room_id=room.room_id,
                player_id=opponent_id,
                payload=snapshot,
            ),
        )

        if snapshot.match_state is MatchState.GAME_OVER:
            await self._hub.send_to_player(
                room_id=room.room_id,
                player_id=opponent_id,
                message=ServerGameFinishedMessage(
                    room_id=room.room_id,
                    player_id=opponent_id,
                    payload=GameFinishedPayload(winner_id=snapshot.winner_id, state=snapshot),
                ),
            )

    async def _dispatch(self, connection: ClientConnection, message: ClientMessage) -> None:
        """Route one validated client message to the correct handler."""
        if isinstance(message, ClientCreateRoomMessage):
            await self._handle_create_room(connection, message)
            return
        if isinstance(message, ClientJoinRoomMessage):
            await self._handle_join_room(connection, message)
            return
        if isinstance(message, ClientFindMatchMessage):
            await self._handle_find_match(connection, message)
            return
        if isinstance(message, ClientCancelMatchmakingMessage):
            await self._handle_cancel_matchmaking(connection)
            return
        if isinstance(message, ClientSelectClansMessage):
            await self._handle_select_clans(connection, message)
            return
        if isinstance(message, ClientSelectCardMessage):
            await self._handle_select_card(connection, message)
            return
        if isinstance(message, ClientSetPillsMessage):
            await self._handle_set_pills(connection, message)
            return
        if isinstance(message, ClientSetOverloadMessage):
            await self._handle_set_overload(connection, message)
            return
        if isinstance(message, ClientConfirmSelectionMessage):
            await self._handle_confirm_selection(connection, message)
            return
        if isinstance(message, ClientRequestStateMessage):
            await self._handle_request_state(connection, message)
            return
        if isinstance(message, ClientRequestRematchMessage):
            await self._handle_request_rematch(connection, message)
            return
        if isinstance(message, ClientPingMessage):
            await self._handle_ping(connection)
            return

        await self._send_error(connection, code="unsupported_message", message=f"Unsupported message type: {message.type}.")

    async def _handle_create_room(self, connection: ClientConnection, message: ClientCreateRoomMessage) -> None:
        """Create a fresh room and bind the requesting WebSocket to player 1."""
        if connection.room_id is not None:
            raise RoomClosedError("Connection already belongs to a room.")

        await self._remove_from_matchmaking(connection)
        room, player = await self._room_manager.create_room(message.payload.player_name)
        connection.room_id = room.room_id
        connection.player_id = player.player_id
        connection.player_name = player.name
        connection.session_token = player.session_token
        self._hub.bind(room_id=room.room_id, player_id=player.player_id, websocket=connection.websocket)

        await self._hub.send(
            connection.websocket,
            ServerRoomCreatedMessage(
                room_id=room.room_id,
                player_id=player.player_id,
                payload=RoomCreatedPayload(player_name=player.name, session_token=player.session_token),
            ),
        )
        await self._send_state_snapshot(connection, await self._room_manager.snapshot_for(room.room_id, player_id=player.player_id))

    async def _handle_join_room(self, connection: ClientConnection, message: ClientJoinRoomMessage) -> None:
        """Join a waiting room as player 2 and notify both clients."""
        if connection.room_id is not None:
            raise RoomClosedError("Connection already belongs to a room.")

        await self._remove_from_matchmaking(connection)
        room, outcome = await self._room_manager.join_room(
            message.room_id,
            player_name=message.payload.player_name,
            session_token=message.payload.session_token,
        )
        player = outcome.player
        connection.room_id = room.room_id
        connection.player_id = player.player_id
        connection.player_name = player.name
        connection.session_token = player.session_token
        self._hub.bind(room_id=room.room_id, player_id=player.player_id, websocket=connection.websocket)

        await self._hub.send(
            connection.websocket,
            ServerRoomJoinedMessage(
                room_id=room.room_id,
                player_id=player.player_id,
                payload=RoomJoinedPayload(
                    player_name=player.name,
                    session_token=player.session_token,
                    resumed=outcome.resumed,
                ),
            ),
        )

        opponent_id = 1 if player.player_id == 2 and 1 in room.players else 2 if player.player_id == 1 and 2 in room.players else None
        if opponent_id is not None and not outcome.resumed:
            await self._hub.send_to_player(
                room_id=room.room_id,
                player_id=opponent_id,
                message=ServerPlayerJoinedMessage(
                    room_id=room.room_id,
                    player_id=opponent_id,
                    payload=PlayerJoinedPayload(
                        joined_player_id=player.player_id,
                        joined_player_name=player.name,
                    ),
                ),
            )

        if not outcome.resumed and len(room.players) == 2:
            for target_player_id in sorted(room.players):
                snapshot = await self._room_manager.snapshot_for(room.room_id, player_id=target_player_id)
                if outcome.game_started:
                    await self._hub.send_to_player(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        message=ServerGameStartedMessage(
                            room_id=room.room_id,
                            player_id=target_player_id,
                            payload=GameStartedPayload(state=snapshot),
                        ),
                    )
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerStateSnapshotMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=snapshot,
                    ),
                )
            return

        await self._send_state_snapshot(connection, await self._room_manager.snapshot_for(room.room_id, player_id=player.player_id))

    async def _handle_find_match(self, connection: ClientConnection, message: ClientFindMatchMessage) -> None:
        """Enter matchmaking or pair with the oldest waiting player."""
        if connection.room_id is not None:
            raise RoomClosedError("Connection already belongs to a room.")

        connection.player_name = message.payload.player_name
        async with self._matchmaking_lock:
            self._matchmaking_waiters = [
                waiter
                for waiter in self._matchmaking_waiters
                if waiter.room_id is None and waiter is not connection
            ]
            if self._matchmaking_waiters:
                opponent = self._matchmaking_waiters.pop(0)
            else:
                self._matchmaking_waiters.append(connection)
                await self._hub.send(
                    connection.websocket,
                    ServerMatchmakingWaitingMessage(
                        payload=MatchmakingWaitingPayload(queue_position=1),
                    ),
                )
                return

        await self._create_matchmaking_room(opponent, connection)

    async def _handle_cancel_matchmaking(self, connection: ClientConnection) -> None:
        """Remove the caller from the matchmaking queue."""
        removed = await self._remove_from_matchmaking(connection)
        await self._hub.send(
            connection.websocket,
            ServerMatchmakingCancelledMessage(
                payload=MatchmakingCancelledPayload(
                    message="Recherche annulée." if removed else "Aucune recherche en cours.",
                ),
            ),
        )

    async def _create_matchmaking_room(self, player_one_connection: ClientConnection, player_two_connection: ClientConnection) -> None:
        """Create a room for two matched waiting sockets and send normal room events."""
        player_one_name = player_one_connection.player_name or "Player 1"
        player_two_name = player_two_connection.player_name or "Player 2"
        room, player_one = await self._room_manager.create_room(player_one_name)
        room, join_outcome = await self._room_manager.join_room(room.room_id, player_name=player_two_name)
        player_two = join_outcome.player

        for target_connection, player in (
            (player_one_connection, player_one),
            (player_two_connection, player_two),
        ):
            target_connection.room_id = room.room_id
            target_connection.player_id = player.player_id
            target_connection.player_name = player.name
            target_connection.session_token = player.session_token
            self._hub.bind(room_id=room.room_id, player_id=player.player_id, websocket=target_connection.websocket)

        await self._hub.send(
            player_one_connection.websocket,
            ServerRoomCreatedMessage(
                room_id=room.room_id,
                player_id=player_one.player_id,
                payload=RoomCreatedPayload(player_name=player_one.name, session_token=player_one.session_token),
            ),
        )
        await self._hub.send(
            player_two_connection.websocket,
            ServerRoomJoinedMessage(
                room_id=room.room_id,
                player_id=player_two.player_id,
                payload=RoomJoinedPayload(
                    player_name=player_two.name,
                    session_token=player_two.session_token,
                    resumed=False,
                ),
            ),
        )
        await self._hub.send_to_player(
            room_id=room.room_id,
            player_id=player_one.player_id,
            message=ServerPlayerJoinedMessage(
                room_id=room.room_id,
                player_id=player_one.player_id,
                payload=PlayerJoinedPayload(
                    joined_player_id=player_two.player_id,
                    joined_player_name=player_two.name,
                ),
            ),
        )

        for target_player_id in sorted(room.players):
            snapshot = await self._room_manager.snapshot_for(room.room_id, player_id=target_player_id)
            if join_outcome.game_started:
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerGameStartedMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=GameStartedPayload(state=snapshot),
                    ),
                )
            await self._hub.send_to_player(
                room_id=room.room_id,
                player_id=target_player_id,
                message=ServerStateSnapshotMessage(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    payload=snapshot,
                ),
            )

    async def _handle_select_clans(self, connection: ClientConnection, message: ClientSelectClansMessage) -> None:
        """Authoritatively lock the caller clan selection."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        room = await self._room_manager.select_clans(room_id, player_id=player_id, clan_ids=message.payload.clan_ids)
        await self._broadcast_state_snapshots(room.room_id, player_ids=sorted(room.players))

    async def _handle_select_card(self, connection: ClientConnection, message: ClientSelectCardMessage) -> None:
        """Authoritatively update the caller draft card."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        room = await self._room_manager.select_card(room_id, player_id=player_id, card_id=message.payload.card_id)
        if room.match_state is MatchState.DRAFTING:
            await self._broadcast_state_snapshots(room.room_id, player_ids=sorted(room.players))
            return

        await self._send_state_snapshot(connection, await self._room_manager.snapshot_for(room_id, player_id=player_id))

    async def _handle_set_pills(self, connection: ClientConnection, message: ClientSetPillsMessage) -> None:
        """Authoritatively update the caller draft pills."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        await self._room_manager.set_pills(room_id, player_id=player_id, pills=message.payload.pills)
        await self._send_state_snapshot(connection, await self._room_manager.snapshot_for(room_id, player_id=player_id))

    async def _handle_set_overload(self, connection: ClientConnection, message: ClientSetOverloadMessage) -> None:
        """Authoritatively update the caller draft Overload flag."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        await self._room_manager.set_overload(room_id, player_id=player_id, overload=message.payload.overload)
        await self._send_state_snapshot(connection, await self._room_manager.snapshot_for(room_id, player_id=player_id))

    async def _handle_confirm_selection(self, connection: ClientConnection, message: ClientConfirmSelectionMessage) -> None:
        """Lock a selection and resolve the round when both players are ready."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        room, outcome = await self._room_manager.confirm_selection(room_id, player_id=player_id)

        for target_player_id in sorted(room.players):
            snapshot = await self._room_manager.snapshot_for(room.room_id, player_id=target_player_id)
            if outcome.game_started and outcome.round_result is None:
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerGameStartedMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=GameStartedPayload(state=snapshot),
                    ),
                )
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerStateSnapshotMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=snapshot,
                    ),
                )
                continue

            if outcome.round_result is None:
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerPlayerReadyMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=PlayerReadyPayload(
                            ready_player_id=outcome.ready_player_id,
                            round_number=snapshot.current_round or 0,
                            state=snapshot,
                        ),
                    ),
                )
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerStateSnapshotMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=snapshot,
                    ),
                )
                continue

            round_result = RoundResolvedPayload(
                round_result=snapshot.history[-1],
                state=snapshot,
            )
            await self._hub.send_to_player(
                room_id=room.room_id,
                player_id=target_player_id,
                message=ServerRoundResolvedMessage(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    payload=round_result,
                ),
            )

            if outcome.game_finished:
                await self._hub.send_to_player(
                    room_id=room.room_id,
                    player_id=target_player_id,
                    message=ServerGameFinishedMessage(
                        room_id=room.room_id,
                        player_id=target_player_id,
                        payload=GameFinishedPayload(
                            winner_id=snapshot.winner_id,
                            state=snapshot,
                        ),
                    ),
                )

    async def _handle_request_state(self, connection: ClientConnection, message: ClientRequestStateMessage) -> None:
        """Return the latest authoritative snapshot to the caller."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        await self._send_state_snapshot(connection, await self._room_manager.snapshot_for(room_id, player_id=player_id))

    async def _handle_request_rematch(self, connection: ClientConnection, message: ClientRequestRematchMessage) -> None:
        """Mark one player ready for rematch and restart drafting when both agree."""
        room_id, player_id = self._require_bound_player(connection, message.room_id, message.player_id)
        room, _outcome = await self._room_manager.request_rematch(room_id, player_id=player_id)
        await self._broadcast_state_snapshots(room.room_id, player_ids=sorted(room.players))

    async def _handle_ping(self, connection: ClientConnection) -> None:
        """Reply to a heartbeat ping."""
        await self._hub.send(
            connection.websocket,
            ServerPongMessage(
                room_id=connection.room_id,
                player_id=connection.player_id,
                payload=PongPayload(),
            ),
        )

    def _require_bound_player(self, connection: ClientConnection, room_id: str | None, player_id: int | None) -> tuple[str, int]:
        """Ensure a gameplay command is bound to the authenticated room/player."""
        if connection.room_id is None or connection.player_id is None:
            raise PlayerNotInRoomError("Join a room before sending gameplay commands.")

        if room_id is not None and room_id != connection.room_id:
            raise RoomNotFoundError(f"Connection belongs to room '{connection.room_id}', not '{room_id}'.")

        if player_id is not None and player_id != connection.player_id:
            raise PlayerNotInRoomError("player_id does not match the authenticated connection.")

        return connection.room_id, connection.player_id

    async def _remove_from_matchmaking(self, connection: ClientConnection) -> bool:
        """Remove a socket from the in-memory matchmaking queue."""
        async with self._matchmaking_lock:
            initial_count = len(self._matchmaking_waiters)
            self._matchmaking_waiters = [
                waiter for waiter in self._matchmaking_waiters if waiter is not connection
            ]
            return len(self._matchmaking_waiters) != initial_count

    async def _send_state_snapshot(self, connection: ClientConnection, snapshot: StateSnapshotPayload) -> None:
        """Send one authoritative state snapshot to the current connection."""
        if connection.room_id is None or connection.player_id is None:
            raise PlayerNotInRoomError("Connection is not bound to a room.")

        await self._hub.send(
            connection.websocket,
            ServerStateSnapshotMessage(
                room_id=connection.room_id,
                player_id=connection.player_id,
                payload=snapshot,
            ),
        )

    async def _broadcast_state_snapshots(self, room_id: str, *, player_ids: list[int]) -> None:
        """Broadcast authoritative per-player snapshots to every connected room participant."""
        for player_id in player_ids:
            snapshot = await self._room_manager.snapshot_for(room_id, player_id=player_id)
            await self._hub.send_to_player(
                room_id=room_id,
                player_id=player_id,
                message=ServerStateSnapshotMessage(
                    room_id=room_id,
                    player_id=player_id,
                    payload=snapshot,
                ),
            )

    async def _send_error(self, connection: ClientConnection, *, code: str, message: str) -> None:
        """Send one explicit protocol error envelope."""
        await self._hub.send(
            connection.websocket,
            ServerErrorMessage(
                room_id=connection.room_id,
                player_id=connection.player_id,
                payload=ErrorPayload(code=code, message=message),
            ),
        )
