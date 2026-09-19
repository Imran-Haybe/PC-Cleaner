"""SEL-xx: the '1,3,5-8' / 'all' selection parser."""

import tracemalloc

import pytest

from pc_cleaner import parse_selection


@pytest.mark.parametrize("text, max_index, expected", [
    ("1", 5, [0]),                                   # SEL-01
    ("1,3,5", 5, [0, 2, 4]),                         # SEL-02
    ("2-4", 5, [1, 2, 3]),                           # SEL-03
    ("1,3,5-8", 8, [0, 2, 4, 5, 6, 7]),              # SEL-04
    ("all", 5, [0, 1, 2, 3, 4]),                     # SEL-05
    ("ALL", 5, [0, 1, 2, 3, 4]),
    ("  All  ", 5, [0, 1, 2, 3, 4]),
    ("1, 3 - 5", 5, [0, 2, 3, 4]),                   # SEL-06 spaces
    ("1,1,1", 5, [0]),                               # SEL-07 repeats
    ("1,,2", 5, [0, 1]),                             # SEL-11
    ("1", 5, [0]),                                   # SEL-09 lower bound
    ("5", 5, [4]),                                   # SEL-09 upper bound
])
def test_SEL_valid_selections(text, max_index, expected):
    assert parse_selection(text, max_index) == expected


@pytest.mark.parametrize("text", [
    "0", "6",                                        # SEL-08 just outside 1..5
    "abc", "1,abc", "1.5", "-1", "-", "1-", "1--3", "1-2-3",   # SEL-10
    ",", "", "   ",                                  # SEL-11 nothing selected
    "0-3", "3-9",                                    # ranges touching outside bounds
    "5-3",                                           # SEL-12 reversed range on its own
])
def test_SEL_invalid_selections_return_empty(text):
    assert parse_selection(text, 5) == []


def test_SEL_12_reversed_range_mixed_with_valid_items_is_rejected():
    """H5: '1,5-3' must not quietly become just [1]. Silent partial selection
    means the user deletes fewer (or different) files than they typed."""
    assert parse_selection("1,5-3", 5) == []


def test_SEL_13_huge_range_is_rejected_without_building_it_in_memory():
    """H5: the range is expanded into a set BEFORE the bounds check.
    2 million is safe to try; 999999999 would eat gigabytes."""
    tracemalloc.start()
    try:
        result = parse_selection("1-2000000", 5)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result == []
    assert peak < 10 * 1024 * 1024, f"peak memory {peak / 1024 ** 2:.0f} MB for an invalid input"


def test_SEL_14_indexes_map_to_the_right_items():
    items = [f"item{i}" for i in range(1, 51)]
    picked = [items[i] for i in parse_selection("1,25,50", 50)]
    assert picked == ["item1", "item25", "item50"]
