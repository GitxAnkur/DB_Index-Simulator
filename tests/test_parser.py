from __future__ import annotations

import pytest

from app.query_parser import Lexicon, parse_query


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Samsung smartphone", {"category": "Smartphone", "brand": "Samsung"}),
        ("Laptops", {"category": "Laptop"}),
        ("Laptop under 80000", {"category": "Laptop", "max_price": 80000}),
        ("Black laptop under 80000", {"category": "Laptop", "color": "Black", "max_price": 80000}),
        ("Lightweight laptop for programming", {"category": "Laptop", "use_case": "programming", "keywords": ["lightweight"]}),
        ("Wireless headphones for travel", {"category": "Headphones", "use_case": "travel", "keywords": ["wireless"]}),
        ("Gaming monitor under 30000", {"category": "Monitor", "use_case": "gaming", "max_price": 30000}),
        ("gaming keyboard under 5000", {"category": "Keyboard", "use_case": "gaming", "max_price": 5000}),
        ("tablet above 20000", {"category": "Tablet", "min_price": 20000}),
        ("blue smartwatch", {"category": "Smartwatch", "color": "Blue"}),
        ("camera for photography", {"category": "Camera", "use_case": "photography"}),
        ("speakers with good bass", {"category": "Speaker", "keywords": ["bass"]}),
        ("BETWEEN 20000 AND 30000 HEADPHONES", {"category": "Headphones", "min_price": 20000, "max_price": 30000}),
        ("headphones under 80k", {"category": "Headphones", "max_price": 80000}),
        ("laptop from 50000 to 90000", {"category": "Laptop", "min_price": 50000, "max_price": 90000}),
    ],
)
def test_parser_examples(query, expected):
    parsed = parse_query(query)
    for key, value in expected.items():
        assert getattr(parsed, key) == value, (query, key, getattr(parsed, key), value)


def test_parser_preserves_original_query():
    parsed = parse_query("  Black Laptop under 80000  ")
    assert parsed.original_query == "Black Laptop under 80000"
    assert parsed.normalized_query == "black laptop under 80000"


def test_parser_does_not_invent_filters():
    parsed = parse_query("something nice and comfortable")
    assert parsed.category is None
    assert parsed.brand is None
    assert parsed.color is None
    assert parsed.min_price is None
    assert parsed.max_price is None
    assert parsed.use_case is None
    assert parsed.keywords


def test_noise_cancelling_is_not_noise_brand():
    parsed = parse_query("noise cancelling headphones")
    assert parsed.category == "Headphones"
    assert parsed.brand is None
    assert "noise" in parsed.keywords


def test_brand_with_space_and_hyphen():
    lex = Lexicon(["Ultimate Ears", "Audio-Technica", "Sony"])
    assert parse_query("ultimate ears speaker", lex).brand == "Ultimate Ears"
    assert parse_query("audio technica headphones", lex).brand == "Audio-Technica"


def test_ambiguous_around_price_is_not_guessed():
    parsed = parse_query("laptop around 50000")
    assert parsed.min_price is None
    assert parsed.max_price is None


def test_empty_and_too_long_queries_rejected():
    with pytest.raises(ValueError):
        parse_query("   ")
    with pytest.raises(ValueError):
        parse_query("x" * 501)
    with pytest.raises(ValueError):
        parse_query(None)  # type: ignore[arg-type]
