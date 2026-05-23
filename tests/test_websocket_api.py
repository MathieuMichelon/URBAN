"""End-to-end tests for the FastAPI WebSocket multiplayer backend."""

from collections import Counter
from itertools import combinations
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app
from core.draft import DRAFT_OFFER_SIZE


ACTIVE_URBAN2_PATH = Path(__file__).resolve().parents[1] / "assets" / "data" / "urban2_personnages_base.json"


def _first_valid_team_ids(draft_offer: list[dict[str, object]]) -> list[str]:
    """Return the first legal 4-card team from a draft offer payload."""
    for team in combinations(draft_offer, 4):
        if sum(card["stars"] for card in team) <= 8:
            return [card["id"] for card in team]
    raise AssertionError("Expected the draft offer to contain a legal team.")


def _first_invalid_star_cap_team_ids(draft_offer: list[dict[str, object]]) -> list[str]:
    """Return the first over-cap team from a draft offer payload."""
    for team in combinations(draft_offer, 4):
        if sum(card["stars"] for card in team) > 8:
            return [card["id"] for card in team]
    raise AssertionError("Expected the draft offer to contain an illegal team.")


def _team_ids_with_active_bonus(draft_offer: list[dict[str, object]]) -> list[str]:
    """Return the first legal team that activates at least one clan bonus."""
    for team in combinations(draft_offer, 4):
        if sum(card["stars"] for card in team) > 8:
            continue
        if any(count >= 2 for count in Counter(card["clan"] for card in team).values()):
            return [card["id"] for card in team]
    raise AssertionError("Expected a legal team with an active clan bonus.")


def _first_three_clan_ids(snapshot_payload: dict[str, object]) -> list[str]:
    """Return the first selectable three-clan combination from a clan snapshot."""
    return [clan["id"] for clan in snapshot_payload["clan_options"][:3]]


def _last_three_clan_ids(snapshot_payload: dict[str, object]) -> list[str]:
    """Return a different selectable three-clan combination from a clan snapshot."""
    return [clan["id"] for clan in snapshot_payload["clan_options"][2:5]]


def test_two_players_can_select_clans_draft_and_resolve_one_round() -> None:
    """The backend should run clan selection, private draft, match start, and one full round."""
    app = create_app(ACTIVE_URBAN2_PATH)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_1:
            ws_1.send_json({"type": "create_room", "payload": {"player_name": "Alice"}})
            room_created = ws_1.receive_json()
            assert room_created["type"] == "room_created"
            room_id = room_created["room_id"]
            lobby_session_token = room_created["payload"]["session_token"]

            initial_snapshot = ws_1.receive_json()
            assert initial_snapshot["type"] == "state_snapshot"
            assert initial_snapshot["payload"]["match_state"] == "waiting_for_players"
            assert initial_snapshot["payload"]["players"][0]["player_state"] == "in_lobby"

            with client.websocket_connect("/ws") as ws_2:
                ws_2.send_json(
                    {
                        "type": "join_room",
                        "room_id": room_id,
                        "payload": {"player_name": "Bob"},
                    }
                )

                room_joined = ws_2.receive_json()
                assert room_joined["type"] == "room_joined"
                assert room_joined["payload"]["resumed"] is False

                player_joined = ws_1.receive_json()
                assert player_joined["type"] == "player_joined"
                assert player_joined["payload"]["joined_player_name"] == "Bob"

                clan_snapshot_2 = ws_2.receive_json()
                clan_snapshot_1 = ws_1.receive_json()
                assert clan_snapshot_1["type"] == "state_snapshot"
                assert clan_snapshot_2["type"] == "state_snapshot"
                assert clan_snapshot_1["payload"]["match_state"] == "clan_selection"

                clan_ids = _first_three_clan_ids(clan_snapshot_1["payload"])
                ws_1.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids}})
                locked_snapshot_1 = ws_1.receive_json()
                locked_snapshot_2 = ws_2.receive_json()
                assert locked_snapshot_1["payload"]["match_state"] == "clan_selection"
                assert locked_snapshot_1["payload"]["players"][0]["clan_selection_locked"] is True
                assert locked_snapshot_1["payload"]["players"][1]["clan_selection_locked"] is False

                ws_2.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids}})
                draft_snapshot_2 = ws_2.receive_json()
                draft_snapshot_1 = ws_1.receive_json()
                assert draft_snapshot_1["payload"]["match_state"] == "drafting"
                assert len(draft_snapshot_1["payload"]["draft_offer"]) == DRAFT_OFFER_SIZE
                assert len(draft_snapshot_2["payload"]["draft_offer"]) == DRAFT_OFFER_SIZE

                team_ids_1 = _first_valid_team_ids(draft_snapshot_1["payload"]["draft_offer"])
                team_ids_2 = _first_valid_team_ids(draft_snapshot_2["payload"]["draft_offer"])

                for card_id in team_ids_1:
                    ws_1.send_json({"type": "select_card", "room_id": room_id, "payload": {"card_id": card_id}})
                    ws_1.receive_json()
                    ws_2.receive_json()

                ws_1.send_json({"type": "confirm_selection", "room_id": room_id, "payload": {}})
                player_ready_1 = ws_1.receive_json()
                player_ready_2 = ws_2.receive_json()
                assert player_ready_1["type"] == "player_ready"
                assert player_ready_2["type"] == "player_ready"
                assert player_ready_1["payload"]["state"]["match_state"] == "drafting"
                assert player_ready_1["payload"]["state"]["players"][0]["draft_locked"] is True

                ws_1.receive_json()
                ws_2.receive_json()

                for card_id in team_ids_2:
                    ws_2.send_json({"type": "select_card", "room_id": room_id, "payload": {"card_id": card_id}})
                    ws_2.receive_json()
                    ws_1.receive_json()

                ws_2.send_json({"type": "confirm_selection", "room_id": room_id, "payload": {}})
                game_started_1 = ws_1.receive_json()
                game_started_2 = ws_2.receive_json()
                assert game_started_1["type"] == "game_started"
                assert game_started_2["type"] == "game_started"
                assert game_started_1["payload"]["state"]["match_state"] == "round_selection"

                round_snapshot_1 = ws_1.receive_json()
                round_snapshot_2 = ws_2.receive_json()
                player_1_card_id = round_snapshot_1["payload"]["players"][0]["hand"][0]["id"]
                player_2_card_id = round_snapshot_2["payload"]["players"][1]["hand"][0]["id"]

                ws_1.send_json({"type": "select_card", "room_id": room_id, "payload": {"card_id": player_1_card_id}})
                selection_snapshot = ws_1.receive_json()
                assert selection_snapshot["payload"]["players"][0]["draft_card_id"] == player_1_card_id

                ws_1.send_json({"type": "set_pills", "room_id": room_id, "payload": {"pills": 3}})
                pills_snapshot = ws_1.receive_json()
                assert pills_snapshot["payload"]["players"][0]["drafted_pills"] == 3

                ws_1.send_json({"type": "set_overload", "room_id": room_id, "payload": {"overload": True}})
                overload_snapshot = ws_1.receive_json()
                assert overload_snapshot["payload"]["players"][0]["drafted_overload"] is True

                ws_1.send_json({"type": "confirm_selection", "room_id": room_id, "payload": {}})
                player_ready_1 = ws_1.receive_json()
                player_ready_2 = ws_2.receive_json()
                assert player_ready_1["type"] == "player_ready"
                assert player_ready_1["payload"]["state"]["match_state"] == "round_locked"
                assert player_ready_2["payload"]["state"]["players"][0]["draft_card_id"] == player_1_card_id
                assert player_ready_2["payload"]["state"]["players"][0]["drafted_pills"] is None
                assert player_ready_2["payload"]["state"]["players"][0]["drafted_overload"] is None

                ws_1.receive_json()
                ws_2.receive_json()

                ws_2.send_json({"type": "select_card", "room_id": room_id, "payload": {"card_id": player_2_card_id}})
                ws_2.receive_json()
                ws_2.send_json({"type": "set_pills", "room_id": room_id, "payload": {"pills": 2}})
                ws_2.receive_json()
                ws_2.send_json({"type": "confirm_selection", "room_id": room_id, "payload": {}})

                resolved_1 = ws_1.receive_json()
                resolved_2 = ws_2.receive_json()
                assert resolved_1["type"] == "round_resolved"
                assert resolved_2["type"] == "round_resolved"
                assert resolved_1["payload"]["round_result"]["player_1_attack"] > 0
                assert resolved_1["payload"]["round_result"]["player_2_attack"] > 0
                assert resolved_1["payload"]["round_result"]["player_1_pills_committed"] == 3
                assert resolved_1["payload"]["round_result"]["player_2_pills_committed"] == 2
                assert resolved_1["payload"]["round_result"]["player_1_overload"] is True
                assert resolved_1["payload"]["state"]["match_state"] == "round_selection"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_lobby:
            ws_lobby.send_json({"type": "create_room", "payload": {"player_name": "Alice"}})
            room_created = ws_lobby.receive_json()
            lobby_room_id = room_created["room_id"]
            lobby_session_token = room_created["payload"]["session_token"]
            ws_lobby.receive_json()

        with client.websocket_connect("/ws") as resumed_ws:
            resumed_ws.send_json(
                {
                    "type": "join_room",
                    "room_id": lobby_room_id,
                    "payload": {"player_name": "Alice", "session_token": lobby_session_token},
                }
            )
            resumed = resumed_ws.receive_json()
            assert resumed["type"] == "room_joined"
            assert resumed["payload"]["resumed"] is True
            resumed_snapshot = resumed_ws.receive_json()
            assert resumed_snapshot["type"] == "state_snapshot"
            assert resumed_snapshot["payload"]["match_state"] == "waiting_for_players"
            assert resumed_snapshot["payload"]["players"][0]["player_state"] == "in_lobby"


def test_invalid_action_returns_error_message() -> None:
    """Invalid gameplay actions should produce explicit protocol errors."""
    app = create_app(ACTIVE_URBAN2_PATH)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_1:
            ws_1.send_json({"type": "create_room", "payload": {"player_name": "Alice"}})
            room_id = ws_1.receive_json()["room_id"]
            ws_1.receive_json()

            with client.websocket_connect("/ws") as ws_2:
                ws_2.send_json({"type": "join_room", "room_id": room_id, "payload": {"player_name": "Bob"}})
                ws_2.receive_json()
                ws_1.receive_json()
                clan_snapshot_2 = ws_2.receive_json()
                clan_snapshot_1 = ws_1.receive_json()
                clan_ids = _first_three_clan_ids(clan_snapshot_1["payload"])

                ws_1.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids}})
                ws_1.receive_json()
                ws_2.receive_json()
                ws_2.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids}})
                ws_2.receive_json()
                ws_1.receive_json()

                ws_1.send_json({"type": "confirm_selection", "room_id": room_id, "payload": {}})
                error = ws_1.receive_json()
                assert error["type"] == "error"
                assert "exactly 4 cards" in error["payload"]["message"]


def test_opponent_disconnect_is_broadcast_cleanly() -> None:
    """The remaining player should be notified when the opponent disconnects."""
    app = create_app(ACTIVE_URBAN2_PATH)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_1:
            ws_1.send_json({"type": "create_room", "payload": {"player_name": "Alice"}})
            room_id = ws_1.receive_json()["room_id"]
            ws_1.receive_json()

            with client.websocket_connect("/ws") as ws_2:
                ws_2.send_json({"type": "join_room", "room_id": room_id, "payload": {"player_name": "Bob"}})
                ws_2.receive_json()
                ws_1.receive_json()
                ws_2.receive_json()
                ws_1.receive_json()

            disconnected = ws_1.receive_json()
            assert disconnected["type"] == "opponent_disconnected"
            snapshot = ws_1.receive_json()
            assert snapshot["type"] == "state_snapshot"
            assert snapshot["payload"]["match_state"] == "game_over"
            assert snapshot["payload"]["winner_id"] == 1
            finished = ws_1.receive_json()
            assert finished["type"] == "game_finished"


def test_clan_selection_and_private_draft_offer_are_synchronized_over_websocket() -> None:
    """Clan choices should gate the draft and each player should see only their own pool."""
    app = create_app(ACTIVE_URBAN2_PATH)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_1:
            ws_1.send_json({"type": "create_room", "payload": {"player_name": "Alice"}})
            room_created = ws_1.receive_json()
            room_id = room_created["room_id"]
            ws_1.receive_json()

            with client.websocket_connect("/ws") as ws_2:
                ws_2.send_json({"type": "join_room", "room_id": room_id, "payload": {"player_name": "Bob"}})
                ws_2.receive_json()
                ws_1.receive_json()
                clan_snapshot_2 = ws_2.receive_json()
                clan_snapshot_1 = ws_1.receive_json()

                clan_ids_1 = _first_three_clan_ids(clan_snapshot_1["payload"])
                clan_ids_2 = _last_three_clan_ids(clan_snapshot_2["payload"])
                clan_names_by_id = {
                    clan["id"]: clan["name"]
                    for clan in clan_snapshot_1["payload"]["clan_options"]
                }

                ws_1.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids_1}})
                ws_1.receive_json()
                ws_2.receive_json()
                ws_2.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids_2}})
                draft_snapshot_2 = ws_2.receive_json()
                draft_snapshot_1 = ws_1.receive_json()

                assert {
                    card["clan"] for card in draft_snapshot_1["payload"]["draft_offer"]
                } <= {clan_names_by_id[clan_id] for clan_id in clan_ids_1}
                assert {
                    card["clan"] for card in draft_snapshot_2["payload"]["draft_offer"]
                } <= {clan_names_by_id[clan_id] for clan_id in clan_ids_2}

                team_ids = _team_ids_with_active_bonus(draft_snapshot_1["payload"]["draft_offer"])
                for card_id in team_ids:
                    ws_1.send_json({"type": "select_card", "room_id": room_id, "payload": {"card_id": card_id}})
                    ws_1.receive_json()
                    snapshot_after_pick_2 = ws_2.receive_json()

                alice_from_bob_view = snapshot_after_pick_2["payload"]["players"][0]
                assert alice_from_bob_view["active_clan_bonuses"]
                assert all(card["bonus_active"] is True for card in alice_from_bob_view["draft_selected_cards"] if card["clan"] in alice_from_bob_view["active_clan_bonuses"])


def test_invalid_star_cap_team_is_rejected_over_websocket() -> None:
    """The server should refuse draft locks that violate the 8-star team cap."""
    app = create_app(ACTIVE_URBAN2_PATH)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_1:
            ws_1.send_json({"type": "create_room", "payload": {"player_name": "Alice"}})
            room_created = ws_1.receive_json()
            room_id = room_created["room_id"]
            ws_1.receive_json()

            with client.websocket_connect("/ws") as ws_2:
                ws_2.send_json({"type": "join_room", "room_id": room_id, "payload": {"player_name": "Bob"}})
                ws_2.receive_json()
                ws_1.receive_json()
                clan_snapshot_2 = ws_2.receive_json()
                clan_snapshot_1 = ws_1.receive_json()
                clan_ids = _first_three_clan_ids(clan_snapshot_1["payload"])

                ws_1.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids}})
                ws_1.receive_json()
                ws_2.receive_json()
                ws_2.send_json({"type": "select_clans", "room_id": room_id, "payload": {"clan_ids": clan_ids}})
                ws_2.receive_json()
                draft_snapshot_1 = ws_1.receive_json()

                for card_id in _first_invalid_star_cap_team_ids(draft_snapshot_1["payload"]["draft_offer"]):
                    ws_1.send_json({"type": "select_card", "room_id": room_id, "payload": {"card_id": card_id}})
                    ws_1.receive_json()
                    ws_2.receive_json()

                ws_1.send_json({"type": "confirm_selection", "room_id": room_id, "payload": {}})
                error = ws_1.receive_json()
                assert error["type"] == "error"
                assert "cannot exceed 8 stars" in error["payload"]["message"]
