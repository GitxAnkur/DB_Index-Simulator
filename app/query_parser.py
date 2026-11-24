"""Rule-based natural-language query parser.

The parser extracts only filters that are explicitly supported by the query.
It never invents a brand, colour, category or price range. The original query
is always preserved for semantic (vector) search.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Iterable

from . import db

# Category synonyms. Values are the exact labels stored in PostgreSQL.
CATEGORY_SYNONYMS: dict[str, str] = {
    "gaming accessories": "Gaming Accessories",
    "gaming accessory": "Gaming Accessories",
    "accessories": "Gaming Accessories",
    "laptops": "Laptop",
    "laptop": "Laptop",
    "notebooks": "Laptop",
    "notebook": "Laptop",
    "smartphones": "Smartphone",
    "smartphone": "Smartphone",
    "mobile phones": "Smartphone",
    "mobile phone": "Smartphone",
    "phones": "Smartphone",
    "phone": "Smartphone",
    "mobiles": "Smartphone",
    "mobile": "Smartphone",
    "headphones": "Headphones",
    "headphone": "Headphones",
    "headsets": "Headphones",
    "headset": "Headphones",
    "earphones": "Headphones",
    "earphone": "Headphones",
    "earbuds": "Headphones",
    "tablets": "Tablet",
    "tablet": "Tablet",
    "smartwatches": "Smartwatch",
    "smartwatch": "Smartwatch",
    "watches": "Smartwatch",
    "watch": "Smartwatch",
    "monitors": "Monitor",
    "monitor": "Monitor",
    "displays": "Monitor",
    "display": "Monitor",
    "keyboards": "Keyboard",
    "keyboard": "Keyboard",
    "cameras": "Camera",
    "camera": "Camera",
    "dslr": "Camera",
    "speakers": "Speaker",
    "speaker": "Speaker",
    "soundbars": "Speaker",
    "soundbar": "Speaker",
}

COLOR_ALIASES: dict[str, str] = {
    "black": "Black",
    "blue": "Blue",
    "green": "Green",
    "grey": "Grey",
    "gray": "Grey",
    "red": "Red",
    "silver": "Silver",
    "white": "White",
}

STATIC_BRANDS = [
    "ASUS", "Acer", "Amazfit", "Apple", "Audio-Technica", "BenQ", "Boat",
    "Bose", "Canon", "Corsair", "Dell", "Fitbit", "Fossil", "Fujifilm",
    "Garmin", "GoPro", "Google", "HP", "HyperX", "JBL", "Jabra", "Keychron",
    "LG", "Lenovo", "Logitech", "MSI", "Marshall", "Motorola", "Nikon",
    "Noise", "OPPO", "OnePlus", "Panasonic", "Razer", "Realme", "Redragon",
    "Samsung", "Sennheiser", "Sony", "SteelSeries", "Tribit",
    "Ultimate Ears", "ViewSonic", "Vivo", "Xiaomi",
]

STATIC_USE_CASES = [
    "PC gaming", "business", "calls", "competitive gaming", "console gaming",
    "content creation", "design", "desktop audio", "drawing", "entertainment",
    "everyday productivity", "everyday use", "everyday wear", "fitness",
    "gaming", "gaming setup", "general computing", "health tracking",
    "home entertainment", "music", "office work", "outdoor listening",
    "parties", "photography", "portrait photography", "programming", "reading",
    "running", "sports", "streaming", "study", "travel", "travel photography",
    "typing", "video creation", "video editing", "vlogging",
    "wildlife photography", "work",
]

STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "best", "buy", "by",
    "cheap", "for", "from", "good", "great", "in", "into", "is", "it", "of",
    "on", "or", "please", "product", "products", "quality", "show", "the",
    "to", "top", "with", "within", "under", "below", "above", "over", "less",
    "than", "greater", "more", "between", "upto", "up", "max", "maximum",
    "min", "minimum", "rs", "inr", "rupees", "price", "budget", "around",
    "about", "approx", "approximately", "find", "me", "looking", "want",
    "need", "some", "that", "this", "which", "has", "have", "using", "use",
    "for", "very", "really", "also", "but", "not", "no", "without",
}


def _boundary_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    escaped = escaped.replace(r"\-", r"[\s\-]+").replace(r"\ ", r"[\s\-]+")
    return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.IGNORECASE)


@dataclass
class ParsedQuery:
    original_query: str
    normalized_query: str
    category: str | None = None
    brand: str | None = None
    color: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    use_case: str | None = None
    keywords: list[str] = field(default_factory=list)
    price_expression: str | None = None
    matched_terms: list[str] = field(default_factory=list)

    @property
    def has_structured_filters(self) -> bool:
        return any(
            value is not None
            for value in (
                self.category,
                self.brand,
                self.color,
                self.min_price,
                self.max_price,
                self.use_case,
            )
        )

    @property
    def has_hard_filters(self) -> bool:
        """True when the query constrains a catalogue column directly.

        ``use_case`` is deliberately excluded: it is a soft ranking hint, so on
        its own it must not make an unrelated query count as in scope.
        """
        return any(
            value is not None
            for value in (
                self.category,
                self.brand,
                self.color,
                self.min_price,
                self.max_price,
            )
        )

    @property
    def is_semantic(self) -> bool:
        return bool(self.keywords) or not self.has_structured_filters

    def to_dict(self) -> dict:
        data = asdict(self)
        data["has_structured_filters"] = self.has_structured_filters
        return data


class Lexicon:
    """Brands, colours and use cases from the database with a static fallback."""

    def __init__(
        self,
        brands: Iterable[str] | None = None,
        colors: Iterable[str] | None = None,
        use_cases: Iterable[str] | None = None,
    ) -> None:
        self.brands = sorted(set(brands or STATIC_BRANDS), key=len, reverse=True)
        self.colors = sorted(set(colors or COLOR_ALIASES.values()), key=len, reverse=True)
        self.use_cases = sorted(set(use_cases or STATIC_USE_CASES), key=len, reverse=True)
        self._brand_patterns = [(b, _boundary_pattern(b)) for b in self.brands]
        self._use_case_patterns = [
            (u, _boundary_pattern(u)) for u in self.use_cases
        ]

    @classmethod
    def from_database(cls) -> "Lexicon":
        brands = [r["brand"] for r in db.fetch_all("SELECT DISTINCT brand FROM products")]
        colors = [r["color"] for r in db.fetch_all(
            "SELECT DISTINCT color FROM products WHERE color IS NOT NULL"
        )]
        use_cases = [r["use_case"] for r in db.fetch_all(
            "SELECT DISTINCT use_case FROM products WHERE use_case IS NOT NULL"
        )]
        return cls(brands, colors, use_cases)


_lexicon: Lexicon | None = None
_lexicon_lock = threading.Lock()


def get_lexicon() -> Lexicon:
    global _lexicon
    if _lexicon is None:
        with _lexicon_lock:
            if _lexicon is None:
                try:
                    _lexicon = Lexicon.from_database()
                except Exception:
                    _lexicon = Lexicon()
    return _lexicon


def reset_lexicon() -> None:
    global _lexicon
    _lexicon = None


_NUMBER = r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|lac|lacs)?"
_CURRENCY = r"(?:rs\.?|inr|₹)?\s*"


def _to_number(value: str, suffix: str | None) -> float | None:
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    suffix = (suffix or "").lower()
    if suffix == "k" or suffix == "thousand":
        number *= 1_000
    elif suffix in {"lakh", "lac", "lacs"}:
        number *= 100_000
    if number <= 0 or number > 10_000_000:
        return None
    return number


def _find_price(text: str) -> tuple[float | None, float | None, str | None, str | None]:
    """Return (min, max, matched expression, remaining text)."""
    patterns = [
        # between 20000 and 30000 / from 20000 to 30000
        (
            re.compile(
                rf"\b(?:between|from)\s+{_CURRENCY}{_NUMBER}\s+(?:and|to)\s+{_CURRENCY}{_NUMBER}\b",
                re.IGNORECASE,
            ),
            "between",
        ),
        # 20000 - 30000
        (
            re.compile(rf"\b{_CURRENCY}{_NUMBER}\s*(?:-|–|to)\s*{_CURRENCY}{_NUMBER}\b", re.IGNORECASE),
            "between_dash",
        ),
        # under / below / less than / up to / within / max
        (
            re.compile(
                rf"\b(?:under|below|less\s+than|less\s+then|upto|up\s+to|within|max(?:imum)?|budget\s+of)\s+{_CURRENCY}{_NUMBER}\b",
                re.IGNORECASE,
            ),
            "max",
        ),
        # above / over / more than / greater than / minimum / starting at
        (
            re.compile(
                rf"\b(?:above|over|more\s+than|greater\s+than|min(?:imum)?|starting\s+(?:at|from)|at\s+least)\s+{_CURRENCY}{_NUMBER}\b",
                re.IGNORECASE,
            ),
            "min",
        ),
    ]
    for pattern, kind in patterns:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        if kind in {"between", "between_dash"}:
            low = _to_number(groups[0], groups[1])
            high = _to_number(groups[2], groups[3])
            if low is None or high is None:
                continue
            if low > high:
                low, high = high, low
            remaining = text[: match.start()] + " " + text[match.end():]
            return low, high, match.group(0).strip(), remaining
        value = _to_number(groups[0], groups[1])
        if value is None:
            continue
        remaining = text[: match.start()] + " " + text[match.end():]
        if kind == "max":
            return None, value, match.group(0).strip(), remaining
        return value, None, match.group(0).strip(), remaining
    return None, None, None, text


def _remove_span(text: str, start: int, end: int) -> str:
    return text[:start] + " " + text[end:]


def parse_query(query: str, lexicon: Lexicon | None = None) -> ParsedQuery:
    if not isinstance(query, str):
        raise ValueError("Query must be a string")
    original = query.strip()
    normalized = re.sub(r"\s+", " ", original.lower()).strip()
    if not normalized:
        raise ValueError("Query must not be empty")
    if len(normalized) > 500:
        raise ValueError("Query must be at most 500 characters")

    lex = lexicon or get_lexicon()
    remaining = normalized
    matched: list[str] = []

    min_price, max_price, price_expr, remaining = _find_price(remaining)

    # Category: longest synonym first, so "gaming accessories" wins over "gaming".
    category = None
    for synonym in sorted(CATEGORY_SYNONYMS, key=len, reverse=True):
        pattern = _boundary_pattern(synonym)
        match = pattern.search(remaining)
        if match:
            category = CATEGORY_SYNONYMS[synonym]
            matched.append(match.group(0))
            remaining = _remove_span(remaining, match.start(), match.end())
            break

    # Brand: longest brand name first (e.g. Ultimate Ears before ...).
    brand = None
    for brand_name, pattern in lex._brand_patterns:
        # "noise cancelling" is a feature phrase, not the Noise brand.
        if brand_name.lower() == "noise" and re.search(
            r"noise\s+(?:cancell?ing|cancellation)", remaining
        ):
            continue
        match = pattern.search(remaining)
        if match:
            brand = brand_name
            matched.append(match.group(0))
            remaining = _remove_span(remaining, match.start(), match.end())
            break

    color = None
    for alias, canonical in sorted(COLOR_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = _boundary_pattern(alias)
        match = pattern.search(remaining)
        if match:
            color = canonical
            matched.append(match.group(0))
            remaining = _remove_span(remaining, match.start(), match.end())
            break

    use_case = None
    for use_case_name, pattern in lex._use_case_patterns:
        match = pattern.search(remaining)
        if match:
            use_case = use_case_name
            matched.append(match.group(0))
            remaining = _remove_span(remaining, match.start(), match.end())
            break

    # Keywords are the meaningful words left after structured terms are removed.
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+.\-]*", remaining)
    keywords: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        lower = token.lower().strip(".-")
        if len(lower) < 2 or lower in STOPWORDS:
            continue
        if re.fullmatch(r"\d+", lower):
            continue
        if lower not in seen:
            seen.add(lower)
            keywords.append(lower)
    keywords = keywords[:8]

    return ParsedQuery(
        original_query=original,
        normalized_query=normalized,
        category=category,
        brand=brand,
        color=color,
        min_price=min_price,
        max_price=max_price,
        use_case=use_case,
        keywords=keywords,
        price_expression=price_expr,
        matched_terms=matched,
    )


KEYWORD_SYNONYMS = {
    "wireless": ["bluetooth", "wi-fi", "wifi"],
    "lightweight": ["portable"],
    "noise": ["noise cancellation", "active noise"],
    "cancelling": ["noise cancellation", "active noise"],
    "canceling": ["noise cancellation", "active noise"],
    "battery": ["battery life"],
    "microphone": ["mic"],
    "waterproof": ["water resistant"],
    "4k": ["ultra hd", "uhd"],
    "fullhd": ["full hd"],
    "ssd": ["solid state"],
    "hdd": ["hard drive"],
}


def _keyword_variant_condition(keyword: str) -> tuple[str, list[str]]:
    """One keyword plus its practical synonyms, OR-ed across text columns."""
    variants = [keyword, *KEYWORD_SYNONYMS.get(keyword.lower(), [])]
    clauses = []
    params: list[str] = []
    for variant in variants:
        like = f"%{variant}%"
        clauses.append(
            "(name ILIKE %s OR description ILIKE %s OR tags ILIKE %s "
            "OR specifications ILIKE %s OR use_case ILIKE %s)"
        )
        params.extend([like] * 5)
    return "(" + " OR ".join(clauses) + ")", params


def keyword_condition(keywords: list[str]) -> tuple[str, list[str]]:
    """Build a parameterised AND-of-OR keyword predicate.

    Each keyword must appear (directly or through a practical synonym) in at
    least one searchable text field. The SQL fragment contains only fixed
    column names and %s placeholders.
    """
    if not keywords:
        return "TRUE", []
    clauses = []
    params: list[str] = []
    for keyword in keywords:
        clause, clause_params = _keyword_variant_condition(keyword)
        clauses.append(clause)
        params.extend(clause_params)
    return "(" + " AND ".join(clauses) + ")", params


def _keyword_boundary_condition(keyword: str) -> tuple[str, list[str]]:
    """Word-boundary variant of a keyword predicate for scope checks.

    A substring test is used as a cheap prefilter, then a word-boundary regex
    confirms the match. This avoids the false positive where ``pet`` matches
    ``competitive`` without paying the full regex cost on every row.
    Synonyms are still accepted.
    """
    variants = [keyword, *KEYWORD_SYNONYMS.get(keyword.lower(), [])]
    clauses = []
    params: list[str] = []
    for variant in variants:
        like = f"%{variant}%"
        pattern = r"\m" + re.escape(variant) + r"\M"
        clauses.append(
            "((name ILIKE %s OR description ILIKE %s OR tags ILIKE %s "
            "OR specifications ILIKE %s OR use_case ILIKE %s) AND "
            "(name ~* %s OR description ~* %s OR tags ~* %s "
            "OR specifications ~* %s OR use_case ~* %s))"
        )
        params.extend([like] * 5 + [pattern] * 5)
    return "(" + " OR ".join(clauses) + ")", params


_scope_cache: dict[tuple[str, ...], tuple[float, bool]] = {}
_scope_cache_lock = threading.Lock()
_SCOPE_CACHE_TTL_SECONDS = 300
_SCOPE_CACHE_MAX_ENTRIES = 512


def _scope_cache_get(key: tuple[str, ...]) -> bool | None:
    now = time.monotonic()
    with _scope_cache_lock:
        entry = _scope_cache.get(key)
        if entry is None:
            return None
        if now - entry[0] >= _SCOPE_CACHE_TTL_SECONDS:
            _scope_cache.pop(key, None)
            return None
        return entry[1]


def _scope_cache_set(key: tuple[str, ...], value: bool) -> None:
    with _scope_cache_lock:
        if len(_scope_cache) >= _SCOPE_CACHE_MAX_ENTRIES:
            _scope_cache.clear()
        _scope_cache[key] = (time.monotonic(), value)


def reset_scope_cache() -> None:
    with _scope_cache_lock:
        _scope_cache.clear()


def keywords_match_exists(keywords: list[str]) -> bool:
    """Return True when every keyword has a lexical catalogue match.

    This is the scope gate for queries that contain no category or brand.
    Matching is word-boundary based, so ``pet`` does not match ``competitive``.
    Requiring every keyword keeps vague or unrelated phrases out of the result
    set while still allowing practical synonyms such as lightweight/portable.
    Results are cached briefly because an out-of-scope check scans the table.
    """
    if not keywords:
        return False
    key = tuple(keyword.lower() for keyword in keywords)
    cached = _scope_cache_get(key)
    if cached is not None:
        return cached

    clauses = []
    params: list[str] = []
    for keyword in keywords:
        clause, clause_params = _keyword_boundary_condition(keyword)
        clauses.append(clause)
        params.extend(clause_params)
    where = "(" + " AND ".join(clauses) + ")"
    row = db.fetch_one(
        f"SELECT EXISTS (SELECT 1 FROM products WHERE {where}) AS found",
        params,
    )
    found = bool(row and row["found"])
    _scope_cache_set(key, found)
    return found
