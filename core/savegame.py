"""JSON save/load helpers for full game states."""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

from core.enums import GameStatus, RoundOutcome
from core.errors import (
    InvalidCardDefinitionError,
    InvalidGameSetupError,
    SaveGameError,
    SaveGameFormatError,
)
from core.models import Card, EffectCondition, EffectDefinition, GameState, PlayerState, RoundResult
from core.rules import MAX_ROUNDS
from core.serialization import serialize_card, serialize_poison, serialize_round_result

SAVE_FORMAT = "urban_duel_save"
SAVE_VERSION = 1


def serialize_game_state(state: GameState) -> dict[str, object]:
    """Convert a game state into a JSON-serializable payload."""
    return {
        "format": SAVE_FORMAT,
        "version": SAVE_VERSION,
        "game_state": {
            "current_round": state.current_round,
            "status": state.status.value,
            "winner_id": state.winner_id,
            "players": {
                str(player_id): _serialize_player(player)
                for player_id, player in state.players.items()
            },
            "history": [serialize_round_result(result) for result in state.history],
        },
    }


def deserialize_game_state(payload: object) -> GameState:
    """Build a game state from a JSON-decoded payload."""
    if not isinstance(payload, dict):
        raise SaveGameFormatError("Save payload must be a JSON object.")

    save_format = payload.get("format")
    if save_format != SAVE_FORMAT:
        raise SaveGameFormatError(
            f"Save payload format must be '{SAVE_FORMAT}'."
        )

    version = payload.get("version")
    if version != SAVE_VERSION:
        raise SaveGameFormatError(
            f"Unsupported save payload version: {version!r}."
        )

    if "game_state" not in payload:
        raise SaveGameFormatError("Save payload is missing the 'game_state' section.")

    raw_state = payload["game_state"]
    if not isinstance(raw_state, dict):
        raise SaveGameFormatError("'game_state' must be a JSON object.")

    current_round = _read_required_int(raw_state, key="current_round", context="game_state")
    status = _read_enum(raw_state, key="status", enum_type=GameStatus, context="game_state")
    winner_id = _read_optional_player_id(raw_state, key="winner_id", context="game_state")

    raw_players = raw_state.get("players")
    if not isinstance(raw_players, dict):
        raise SaveGameFormatError("'game_state.players' must be a JSON object.")

    players = {
        1: _deserialize_player(raw_players.get("1"), expected_player_id=1),
        2: _deserialize_player(raw_players.get("2"), expected_player_id=2),
    }

    raw_history = raw_state.get("history")
    if not isinstance(raw_history, list):
        raise SaveGameFormatError("'game_state.history' must be a JSON array.")

    history = [
        _deserialize_round_result(entry, index=index)
        for index, entry in enumerate(raw_history)
    ]

    try:
        state = GameState(
            players=players,
            current_round=current_round,
            history=history,
            status=status,
            winner_id=winner_id,
        )
    except InvalidGameSetupError as error:
        raise SaveGameFormatError(f"Invalid game state in save payload: {error}") from error

    _validate_loaded_state(state)
    return state


def save_game_state(state: GameState, path: str | Path) -> None:
    """Write a full game state to a JSON file."""
    payload = serialize_game_state(state)
    save_path = Path(path)

    try:
        save_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
    except OSError as error:
        raise SaveGameError(f"Unable to write save file '{save_path}': {error}") from error


def load_game_state(path: str | Path) -> GameState:
    """Read a full game state from a JSON save file."""
    save_path = Path(path)
    if not save_path.exists():
        raise SaveGameError(f"Save file not found: {save_path}")

    try:
        raw_text = save_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SaveGameError(f"Unable to read save file '{save_path}': {error}") from error

    try:
        payload = json.loads(raw_text)
    except JSONDecodeError as error:
        raise SaveGameFormatError(
            f"Invalid JSON in save file '{save_path.name}' at line {error.lineno}, column {error.colno}: {error.msg}."
        ) from error

    return deserialize_game_state(payload)


def _serialize_player(player: PlayerState) -> dict[str, object]:
    """Serialize one player state."""
    return {
        "player_id": player.player_id,
        "hit_points": player.hit_points,
        "pills": player.pills,
        "hand": [serialize_card(card) for card in player.hand],
        "played_card_ids": sorted(player.played_card_ids),
        "active_clan_bonuses": sorted(player.active_clan_bonuses),
        "poison": serialize_poison(player.poison),
    }


def _deserialize_player(payload: object, *, expected_player_id: int) -> PlayerState:
    """Deserialize one player state."""
    if not isinstance(payload, dict):
        raise SaveGameFormatError(
            f"Save payload is missing player '{expected_player_id}'."
        )

    player_id = _read_required_int(payload, key="player_id", context=f"player {expected_player_id}")
    if player_id != expected_player_id:
        raise SaveGameFormatError(
            f"Save payload player key '{expected_player_id}' does not match embedded player_id '{player_id}'."
        )

    raw_hand = payload.get("hand")
    if not isinstance(raw_hand, list):
        raise SaveGameFormatError(f"Player {expected_player_id} hand must be a JSON array.")

    cards = [
        _deserialize_card(entry, context=f"player {expected_player_id} hand index {index}")
        for index, entry in enumerate(raw_hand)
    ]

    raw_played_ids = payload.get("played_card_ids")
    if not isinstance(raw_played_ids, list):
        raise SaveGameFormatError(
            f"Player {expected_player_id} played_card_ids must be a JSON array."
        )

    played_ids: set[str] = set()
    for index, card_id in enumerate(raw_played_ids):
        if not isinstance(card_id, str) or not card_id.strip():
            raise SaveGameFormatError(
                f"Player {expected_player_id} played_card_ids entry at index {index} must be a non-empty string."
            )
        played_ids.add(card_id)

    try:
        return PlayerState(
            player_id=player_id,
            hit_points=_read_required_int(payload, key="hit_points", context=f"player {expected_player_id}"),
            pills=_read_required_int(payload, key="pills", context=f"player {expected_player_id}"),
            hand=cards,
            played_card_ids=played_ids,
            active_clan_bonuses=set(_read_optional_string_list(payload, key="active_clan_bonuses", context=f"player {expected_player_id}")),
            poison=_read_optional_poison(payload, key="poison", context=f"player {expected_player_id}"),
        )
    except InvalidGameSetupError as error:
        raise SaveGameFormatError(
            f"Invalid player state for player {expected_player_id}: {error}"
        ) from error


def _deserialize_card(payload: object, *, context: str) -> Card:
    """Deserialize one card object."""
    if not isinstance(payload, dict):
        raise SaveGameFormatError(f"{context} must be a JSON object.")

    required_keys = {
        "id",
        "name",
        "clan",
        "stars",
        "power",
        "damage",
        "power_text",
        "bonus_text",
        "illustration",
    }
    missing_keys = required_keys - set(payload)
    if missing_keys:
        joined_keys = ", ".join(sorted(missing_keys))
        raise SaveGameFormatError(f"{context} is missing required keys: {joined_keys}.")

    try:
        return Card(
            id=_read_required_string(payload, key="id", context=context),
            name=_read_required_string(payload, key="name", context=context),
            clan=_read_required_string(payload, key="clan", context=context),
            stars=_read_required_int(payload, key="stars", context=context),
            power=_read_required_int(payload, key="power", context=context),
            damage=_read_required_int(payload, key="damage", context=context),
            power_text=_read_required_string(payload, key="power_text", context=context),
            bonus_text=_read_required_string(payload, key="bonus_text", context=context),
            illustration=_read_required_string(payload, key="illustration", context=context),
            power_effects=tuple(_read_effects(payload, key="power_effects", context=context)),
            bonus_effects=tuple(_read_effects(payload, key="bonus_effects", context=context)),
            info=_read_optional_string(payload, key="info", context=context),
        )
    except InvalidCardDefinitionError as error:
        raise SaveGameFormatError(f"Invalid card in {context}: {error}") from error


def _deserialize_round_result(payload: object, *, index: int) -> RoundResult:
    """Deserialize one historical round result."""
    context = f"history entry {index}"
    if not isinstance(payload, dict):
        raise SaveGameFormatError(f"{context} must be a JSON object.")

    try:
        return RoundResult(
            round_number=_read_required_int(payload, key="round_number", context=context),
            player_1_card_id=_read_required_string(payload, key="player_1_card_id", context=context),
            player_2_card_id=_read_required_string(payload, key="player_2_card_id", context=context),
            player_1_attack=_read_required_int(payload, key="player_1_attack", context=context),
            player_2_attack=_read_required_int(payload, key="player_2_attack", context=context),
            outcome=_read_enum(payload, key="outcome", enum_type=RoundOutcome, context=context),
            winner_id=_read_optional_player_id(payload, key="winner_id", context=context),
            loser_id=_read_optional_player_id(payload, key="loser_id", context=context),
            damage_dealt=_read_required_int(payload, key="damage_dealt", context=context),
            life_swing_player_1=_read_optional_int(payload, key="life_swing_player_1", context=context) or 0,
            life_swing_player_2=_read_optional_int(payload, key="life_swing_player_2", context=context) or 0,
            pills_gained_player_1=_read_optional_int(payload, key="pills_gained_player_1", context=context) or 0,
            pills_gained_player_2=_read_optional_int(payload, key="pills_gained_player_2", context=context) or 0,
            player_1_overload=_read_optional_bool(payload, key="player_1_overload", context=context) or False,
            player_2_overload=_read_optional_bool(payload, key="player_2_overload", context=context) or False,
            overload_damage_bonus=_read_optional_int(payload, key="overload_damage_bonus", context=context) or 0,
        )
    except ValueError as error:
        raise SaveGameFormatError(f"Invalid {context}: {error}") from error


def _read_required_string(payload: dict[str, object], *, key: str, context: str) -> str:
    """Read a required non-empty string from a JSON object."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SaveGameFormatError(f"{context} field '{key}' must be a non-empty string.")
    return value


def _read_required_int(payload: dict[str, object], *, key: str, context: str) -> int:
    """Read a required integer from a JSON object."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SaveGameFormatError(f"{context} field '{key}' must be an integer.")
    return value


def _read_optional_player_id(payload: dict[str, object], *, key: str, context: str) -> int | None:
    """Read an optional player id constrained to 1 or 2."""
    value = payload.get(key)
    if value is None:
        return None
    if value not in {1, 2}:
        raise SaveGameFormatError(f"{context} field '{key}' must be 1, 2, or null.")
    return value


def _read_optional_int(payload: dict[str, object], *, key: str, context: str) -> int | None:
    """Read an optional integer from a JSON object."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SaveGameFormatError(f"{context} field '{key}' must be an integer or null.")
    return value


def _read_optional_bool(payload: dict[str, object], *, key: str, context: str) -> bool | None:
    """Read an optional boolean from a JSON object."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SaveGameFormatError(f"{context} field '{key}' must be a boolean or null.")
    return value


def _read_optional_string_list(payload: dict[str, object], *, key: str, context: str) -> list[str]:
    """Read an optional list of strings from a JSON object."""
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(entry, str) or not entry.strip() for entry in value):
        raise SaveGameFormatError(f"{context} field '{key}' must be a string array.")
    return value


def _read_optional_string(payload: dict[str, object], *, key: str, context: str) -> str | None:
    """Read an optional non-empty string from a JSON object."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SaveGameFormatError(f"{context} field '{key}' must be a non-empty string or null.")
    return value


def _read_optional_poison(payload: dict[str, object], *, key: str, context: str):
    """Read an optional poison object from a JSON payload."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SaveGameFormatError(f"{context} field '{key}' must be a JSON object or null.")

    from core.models import OngoingPoison

    return OngoingPoison(
        amount=_read_required_int(value, key="amount", context=f"{context}.{key}"),
        minimum_hit_points=_read_required_int(value, key="minimum_hit_points", context=f"{context}.{key}"),
    )


def _read_effects(payload: dict[str, object], *, key: str, context: str) -> list[EffectDefinition]:
    """Read an optional list of effect definitions from serialized card data."""
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise SaveGameFormatError(f"{context} field '{key}' must be a JSON array.")
    return [_read_effect_definition(entry, context=f"{context}.{key}[{index}]") for index, entry in enumerate(value)]


def _read_effect_definition(payload: object, *, context: str) -> EffectDefinition:
    """Read one effect definition from serialized card data."""
    if not isinstance(payload, dict):
        raise SaveGameFormatError(f"{context} must be a JSON object.")

    condition_payload = payload.get("condition")
    condition = None
    if condition_payload is not None:
        if not isinstance(condition_payload, dict):
            raise SaveGameFormatError(f"{context}.condition must be a JSON object.")
        condition = EffectCondition(
            kind=_read_required_string(condition_payload, key="kind", context=f"{context}.condition"),
            value=condition_payload.get("value"),
        )

    try:
        return EffectDefinition(
            trigger=_read_required_string(payload, key="trigger", context=context),
            target=_read_required_string(payload, key="target", context=context),
            effect_type=_read_required_string(payload, key="effect_type", context=context),
            value=_read_required_int(payload, key="value", context=context),
            minimum=_read_optional_int(payload, key="minimum", context=context),
            condition=condition,
        )
    except InvalidCardDefinitionError as error:
        raise SaveGameFormatError(f"Invalid effect in {context}: {error}") from error


def _read_enum(
    payload: dict[str, object],
    *,
    key: str,
    enum_type,
    context: str,
):
    """Read an enum value from a JSON object."""
    raw_value = payload.get(key)
    if not isinstance(raw_value, str):
        raise SaveGameFormatError(f"{context} field '{key}' must be a string.")

    try:
        return enum_type(raw_value)
    except ValueError as error:
        raise SaveGameFormatError(
            f"{context} field '{key}' has an unsupported value: {raw_value!r}."
        ) from error


def _validate_loaded_state(state: GameState) -> None:
    """Validate cross-object save state invariants."""
    if state.current_round > MAX_ROUNDS:
        raise SaveGameFormatError(
            f"Loaded game state current_round cannot exceed {MAX_ROUNDS}."
        )

    for player_id, player in state.players.items():
        hand_ids = {card.id for card in player.hand}
        if not player.played_card_ids.issubset(hand_ids):
            raise SaveGameFormatError(
                f"Player {player_id} has played_card_ids outside their hand."
            )

    if state.status is GameStatus.IN_PROGRESS and state.winner_id is not None:
        raise SaveGameFormatError(
            "An in-progress game cannot define a winner_id."
        )

    if state.status is GameStatus.DRAW and state.winner_id is not None:
        raise SaveGameFormatError("A draw game cannot define a winner_id.")

    if state.status in {GameStatus.PLAYER_1_WON, GameStatus.PLAYER_2_WON}:
        expected_winner = 1 if state.status is GameStatus.PLAYER_1_WON else 2
        if state.winner_id != expected_winner:
            raise SaveGameFormatError(
                "winner_id is inconsistent with the game status."
            )

    if len(state.history) > MAX_ROUNDS:
        raise SaveGameFormatError(
            f"Loaded game state cannot contain more than {MAX_ROUNDS} historical rounds."
        )

    for expected_round, result in enumerate(state.history, start=1):
        if result.round_number != expected_round:
            raise SaveGameFormatError(
                "Round history must contain sequential round numbers starting at 1."
            )

    if state.is_over:
        if len(state.history) == 0:
            raise SaveGameFormatError("A finished game must contain at least one historical round.")
        if state.current_round != state.history[-1].round_number:
            raise SaveGameFormatError(
                "For a finished game, current_round must match the last played round."
            )
    else:
        if state.current_round != len(state.history) + 1:
            raise SaveGameFormatError(
                "For an in-progress game, current_round must equal history length plus one."
            )
