"""Restaurants: find the best place for what you're craving, book a table, pre-order.

Real reservation APIs (OpenTable, TheFork, resOS, …) are mostly partner-gated and
thin in Nigeria, so Quik's path is direct restaurant partnerships: restaurants list
on Quik (menu, hours, tables) and get bookings + pre-orders in a simple partner view.
The sample venues below are invented for development.
"""
import hashlib
import random
import re
from datetime import date, datetime, timedelta
from typing import Protocol

from .. import airports
from ..schemas import MenuItem, Restaurant, RestaurantSearch

CITY_CENTRES = {"abuja": (9.0765, 7.3986), "lagos": (6.4550, 3.4246), "port harcourt": (4.8156, 7.0498)}

# Shared dish library: id -> (name, description, price, tags)
DISHES = {
    "jollof": ("Party jollof rice & chicken", "Smoky firewood jollof, grilled chicken, plantain", 9_500, ["jollof", "rice", "chicken", "nigerian", "spicy"]),
    "friedrice": ("Nigerian fried rice & turkey", "Fried rice with liver, prawns and peppered turkey", 10_500, ["rice", "turkey", "nigerian"]),
    "ofada": ("Ofada rice & ayamase", "Local rice with green pepper sauce and assorted meat", 9_000, ["rice", "ofada", "nigerian", "spicy", "local"]),
    "egusi": ("Pounded yam & egusi", "Egusi with stockfish and goat meat", 8_500, ["swallow", "pounded yam", "egusi", "soup", "nigerian", "local"]),
    "amala": ("Amala, ewedu & gbegiri", "With assorted beef", 7_500, ["swallow", "amala", "soup", "nigerian", "local"]),
    "afang": ("Afang soup & eba", "Calabar-style with periwinkle", 9_000, ["swallow", "eba", "soup", "nigerian", "local"]),
    "peppersoup": ("Catfish pepper soup", "Point-and-kill catfish, utazi", 11_000, ["pepper soup", "fish", "soup", "spicy", "nigerian"]),
    "goatpepper": ("Goat meat pepper soup", "Slow-cooked, with agidi", 7_000, ["pepper soup", "goat", "soup", "spicy", "nigerian"]),
    "suya": ("Suya platter", "Beef and chicken suya, yaji, onions", 8_000, ["suya", "grill", "beef", "spicy", "nigerian", "street food"]),
    "asun": ("Asun", "Peppered smoked goat", 6_500, ["asun", "goat", "spicy", "grill", "nigerian"]),
    "nkwobi": ("Nkwobi", "Cow foot in palm-oil sauce, utazi", 7_000, ["nkwobi", "nigerian", "local"]),
    "fish": ("Grilled croaker & chips", "Whole croaker, pepper sauce, yam or plantain chips", 22_000, ["fish", "seafood", "grill", "spicy"]),
    "shawarma": ("Chicken shawarma", "Double chicken, garlic sauce", 5_500, ["shawarma", "chicken", "wrap", "fast food"]),
    "burger": ("Smash burger & fries", "Double beef, cheddar, house sauce", 11_000, ["burger", "beef", "fast food"]),
    "pizza": ("Pepperoni pizza", "12-inch, wood-fired", 14_000, ["pizza", "italian"]),
    "pasta": ("Seafood linguine", "Prawns, calamari, chilli", 16_500, ["pasta", "seafood", "italian"]),
    "sushi": ("Sushi platter", "18 pieces, chef's selection", 28_000, ["sushi", "japanese", "fish", "seafood"]),
    "ramen": ("Chicken ramen", "Rich broth, soft egg", 13_000, ["ramen", "japanese", "noodles", "soup"]),
    "szechuan": ("Szechuan chicken", "With egg fried rice", 12_000, ["chinese", "chicken", "spicy", "rice"]),
    "dimsum": ("Dim sum basket", "Har gow, siu mai, bao", 10_000, ["chinese", "dim sum"]),
    "butter": ("Butter chicken & naan", "Creamy tomato curry", 13_500, ["indian", "curry", "chicken"]),
    "biryani": ("Lamb biryani", "Raita and salad", 15_000, ["indian", "rice", "lamb", "spicy"]),
    "mezze": ("Mezze platter", "Hummus, baba ghanoush, falafel, flatbread", 12_000, ["lebanese", "vegetarian", "vegan"]),
    "steak": ("Ribeye steak", "300g, peppercorn sauce, mash", 32_000, ["steak", "beef", "grill", "continental"]),
    "ribs": ("BBQ pork ribs", "Half rack, slaw", 18_000, ["ribs", "pork", "grill", "bbq"]),
    "bowl": ("Grain & veg bowl", "Quinoa, roasted veg, tahini", 8_500, ["vegan", "vegetarian", "healthy", "salad"]),
    "breakfast": ("Full English breakfast", "Eggs, sausage, beans, toast", 9_000, ["breakfast", "eggs", "continental"]),
    "pancakes": ("Pancake stack", "Berries, syrup", 7_500, ["breakfast", "pancakes", "dessert", "sweet"]),
    "akara": ("Akara & pap", "Bean fritters, custard", 3_500, ["breakfast", "akara", "nigerian", "local"]),
    "cake": ("Chocolate fudge cake", "Warm, with ice cream", 5_500, ["dessert", "cake", "sweet"]),
    "smoothie": ("Mango smoothie", "Fresh mango, yoghurt", 4_000, ["drink", "smoothie", "healthy"]),
    "chapman": ("Chapman", "Classic Nigerian mocktail", 3_000, ["drink", "mocktail", "nigerian"]),
}

# id, name, city, area, lat, lng, cuisines, price level, rating, opens, closes, deposit/guest, dish ids
VENUES = [
    ("abj-eko", "Eko Hearth", "Abuja", "Wuse II", 9.0790, 7.4700, ["Nigerian"], 2, 4.6, "08:00", "23:00", 3_000,
     ["jollof", "ofada", "egusi", "amala", "afang", "peppersoup", "goatpepper", "asun", "akara", "chapman"]),
    ("abj-yaji", "Yaji House", "Abuja", "Jabi", 9.0650, 7.4230, ["Nigerian", "Grills"], 1, 4.5, "12:00", "01:00", 0,
     ["suya", "asun", "nkwobi", "goatpepper", "fish", "chapman"]),
    ("abj-kintsugi", "Kintsugi", "Abuja", "Maitama", 9.0900, 7.4930, ["Japanese", "Asian"], 3, 4.7, "12:00", "23:00", 10_000,
     ["sushi", "ramen", "dimsum", "cake", "smoothie"]),
    ("abj-redlantern", "Red Lantern", "Abuja", "Garki II", 9.0300, 7.4870, ["Chinese"], 2, 4.3, "11:30", "22:30", 5_000,
     ["szechuan", "dimsum", "friedrice", "ramen"]),
    ("abj-saffron", "Saffron Road", "Abuja", "Asokoro", 9.0440, 7.5240, ["Indian"], 2, 4.4, "12:00", "22:30", 5_000,
     ["butter", "biryani", "mezze", "smoothie"]),
    ("abj-cedar", "Cedar & Salt", "Abuja", "Wuse II", 9.0810, 7.4650, ["Lebanese", "Grills"], 2, 4.2, "10:00", "00:00", 0,
     ["shawarma", "mezze", "fish", "smoothie", "cake"]),
    ("abj-ember", "Ember Steakhouse", "Abuja", "Maitama", 9.0950, 7.4880, ["Steakhouse", "Continental"], 3, 4.8, "17:00", "23:30", 15_000,
     ["steak", "ribs", "fish", "pasta", "cake"]),
    ("abj-crust", "Crust & Co", "Abuja", "Gwarinpa", 9.1100, 7.4050, ["Pizza", "Italian"], 2, 4.3, "11:00", "23:00", 0,
     ["pizza", "pasta", "burger", "cake"]),
    ("abj-sunday", "Sunday Table", "Abuja", "Jabi", 9.0700, 7.4280, ["Brunch", "Continental"], 2, 4.5, "07:30", "17:00", 3_000,
     ["breakfast", "pancakes", "akara", "bowl", "smoothie"]),
    ("abj-greenleaf", "Greenleaf", "Abuja", "Wuse II", 9.0770, 7.4720, ["Healthy", "Vegan"], 2, 4.4, "08:00", "21:00", 0,
     ["bowl", "mezze", "smoothie"]),
    ("los-lagoon", "Lagoon Kitchen", "Lagos", "Victoria Island", 6.4300, 3.4200, ["Nigerian", "Seafood"], 3, 4.7, "12:00", "23:30", 10_000,
     ["jollof", "fish", "peppersoup", "afang", "suya", "chapman"]),
    ("los-mama", "Mama Put Deluxe", "Lagos", "Ikeja GRA", 6.5800, 3.3500, ["Nigerian"], 1, 4.4, "08:00", "22:00", 0,
     ["amala", "egusi", "ofada", "jollof", "akara", "goatpepper"]),
    ("los-umami", "Umami Bay", "Lagos", "Ikoyi", 6.4530, 3.4350, ["Japanese"], 3, 4.6, "12:00", "23:00", 15_000,
     ["sushi", "ramen", "dimsum"]),
    ("los-fire", "Firepit", "Lagos", "Lekki Phase 1", 6.4470, 3.4730, ["Grills", "BBQ"], 2, 4.5, "13:00", "00:00", 5_000,
     ["ribs", "steak", "suya", "burger", "fish"]),
    ("phc-garden", "Garden City Grill", "Port Harcourt", "GRA Phase 2", 4.8250, 7.0100, ["Nigerian", "Grills"], 2, 4.4, "10:00", "23:00", 3_000,
     ["peppersoup", "fish", "afang", "suya", "jollof"]),
]

SYNONYMS = {
    "hungry": [], "food": [], "eat": [], "something": [],
    "local": ["nigerian", "local"], "naija": ["nigerian"], "swallow": ["swallow"], "soup": ["soup"],
    "seafood": ["seafood", "fish"], "fish": ["fish"], "meat": ["beef", "goat", "grill"],
    "veggie": ["vegetarian"], "vegetarian": ["vegetarian"], "vegan": ["vegan"], "healthy": ["healthy"],
    "sweet": ["dessert", "sweet"], "dessert": ["dessert"], "brunch": ["breakfast"], "noodles": ["noodles"],
    "curry": ["curry", "indian"], "chicken": ["chicken"], "rice": ["rice"], "spicy": ["spicy"], "bbq": ["bbq", "grill"],
}
STOP = {"i", "want", "a", "an", "some", "me", "for", "the", "to", "and", "with", "near", "in", "at", "am", "im", "i'm",
        "craving", "like", "would", "please", "book", "table", "get", "find", "good", "best", "place", "restaurant", "really"}


def _menu(ids: list[str], venue_id: str, price_level: int) -> list[MenuItem]:
    mult = {1: 0.8, 2: 1.0, 3: 1.35}[price_level]
    return [MenuItem(id=f"{venue_id}:{d}", name=DISHES[d][0], description=DISHES[d][1],
                     price=round(DISHES[d][2] * mult / 500) * 500, tags=DISHES[d][3]) for d in ids]


def _venue(v) -> Restaurant:
    vid, name, city, area, lat, lng, cuisines, pl, rating, opens, closes, dep, dishes = v
    return Restaurant(id=vid, name=name, city=city, area=area, lat=lat, lng=lng, cuisines=cuisines, price_level=pl,
                      rating=rating, opens=opens, closes=closes, deposit_per_guest=dep, menu=_menu(dishes, vid, pl))


def get(restaurant_id: str) -> Restaurant | None:
    v = next((v for v in VENUES if v[0] == restaurant_id), None)
    return _venue(v) if v else None


def _vocabulary() -> set[str]:
    words = set()
    for name, desc, _, tags in DISHES.values():
        words |= set(re.findall(r"[a-z]+", name.lower())) | set(tags) | {w for t in tags for w in t.split()}
    for v in VENUES:
        words |= {c.lower() for c in v[6]}
    return words - {"and", "with", "the", "of"}


VOCAB = _vocabulary()
PHRASES = sorted({t for *_, tags in DISHES.values() for t in tags if " " in t}, key=len, reverse=True)


def craving_terms(text: str | None) -> list[str]:
    """Food words from free text. Anything that isn't on a menu (places, times, filler) is ignored."""
    if not text:
        return []
    words = re.findall(r"[a-z']+", text.lower())
    terms: list[str] = []
    for w in words:
        if w in STOP:
            continue
        if w in SYNONYMS:
            terms += SYNONYMS[w]
        else:
            terms.append(w)
    # a multi-word dish ("pepper soup") wins over its parts ("pepper", "soup")
    low = text.lower()
    for phrase in PHRASES:
        if phrase in low:
            terms = [t for t in terms if t not in phrase.split()] + [phrase]
    terms = [t for t in terms if t in VOCAB or t.rstrip("s") in VOCAB]
    return list(dict.fromkeys(terms))


def match_items(r: Restaurant, terms: list[str]) -> list[str]:
    """Menu items whose tags or name words match a craving term (whole words, so 'pepper' ≠ 'pepperoni')."""
    if not terms:
        return []
    hits = []
    for it in r.menu:
        words = set(re.findall(r"[a-z]+", it.name.lower())) | set(it.tags)
        if any(t in words or t.rstrip("s") in words or (" " in t and t in it.name.lower()) for t in terms):
            hits.append(it.id)
    if not hits and any(t in [c.lower() for c in r.cuisines] for t in terms):
        hits = [it.id for it in r.menu[:3]]
    return hits


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def slots(r: Restaurant, d: date, around: str, party: int) -> list[str]:
    """Free half-hour slots within ±2h of the requested time."""
    o, c = _mins(r.opens), _mins(r.closes)
    if c <= o:
        c += 24 * 60
    want = _mins(around)
    out = []
    for t in range(o, c - 60 + 1, 30):
        if abs(t - want) > 120 and abs(t - (want + 1440)) > 120:
            continue
        busy = 0.35 + (0.3 if 19 * 60 <= t % 1440 <= 21 * 60 else 0) + (0.1 if party > 4 else 0)
        # each slot's availability depends only on venue, day, party size and time
        roll = random.Random(int(hashlib.md5(f"{r.id}{d}{party}{t}".encode()).hexdigest(), 16)).random()
        if roll > busy:
            out.append(f"{(t // 60) % 24:02d}:{t % 60:02d}")
    if d == datetime.now().date():
        now = datetime.now().hour * 60 + datetime.now().minute + 30
        out = [s for s in out if _mins(s) >= now]
    return out


class RestaurantProvider(Protocol):
    name: str

    def search(self, s: RestaurantSearch) -> list[Restaurant]: ...


class MockRestaurantProvider:
    name = "mock"

    def search(self, s: RestaurantSearch) -> list[Restaurant]:
        lat, lng = s.lat, s.lng
        if lat is None and s.city:
            lat, lng = CITY_CENTRES.get(s.city.lower(), (None, None))
        venues = [_venue(v) for v in VENUES]
        if s.city:
            venues = [v for v in venues if v.city.lower() == s.city.lower()] or venues
        elif lat is not None:
            venues = [v for v in venues if airports.haversine_km(lat, lng, v.lat, v.lng) < 60]
        terms = craving_terms(s.craving)
        out = []
        for v in venues:
            v.matches = match_items(v, terms)
            if terms and not v.matches:
                continue
            v.slots = slots(v, s.date, s.time, s.party_size)
            if lat is not None:
                v.distance_km = round(airports.haversine_km(lat, lng, v.lat, v.lng) * 1.3, 1)
            out.append(v)
        return out


def get_restaurant_provider() -> RestaurantProvider:
    return MockRestaurantProvider()


def default_date() -> date:
    return (datetime.now() + timedelta(hours=1)).date()
