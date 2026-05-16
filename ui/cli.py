"""Minimal CLI adapters for local play."""

from __future__ import annotations

from core.enums import GameStatus, RoundOutcome
from core.interfaces import MatchObserver
from core.models import GameState, PlayerState, RoundChoice, RoundResult


class HumanCLIChoiceProvider:
    """Ask the user to choose a card and pill count."""

    def choose_action(self, game_state: GameState, player: PlayerState) -> RoundChoice:
        """Read a valid choice from standard input."""
        print()
        print(f"Round {game_state.current_round} - Player {player.player_id}")
        print(f"PV: {player.hit_points} | Pills: {player.pills}")

        available_cards = player.available_cards()
        for index, card in enumerate(available_cards, start=1):
            print(
                f"{index}. {card.name} "
                f"(id={card.id}, power={card.power}, damage={card.damage})"
            )

        while True:
            try:
                card_index = int(input("Choose a card number: ").strip())
                selected_card = available_cards[card_index - 1]
                pills = int(input("Choose how many pills to spend: ").strip())
                return RoundChoice(card_id=selected_card.id, pills_committed=pills)
            except (IndexError, ValueError):
                print("Invalid input. Please try again.")


class ConsoleObserver(MatchObserver):
    """Display match events in the terminal."""

    def on_match_started(self, state: GameState) -> None:
        """Print the initial game summary."""
        print("=== Urban Duel Prototype ===")
        print("Player 1 uses the CLI. Player 2 uses a simple AI.")

    def on_round_resolved(self, state: GameState, result: RoundResult) -> None:
        """Print the outcome of one round."""
        player_1 = state.get_player(1)
        player_2 = state.get_player(2)

        print()
        print(f"Round {result.round_number} resolved")
        print(f"Player 1 attack: {result.player_1_attack}")
        print(f"Player 2 attack: {result.player_2_attack}")

        if result.outcome is RoundOutcome.TIE:
            print("Round result: tie, no damage dealt.")
        else:
            print(f"Round winner: Player {result.winner_id}")
            print(f"Damage dealt: {result.damage_dealt}")

        print(
            f"Current score -> P1: {player_1.hit_points} HP / {player_1.pills} pills | "
            f"P2: {player_2.hit_points} HP / {player_2.pills} pills"
        )

    def on_match_finished(self, state: GameState) -> None:
        """Print the final result."""
        print()
        if state.status is GameStatus.DRAW:
            print("Match finished: draw.")
        elif state.status is GameStatus.PLAYER_1_WON:
            print("Match finished: Player 1 wins.")
        elif state.status is GameStatus.PLAYER_2_WON:
            print("Match finished: Player 2 wins.")
