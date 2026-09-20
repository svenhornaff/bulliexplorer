"""Unit tests for app.routes.posts._poi_category_chips.

Phase 3a, docs/dev/bulliexplorer_experience_2027.md — powers the "Places
along the way" chip row below the map. No DB needed: PointOfInterest rows
are built directly, ``category`` is the only field this function reads.
"""

from __future__ import annotations

from app.models.point_of_interest import PointOfInterest
from app.routes.posts import _poi_category_chips


def _poi(*, poi_id: int = 1, category: str) -> PointOfInterest:
    return PointOfInterest(
        id=poi_id,
        post_id=1,
        name=f"POI {poi_id}",
        category=category,
        location=None,  # not read by _poi_category_chips
    )


def test_empty_list_returns_no_chips():
    assert _poi_category_chips([]) == []


def test_single_category_humanised():
    chips = _poi_category_chips([_poi(category="campsite")])
    assert chips == [{"category": "campsite", "label": "Campsite"}]


def test_snake_case_category_only_capitalises_first_word():
    """Matches categoryLabel() in static/js/post-map.js exactly —
    "gas_station" -> "Gas station", not "Gas Station"."""
    chips = _poi_category_chips([_poi(category="gas_station")])
    assert chips == [{"category": "gas_station", "label": "Gas station"}]

    chips = _poi_category_chips([_poi(category="bike_shop")])
    assert chips == [{"category": "bike_shop", "label": "Bike shop"}]


def test_duplicate_categories_deduplicated_keeping_first_occurrence_order():
    pois = [
        _poi(poi_id=1, category="viewpoint"),
        _poi(poi_id=2, category="campsite"),
        _poi(poi_id=3, category="viewpoint"),
        _poi(poi_id=4, category="restaurant"),
        _poi(poi_id=5, category="campsite"),
    ]
    chips = _poi_category_chips(pois)
    assert [c["category"] for c in chips] == ["viewpoint", "campsite", "restaurant"]


def test_falsy_category_is_skipped_without_error():
    pois = [_poi(poi_id=1, category=""), _poi(poi_id=2, category="campsite")]
    chips = _poi_category_chips(pois)
    assert chips == [{"category": "campsite", "label": "Campsite"}]
