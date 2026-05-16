"""Async-safe room registry delegating all transitions to the room state machine."""

from __future__ import annotations

import asyncio
from pathlib import Path
import secrets

from data.card_repository import load_cards
from rooms.state_machine import (
    ConfirmSelectionOutcome,
    DisconnectOutcome,
    JoinRoomOutcome,
    OnlineRoom,
    RoomNotFoundError,
    RoomPlayer,
    RoomStateMachine,
)


class RoomManager:
    """In-memory room registry for the FastAPI multiplayer backend."""

    def __init__(self, cards_path: str | Path) -> None:
        """Load the shared card catalog once and keep a central state machine."""
        self._cards = load_cards(cards_path)
        self._rooms: dict[str, OnlineRoom] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()
        self._state_machine = RoomStateMachine()

    async def create_room(self, player_name: str) -> tuple[OnlineRoom, RoomPlayer]:
        """Create a new room with its first player."""
        async with self._registry_lock:
            room_id = self._generate_room_id()
            room, player = self._state_machine.create_room(room_id, cards=self._cards, player_name=player_name)
            self._rooms[room_id] = room
            self._locks[room_id] = asyncio.Lock()
            return room, player

    async def join_room(
        self,
        room_id: str,
        *,
        player_name: str,
        session_token: str | None = None,
    ) -> tuple[OnlineRoom, JoinRoomOutcome]:
        """Join or resume a room through the centralized state machine."""
        room = await self.get_room(room_id)
        async with self._locks[room_id]:
            outcome = self._state_machine.join_room(room, player_name=player_name, session_token=session_token)
            return room, outcome

    async def select_card(self, room_id: str, *, player_id: int, card_id: str) -> OnlineRoom:
        """Update the drafted card for one player."""
        room = await self.get_room(room_id)
        async with self._locks[room_id]:
            self._state_machine.select_card(room, player_id=player_id, card_id=card_id)
            return room

    async def set_pills(self, room_id: str, *, player_id: int, pills: int) -> OnlineRoom:
        """Update the drafted pills for one player."""
        room = await self.get_room(room_id)
        async with self._locks[room_id]:
            self._state_machine.set_pills(room, player_id=player_id, pills=pills)
            return room

    async def confirm_selection(self, room_id: str, *, player_id: int) -> tuple[OnlineRoom, ConfirmSelectionOutcome]:
        """Lock a selection and resolve the round if both players are ready."""
        room = await self.get_room(room_id)
        async with self._locks[room_id]:
            outcome = self._state_machine.confirm_selection(room, player_id=player_id)
            return room, outcome

    async def disconnect_player(self, room_id: str, *, player_id: int) -> tuple[OnlineRoom, DisconnectOutcome]:
        """Apply the explicit disconnect policy for a room."""
        room = await self.get_room(room_id)
        async with self._locks[room_id]:
            outcome = self._state_machine.disconnect_player(room, player_id=player_id)
            should_cleanup = room.match_state.value == "game_over" and all(
                player.state.value == "disconnected"
                for player in room.players.values()
            )

        if should_cleanup:
            async with self._registry_lock:
                self._rooms.pop(room_id, None)
                self._locks.pop(room_id, None)

        return room, outcome

    async def snapshot_for(self, room_id: str, *, player_id: int):
        """Return the authoritative snapshot for one player perspective."""
        room = await self.get_room(room_id)
        async with self._locks[room_id]:
            return self._state_machine.snapshot_for(room, local_player_id=player_id)

    async def get_room(self, room_id: str) -> OnlineRoom:
        """Fetch one room from the in-memory registry."""
        async with self._registry_lock:
            room = self._rooms.get(room_id)
            if room is None:
                raise RoomNotFoundError(f"Room '{room_id}' does not exist.")
            return room

    def _generate_room_id(self) -> str:
        """Generate a short uppercase room code."""
        while True:
            room_id = secrets.token_hex(3).upper()
            if room_id not in self._rooms:
                return room_id
