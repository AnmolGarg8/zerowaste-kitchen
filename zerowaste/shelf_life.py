"""Approximate, conservative fridge/pantry shelf-life defaults (days).

These are rule-of-thumb values so the voice flow never has to ask
"when does this expire?". Callers can always override with an explicit
`days_until_expiry`. For production, replace this table with a vetted source
such as the USDA FoodKeeper dataset.
"""
from __future__ import annotations

SHELF_LIFE_DAYS: dict[str, int] = {
    # dairy
    "milk": 7, "yogurt": 14, "curd": 7, "cheese": 21, "paneer": 5, "butter": 30,
    "cream": 7, "egg": 28,
    # meat & fish
    "chicken": 2, "fish": 2, "shrimp": 2, "beef": 3, "mutton": 3, "pork": 3,
    "ground beef": 2, "sausage": 5,
    # vegetables
    "spinach": 5, "lettuce": 5, "tomato": 6, "onion": 30, "potato": 30,
    "carrot": 21, "broccoli": 5, "cauliflower": 6, "cucumber": 6,
    "bell pepper": 7, "capsicum": 7, "coriander": 5, "mint": 5, "cabbage": 14,
    "mushroom": 5, "garlic": 60, "ginger": 21, "okra": 4, "pea": 5,
    # fruit
    "banana": 5, "apple": 21, "orange": 14, "grape": 7, "berry": 4,
    "strawberry": 4, "mango": 5, "lemon": 21, "avocado": 4, "papaya": 4,
    # bakery & cooked
    "bread": 5, "tortilla": 14, "roti": 2, "cooked rice": 2, "leftover": 3,
    "dal": 3, "soup": 3, "hummus": 7, "tofu": 5,
}
DEFAULT_DAYS = 7


def normalize(name: str) -> str:
    """Lowercase, trim, and singularize simply ('Tomatoes' -> 'tomato')."""
    n = " ".join(name.lower().strip().split())
    if n.endswith("ies") and len(n) > 4:
        return n[:-3] + "y"
    if n.endswith("oes") and len(n) > 4:
        return n[:-2]
    if n.endswith("s") and not n.endswith(("ss", "us")) and len(n) > 3:
        return n[:-1]
    return n


def lookup(name: str) -> tuple[int, bool]:
    """Return (days, is_estimate). `is_estimate` is True when we fell back to the default."""
    n = normalize(name)
    if n in SHELF_LIFE_DAYS:
        return SHELF_LIFE_DAYS[n], False
    words = set(n.split())
    best: str | None = None
    for key in SHELF_LIFE_DAYS:
        key_words = key.split()
        if all(w in words for w in key_words) and (best is None or len(key) > len(best)):
            best = key
    if best:
        return SHELF_LIFE_DAYS[best], False
    return DEFAULT_DAYS, True
