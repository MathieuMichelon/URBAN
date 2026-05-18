"""Draft and team-building helpers shared by solo and online modes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
import random

from core.errors import CardNotFoundError, InvalidGameSetupError, InvalidMoveError
from core.effects import compute_active_clans
from core.models import Card

DRAFT_OFFER_SIZE = 12
TEAM_SIZE = 4
TEAM_STAR_CAP = 8
DRAFT_MIN_STAR_DISTRIBUTION = {
    3: 3,
    2: 3,
    1: 3,
}
DRAFT_MIN_CLAN_DISTRIBUTION = 3


@dataclass(frozen=True, slots=True)
class TeamValidation:
    """Computed validation details for one candidate team."""

    selected_card_ids: tuple[str, ...]
    total_stars: int
    active_clans: tuple[str, ...]
    selected_card_previews: tuple["DraftCardPreview", ...]
    is_full_team: bool
    is_valid: bool


@dataclass(frozen=True, slots=True)
class DraftCardPreview:
    """UI-friendly preview for one currently selected draft card."""

    card_id: str
    clan: str
    stars: int
    bonus_active: bool


@dataclass(slots=True)
class DraftSeatState:
    """In-progress draft selection for one participant."""

    selected_card_ids: list[str] = field(default_factory=list)
    locked: bool = False


@dataclass(slots=True)
class DraftPhase:
    """Shared draft offer plus per-player draft selections."""

    offer: list[Card]
    seats: dict[int, DraftSeatState] = field(default_factory=lambda: {1: DraftSeatState(), 2: DraftSeatState()})

    def selected_cards(self, player_id: int) -> list[Card]:
        """Return the currently selected cards for one player."""
        return [self._offer_by_id()[card_id] for card_id in self.seats[player_id].selected_card_ids]

    def validation_for(self, player_id: int) -> TeamValidation:
        """Return selection validation details for one player."""
        return describe_team_selection(self.selected_cards(player_id))

    def toggle_card(self, player_id: int, card_id: str) -> TeamValidation:
        """Toggle one card inside a player's draft selection."""
        seat = self.seats[player_id]
        if seat.locked:
            raise InvalidMoveError("This draft selection is already locked.")

        offer_by_id = self._offer_by_id()
        if card_id not in offer_by_id:
            raise CardNotFoundError(f"Card '{card_id}' is not part of the current draft offer.")

        if card_id in seat.selected_card_ids:
            seat.selected_card_ids.remove(card_id)
            return self.validation_for(player_id)

        if len(seat.selected_card_ids) >= TEAM_SIZE:
            raise InvalidMoveError(f"You can only draft {TEAM_SIZE} cards.")

        seat.selected_card_ids.append(card_id)
        return self.validation_for(player_id)

    def lock_team(self, player_id: int) -> TeamValidation:
        """Validate and lock one player's team."""
        seat = self.seats[player_id]
        if seat.locked:
            raise InvalidMoveError("This team is already locked.")

        selected_cards = self.selected_cards(player_id)
        validate_team(selected_cards)
        seat.locked = True
        return describe_team_selection(selected_cards)

    def teams_ready(self) -> bool:
        """Return whether both players locked a legal team."""
        return self.seats[1].locked and self.seats[2].locked

    def build_locked_teams(self) -> dict[int, list[Card]]:
        """Return the final teams after both players locked."""
        if not self.teams_ready():
            raise InvalidMoveError("Both players must lock their team before starting the match.")
        return {
            player_id: resolve_team_from_ids(self.offer, seat.selected_card_ids)
            for player_id, seat in self.seats.items()
        }

    def _offer_by_id(self) -> dict[str, Card]:
        """Index the shared draft offer by identifier."""
        return {card.id: card for card in self.offer}


def build_draft_offer(cards: list[Card], *, seed: str | int | None = None) -> list[Card]:
    """Return a shared draft offer sampled from the active roster."""
    if len(cards) < DRAFT_OFFER_SIZE:
        raise InvalidGameSetupError(
            f"The roster must contain at least {DRAFT_OFFER_SIZE} cards to build a draft offer."
        )

    generator = random.Random(seed)
    roster_clans = _validate_roster_supports_clan_distribution(cards)
    require_star_distribution = _roster_supports_star_distribution(cards)

    if require_star_distribution:
        for _ in range(100):
            offer = _build_balanced_offer(cards, generator, roster_clans=roster_clans)
            if (
                offer is not None
                and _offer_supports_valid_team(offer)
                and _offer_matches_star_distribution(offer)
                and _offer_matches_clan_distribution(offer, required_clans=roster_clans)
            ):
                return offer

    for _ in range(2000):
        offer = list(generator.sample(cards, DRAFT_OFFER_SIZE))
        if (
            _offer_supports_valid_team(offer)
            and (not require_star_distribution or _offer_matches_star_distribution(offer))
            and _offer_matches_clan_distribution(offer, required_clans=roster_clans)
        ):
            return offer

    raise InvalidGameSetupError("Unable to generate a valid draft offer from the current roster.")


def resolve_team_from_ids(offer: list[Card], selected_card_ids: list[str]) -> list[Card]:
    """Build one team from a draft offer and selected identifiers."""
    offer_by_id = {card.id: card for card in offer}
    selected_cards: list[Card] = []

    for card_id in selected_card_ids:
        try:
            selected_cards.append(offer_by_id[card_id])
        except KeyError as error:
            raise CardNotFoundError(f"Card '{card_id}' is not part of the current draft offer.") from error

    validate_team(selected_cards)
    return selected_cards


def validate_team(cards: list[Card]) -> None:
    """Ensure one drafted team respects team size and star cap."""
    if len(cards) != TEAM_SIZE:
        raise InvalidMoveError(f"A team must contain exactly {TEAM_SIZE} cards.")

    card_ids = [card.id for card in cards]
    if len(set(card_ids)) != len(card_ids):
        raise InvalidMoveError("A team cannot contain duplicate cards.")

    total_stars = compute_team_stars(cards)
    if total_stars > TEAM_STAR_CAP:
        raise InvalidMoveError(
            f"A team cannot exceed {TEAM_STAR_CAP} stars. Current total: {total_stars}."
        )


def compute_team_stars(cards: list[Card]) -> int:
    """Return the star total of one team."""
    return sum(card.stars for card in cards)

def describe_team_selection(selected_cards: list[Card]) -> TeamValidation:
    """Return validation and clan preview details for a draft selection."""
    total_stars = compute_team_stars(selected_cards)
    active_clans = tuple(sorted(compute_active_clans(selected_cards)))
    selected_card_previews = tuple(
        DraftCardPreview(
            card_id=card.id,
            clan=card.clan,
            stars=card.stars,
            bonus_active=card.clan in active_clans,
        )
        for card in selected_cards
    )
    is_full_team = len(selected_cards) == TEAM_SIZE
    is_valid = is_full_team and total_stars <= TEAM_STAR_CAP and len({card.id for card in selected_cards}) == len(selected_cards)
    return TeamValidation(
        selected_card_ids=tuple(card.id for card in selected_cards),
        total_stars=total_stars,
        active_clans=active_clans,
        selected_card_previews=selected_card_previews,
        is_full_team=is_full_team,
        is_valid=is_valid,
    )


def _offer_supports_valid_team(cards: list[Card]) -> bool:
    """Return whether the offer contains at least one legal 4-card team."""
    return any(compute_team_stars(list(team)) <= TEAM_STAR_CAP for team in combinations(cards, TEAM_SIZE))


def _roster_supports_star_distribution(cards: list[Card]) -> bool:
    """Return whether the roster can satisfy the preferred draft star spread."""
    return all(
        sum(1 for card in cards if card.stars == stars) >= minimum
        for stars, minimum in DRAFT_MIN_STAR_DISTRIBUTION.items()
    )


def _offer_matches_star_distribution(cards: list[Card]) -> bool:
    """Return whether one offer includes the minimum desired star variety."""
    return all(
        sum(1 for card in cards if card.stars == stars) >= minimum
        for stars, minimum in DRAFT_MIN_STAR_DISTRIBUTION.items()
    )


def _offer_matches_clan_distribution(cards: list[Card], *, required_clans: set[str] | None = None) -> bool:
    """Return whether one offer includes the minimum desired clan variety."""
    clan_counts = Counter(card.clan for card in cards)
    clans = required_clans if required_clans is not None else set(clan_counts)
    return all(clan_counts[clan] >= DRAFT_MIN_CLAN_DISTRIBUTION for clan in clans)


def _validate_roster_supports_clan_distribution(cards: list[Card]) -> set[str]:
    """Return roster clans or raise when the draft clan minimum cannot be satisfied."""
    clan_counts = Counter(card.clan for card in cards)
    roster_clans = set(clan_counts)
    if len(roster_clans) * DRAFT_MIN_CLAN_DISTRIBUTION > DRAFT_OFFER_SIZE:
        raise InvalidGameSetupError(
            f"A {DRAFT_OFFER_SIZE}-card draft offer cannot include at least "
            f"{DRAFT_MIN_CLAN_DISTRIBUTION} cards for each of {len(roster_clans)} clans."
        )

    missing_clans = sorted(
        clan
        for clan, count in clan_counts.items()
        if count < DRAFT_MIN_CLAN_DISTRIBUTION
    )
    if missing_clans:
        joined_clans = ", ".join(missing_clans)
        raise InvalidGameSetupError(
            f"The roster must contain at least {DRAFT_MIN_CLAN_DISTRIBUTION} cards "
            f"for each clan to build a draft offer. Missing: {joined_clans}."
        )

    return roster_clans


def _build_balanced_offer(
    cards: list[Card],
    generator: random.Random,
    *,
    roster_clans: set[str],
) -> list[Card] | None:
    """Sample an offer with enough clan and star variety."""
    selected: list[Card] = []
    selected_ids: set[str] = set()

    for clan in sorted(roster_clans):
        bucket = [card for card in cards if card.clan == clan]
        picked = generator.sample(bucket, DRAFT_MIN_CLAN_DISTRIBUTION)
        selected.extend(picked)
        selected_ids.update(card.id for card in picked)

    for stars, minimum in DRAFT_MIN_STAR_DISTRIBUTION.items():
        current_count = sum(1 for card in selected if card.stars == stars)
        needed = minimum - current_count
        if needed <= 0:
            continue

        if len(selected) + needed > DRAFT_OFFER_SIZE:
            return None

        bucket = [
            card
            for card in cards
            if card.stars == stars and card.id not in selected_ids
        ]
        if len(bucket) < needed:
            return None

        picked = generator.sample(bucket, needed)
        selected.extend(picked)
        selected_ids.update(card.id for card in picked)

    if len(selected) > DRAFT_OFFER_SIZE:
        return None

    remaining_pool = [card for card in cards if card.id not in selected_ids]
    selected.extend(generator.sample(remaining_pool, DRAFT_OFFER_SIZE - len(selected)))
    generator.shuffle(selected)
    return selected
