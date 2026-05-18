"""Unit tests for the shared draft and team-building helpers."""

from collections import Counter
from itertools import combinations

import pytest

from core.draft import DraftPhase, TEAM_SIZE, TEAM_STAR_CAP, build_draft_offer
from core.errors import InvalidGameSetupError, InvalidMoveError


def test_build_draft_offer_returns_ten_cards_and_supports_a_legal_team(sample_cards) -> None:
    """A generated draft offer should expose ten varied cards and at least one legal team."""
    offer = build_draft_offer(sample_cards, seed="ROOM42")
    star_counts = Counter(card.stars for card in offer)
    clan_counts = Counter(card.clan for card in offer)

    assert len(offer) == 10
    assert len({card.id for card in offer}) == 10
    assert star_counts[3] >= 2
    assert star_counts[2] >= 3
    assert star_counts[1] >= 2
    assert all(clan_counts[clan] >= 2 for clan in {card.clan for card in sample_cards})
    assert any(
        sum(card.stars for card in team) <= TEAM_STAR_CAP
        for team in combinations(offer, TEAM_SIZE)
    )


def test_build_draft_offer_consistently_keeps_size_uniqueness_stars_clans_and_legal_team(sample_cards) -> None:
    """Draft offers should combine all balancing constraints without duplicates."""
    for seed in range(20):
        offer = build_draft_offer(sample_cards, seed=seed)
        star_counts = Counter(card.stars for card in offer)
        clan_counts = Counter(card.clan for card in offer)

        assert len(offer) == 10
        assert len({card.id for card in offer}) == 10
        assert star_counts[3] >= 2
        assert star_counts[2] >= 3
        assert star_counts[1] >= 2
        assert all(clan_counts[clan] >= 2 for clan in {card.clan for card in sample_cards})
        assert any(
            sum(card.stars for card in team) <= TEAM_STAR_CAP
            for team in combinations(offer, TEAM_SIZE)
        )


def test_build_draft_offer_rejects_roster_without_enough_cards_in_each_clan(card_factory) -> None:
    """A clear setup error should be raised when any roster clan cannot supply two cards."""
    roster = [
        card_factory("alpha_1", clan="Alpha", stars=1),
        card_factory("beta_1", clan="Beta", stars=1),
        card_factory("beta_2", clan="Beta", stars=2),
        card_factory("beta_3", clan="Beta", stars=2),
        card_factory("beta_4", clan="Beta", stars=3),
        card_factory("beta_5", clan="Beta", stars=3),
        card_factory("gamma_1", clan="Gamma", stars=1),
        card_factory("gamma_2", clan="Gamma", stars=2),
        card_factory("gamma_3", clan="Gamma", stars=3),
        card_factory("gamma_4", clan="Gamma", stars=1),
    ]

    with pytest.raises(InvalidGameSetupError, match="at least 2 cards for each clan"):
        build_draft_offer(roster, seed="bad-clan")


def test_draft_phase_tracks_selection_validation(card_factory) -> None:
    """Selecting cards should update star totals and clan bonus preview."""
    offer = [
        card_factory("a1", clan="Alpha", stars=2),
        card_factory("a2", clan="Alpha", stars=2),
        card_factory("b1", clan="Beta", stars=2),
        card_factory("b2", clan="Beta", stars=2),
        card_factory("c1", clan="Gamma", stars=3),
        card_factory("c2", clan="Gamma", stars=1),
        card_factory("c3", clan="Gamma", stars=1),
        card_factory("c4", clan="Gamma", stars=1),
        card_factory("d1", clan="Delta", stars=1),
        card_factory("d2", clan="Delta", stars=1),
    ]
    draft = DraftPhase(offer)

    draft.toggle_card(1, "a1")
    draft.toggle_card(1, "a2")
    draft.toggle_card(1, "b1")
    validation = draft.toggle_card(1, "d1")

    assert validation.total_stars == 7
    assert validation.is_valid is True
    assert validation.is_full_team is True
    assert validation.active_clans == ("Alpha",)
    assert {preview.card_id: preview.bonus_active for preview in validation.selected_card_previews} == {
        "a1": True,
        "a2": True,
        "b1": False,
        "d1": False,
    }


def test_draft_phase_accepts_a_valid_exactly_four_card_selection(card_factory) -> None:
    """A 4-card selection under the star cap should lock successfully."""
    offer = [
        card_factory("a1", clan="Alpha", stars=2),
        card_factory("a2", clan="Alpha", stars=2),
        card_factory("b1", clan="Beta", stars=2),
        card_factory("c1", clan="Gamma", stars=1),
        card_factory("x1", stars=3),
        card_factory("x2", stars=3),
        card_factory("x3", stars=3),
        card_factory("x4", stars=1),
        card_factory("x5", stars=1),
        card_factory("x6", stars=1),
    ]
    draft = DraftPhase(offer)

    for card_id in ("a1", "a2", "b1", "c1"):
        draft.toggle_card(1, card_id)

    validation = draft.lock_team(1)

    assert validation.is_full_team is True
    assert validation.total_stars == 7
    assert validation.is_valid is True
    assert draft.seats[1].locked is True


def test_draft_phase_rejects_locking_a_team_over_the_star_cap(card_factory) -> None:
    """Locking should fail when the team exceeds the 8-star cap."""
    offer = [
        card_factory("x1", stars=3),
        card_factory("x2", stars=3),
        card_factory("x3", stars=3),
        card_factory("x4", stars=1),
        card_factory("x5", stars=1),
        card_factory("x6", stars=1),
        card_factory("x7", stars=1),
        card_factory("x8", stars=1),
        card_factory("x9", stars=1),
        card_factory("x10", stars=1),
    ]
    draft = DraftPhase(offer)

    for card_id in ("x1", "x2", "x3", "x4"):
        draft.toggle_card(1, card_id)

    with pytest.raises(InvalidMoveError, match="cannot exceed 8 stars"):
        draft.lock_team(1)


def test_draft_phase_rejects_locking_with_fewer_than_four_cards(card_factory) -> None:
    """Locking should fail when the player selected fewer than 4 cards."""
    offer = [
        card_factory("a1", stars=2),
        card_factory("a2", stars=2),
        card_factory("a3", stars=2),
        card_factory("a4", stars=1),
        card_factory("a5", stars=1),
        card_factory("a6", stars=1),
        card_factory("a7", stars=1),
        card_factory("a8", stars=1),
        card_factory("a9", stars=1),
        card_factory("a10", stars=1),
    ]
    draft = DraftPhase(offer)

    for card_id in ("a1", "a2", "a3"):
        draft.toggle_card(1, card_id)

    with pytest.raises(InvalidMoveError, match="exactly 4 cards"):
        draft.lock_team(1)


def test_draft_phase_bonus_activation_preview_marks_selected_cards(card_factory) -> None:
    """Selected draft cards should expose whether their clan bonus is active or inactive."""
    offer = [
        card_factory("alpha_1", clan="Alpha", stars=2),
        card_factory("alpha_2", clan="Alpha", stars=2),
        card_factory("beta_1", clan="Beta", stars=2),
        card_factory("gamma_1", clan="Gamma", stars=1),
        card_factory("x1", stars=3),
        card_factory("x2", stars=3),
        card_factory("x3", stars=3),
        card_factory("x4", stars=1),
        card_factory("x5", stars=1),
        card_factory("x6", stars=1),
    ]
    draft = DraftPhase(offer)

    for card_id in ("alpha_1", "alpha_2", "beta_1", "gamma_1"):
        draft.toggle_card(1, card_id)

    validation = draft.validation_for(1)
    preview_by_id = {
        preview.card_id: preview.bonus_active
        for preview in validation.selected_card_previews
    }

    assert validation.active_clans == ("Alpha",)
    assert preview_by_id == {
        "alpha_1": True,
        "alpha_2": True,
        "beta_1": False,
        "gamma_1": False,
    }
