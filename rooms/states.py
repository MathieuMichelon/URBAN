"""Shared state enumerations for multiplayer rooms and players."""

from enum import Enum


class MatchState(str, Enum):
    """Authoritative state machine for one multiplayer match."""

    WAITING_FOR_PLAYERS = "waiting_for_players"
    DRAFTING = "drafting"
    ROUND_SELECTION = "round_selection"
    ROUND_LOCKED = "round_locked"
    ROUND_RESOLUTION = "round_resolution"
    GAME_OVER = "game_over"


class PlayerRoomState(str, Enum):
    """Authoritative per-player state machine within the multiplayer room."""

    CONNECTED = "connected"
    IN_LOBBY = "in_lobby"
    IN_ROOM = "in_room"
    SELECTING = "selecting"
    LOCKED = "locked"
    DISCONNECTED = "disconnected"
