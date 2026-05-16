"""Custom exceptions for game validation."""


class GameError(Exception):
    """Base class for game-related errors."""


class InvalidCardDefinitionError(GameError):
    """Raised when a card payload is invalid."""


class CardSetLoadError(GameError):
    """Raised when a card set file cannot be loaded."""


class CardSetFormatError(CardSetLoadError):
    """Raised when a card set JSON structure is invalid."""


class SaveGameError(GameError):
    """Raised when a save game cannot be handled correctly."""


class SaveGameFormatError(SaveGameError):
    """Raised when a save game JSON structure is invalid."""


class InvalidGameSetupError(GameError):
    """Raised when the initial game setup is inconsistent."""


class GameAlreadyFinishedError(GameError):
    """Raised when trying to play after the match ended."""


class InvalidMoveError(GameError):
    """Raised when a choice is not legal."""


class RoundSynchronizationError(InvalidMoveError):
    """Raised when a submitted action targets the wrong round."""


class SelectionAlreadySubmittedError(InvalidMoveError):
    """Raised when a player submits more than one action for the same round."""


class CardNotFoundError(InvalidMoveError):
    """Raised when a chosen card cannot be found."""


class CardAlreadyPlayedError(InvalidMoveError):
    """Raised when a player reuses a spent card."""


class NotEnoughPillsError(InvalidMoveError):
    """Raised when a player spends too many pills."""


class InvalidRoundNumberError(GameError):
    """Raised when the game state contains an invalid round number."""
