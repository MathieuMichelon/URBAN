"""Entry point for the local 1v1 card game prototype."""

from pathlib import Path

from ai.bot import HeuristicAIChoiceProvider
from ui.gui import GameWindow


def main() -> None:
    """Launch the Pygame prototype."""
    project_root = Path(__file__).resolve().parent
    window = GameWindow(
        cards_path=project_root / "data" / "cards.json",
        ai_provider=HeuristicAIChoiceProvider(),
    )
    window.run()


if __name__ == "__main__":
    main()
