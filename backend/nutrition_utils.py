"""Loads the food databases and powers the Nutrition page's food autocomplete.

Two built-in sources are merged at start-up:
  * data/foods.json        — the general food dataset (built by scripts/prepare_data.py)
  * data/indian_foods.csv  — Indian foods (breads, dal, curries, South Indian, snacks, sweets…).
    Kept as a separate, hand-editable file so re-running prepare_data.py never wipes it.
    Values are approximate home-style estimates per the serving written in the name.

On top of those, each user can save their own "custom foods" (see models.py); those are
passed into search_foods() by the API layer and always rank first for that user.
"""
import csv
import json
import os
import re
from config import MEAL_TYPES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


# Sanity limits for a single logged entry (after multiplying by servings).
INDIAN_ID_START = 10001   # ids of foods loaded from indian_foods.csv start here

MAX_SERVINGS = 20
MAX_CALORIES = 5000
MAX_MACRO_G = 1000


def _load_foods():
    with open(os.path.join(DATA_DIR, "foods.json"), encoding="utf-8") as f:
        foods = json.load(f)
    path = os.path.join(DATA_DIR, "indian_foods.csv")
    if os.path.exists(path):
        next_id = INDIAN_ID_START
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                foods.append({
                    "id": next_id,
                    "Food_Item": row["Food_Item"].strip(),
                    "Category": row["Category"].strip(),
                    "Meal_Type": row["Meal_Type"].strip(),
                    "Region": row.get("Region", "").strip(),
                    "Calories": float(row["Calories"]),
                    "Protein_g": float(row["Protein_g"]),
                    "Carbs_g": float(row["Carbs_g"]),
                    "Fat_g": float(row["Fat_g"]),
                })
                next_id += 1
    return foods


_foods = _load_foods()
FOOD_CATEGORIES = sorted({f["Category"] for f in _foods})

# Words people use interchangeably. Searching for any one finds foods named with the others.
_SYNONYM_GROUPS = [
    {"roti", "chapati", "chapatti", "phulka", "fulka", "rotli"},
    {"paratha", "parantha", "parotta", "porotta"},
    {"curd", "dahi", "yogurt", "yoghurt", "thayir", "doi"},
    {"mutton", "goat", "lamb", "mangsho", "gosht"},
    {"dal", "daal", "dhal", "lentil", "lentils"},
    {"dosa", "dosai", "dosha"},
    {"idli", "idly"},
    {"biryani", "biriyani", "briyani"},
    {"chai", "tea"},
    {"sabzi", "sabji", "subzi", "sabji"},
    {"paneer", "cottage"},
    {"kheer", "payasam", "payasa", "payesh", "phirni"},
    {"ladoo", "laddu", "laddoo"},
    {"gulab", "gulaab"},
    {"halwa", "halva", "sheera"},
    {"lassi", "buttermilk", "chaas", "chaach", "mattha"},
    {"poha", "pohe", "aval"},
    {"sweet", "mithai", "dessert", "mishti", "meetha"},
    {"kebab", "kabab", "kebap", "tikka"},
    {"egg", "anda"},
    {"chana", "chole", "chickpea", "chickpeas"},
    {"rajma", "kidney"},
    {"aloo", "alu", "aloor", "potato", "batata"},
    {"gobi", "cauliflower", "phool"},
    {"palak", "spinach"},
    {"bhindi", "okra"},
    {"baingan", "begun", "brinjal", "eggplant"},
    {"chawal", "rice"},
    {"ghee", "clarified"},
    {"kachori", "kachuri", "kochuri", "kachauri", "kachodi"},
    {"rasgulla", "rosogolla", "roshogolla", "rasogolla", "rossogolla"},
    {"fish", "maach", "machh", "mach", "macher", "machher", "maachh"},
    {"chicken", "murgi", "murgir", "murgh", "murg"},
    {"prawn", "shrimp", "chingri", "jhinga"},
    {"ilish", "hilsa", "hilsha", "elish", "ilisha"},
    {"pithe", "pitha", "pithey", "puli"},
    {"luchi", "loochi"},
    {"puri", "poori"},
    {"papdi", "papri"},
    {"khichdi", "khichuri", "khichri", "khichadi", "kichadi"},
    {"pani", "phuchka", "puchka", "golgappa", "gupchup", "panipuri"},
    {"vada", "vadai", "wada", "bada"},
    {"chaat", "chat"},
    {"cutlet", "chop"},
    {"sooji", "suji", "rava", "semolina"},
    {"kesari", "kesar"},
    {"ladoo", "laddu", "laddoo", "naru"},
    {"pomfret", "paplet", "pamplet", "paplate"},
    {"bhetki", "bekti", "barramundi"},
    {"crab", "kekda", "kankda"},
    {"mackerel", "bangda", "ayala", "bangdo"},
    {"sardine", "mathi", "chala", "tarli"},
    {"kingfish", "surmai", "seer", "neymeen"},
    {"rohu", "rui", "rohita", "rahu"},
    {"katla", "catla", "bhakur"},
    {"pabda", "pabdah"},
    {"bombil", "bombay"},
    {"squid", "calamari"},
    {"karimeen", "pearlspot"},
]
_SYNONYMS = {}
for _group in _SYNONYM_GROUPS:
    for _w in _group:
        _SYNONYMS.setdefault(_w, set()).update(_group)


def _stem(token):
    """Very light plural handling: 'sweets' -> 'sweet', 'rotis' -> 'roti'."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _variants(token):
    stem = _stem(token)
    out = {token, stem}
    for t in (token, stem):
        out |= _SYNONYMS.get(t, set())
    return out


def _word_starts(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _match_score(food, tokens):
    """Return None if the food doesn't match every search word, else a sort key
    (lower = better). A search word matches when it (or a synonym) is the start of a
    word in the food's name/category/region — so 'egg' finds 'Scrambled Eggs' but no
    longer 'Veggie Burger'."""
    name = food["Food_Item"].lower()
    words = _word_starts(f"{food['Food_Item']} {food.get('Category', '')} {food.get('Region', '')}")
    name_words = _word_starts(food["Food_Item"])
    cat_words = _word_starts(food.get("Category", ""))
    pos_total = 0
    category_hit = 1
    for tok in tokens:
        variants = _variants(tok)
        if not any(w.startswith(v) for w in words for v in variants):
            return None
        # A word matching the food's category ("sweets" -> Indian Sweet) ranks a food
        # above name-only matches; otherwise prefer matches earlier in the name.
        if any(w.startswith(v) for w in cat_words for v in variants):
            category_hit = 0
        pos_total += min((i for i, w in enumerate(name_words) if any(w.startswith(v) for v in variants)),
                         default=len(name_words) + 5)
    phrase = " ".join(_stem(t) for t in tokens)
    return (category_hit, 0 if name.startswith(phrase) else 1, pos_total, len(name))


def search_foods(search="", limit=12, extra_foods=None):
    """Search built-in foods plus `extra_foods` (a user's saved custom foods, which are
    listed first). An empty search returns the first `limit` foods."""
    limit = max(1, min(int(limit or 12), 50))
    pool = list(extra_foods or []) + _foods
    tokens = _word_starts(search or "")
    if not tokens:
        return pool[:limit]
    scored = []
    for order, food in enumerate(pool):
        key = _match_score(food, tokens)
        if key is not None:
            custom_first = 0 if food.get("Custom") else 1
            # Indian foods (ids 10001+) win ties over the general dataset: this app is
            # built for Indian users, so "sweets" should show gulab jamun before sweet tea.
            fid = food.get("id")
            indian_first = 0 if isinstance(fid, int) and fid >= INDIAN_ID_START else 1
            scored.append(((custom_first, indian_first) + key + (order,), food))
    scored.sort(key=lambda pair: pair[0])
    return [food for _, food in scored[:limit]]


def get_food_by_name(name):
    name = (name or "").strip().lower()
    for f in _foods:
        if f["Food_Item"].lower() == name:
            return f
    return None


def check_entry_numbers(servings, calories, protein_g, carbs_g, fat_g):
    """Validate a logged food entry (typed by hand or auto-filled). Returns a list of
    error strings — empty if fine. Catches typos without being strict about real foods
    whose calories don't equal 4/4/9 exactly (alcohol, fibre, sugar alcohols)."""
    errors = []
    if servings is not None and not (0 < servings <= MAX_SERVINGS):
        errors.append(f"servings must be more than 0 and at most {MAX_SERVINGS}.")
    if calories is not None and not (0 <= calories <= MAX_CALORIES):
        errors.append(f"calories must be between 0 and {MAX_CALORIES}.")
    for label, value in (("protein_g", protein_g), ("carbs_g", carbs_g), ("fat_g", fat_g)):
        if value is not None and not (0 <= value <= MAX_MACRO_G):
            errors.append(f"{label} must be between 0 and {MAX_MACRO_G}.")
    if errors or None in (calories, protein_g, carbs_g, fat_g):
        return errors
    implied = 4 * protein_g + 4 * carbs_g + 9 * fat_g
    # Macros can never *explain* fewer calories than they contain, so a low total is almost
    # certainly a typo. A higher total is allowed a wide margin (alcohol is ~7 kcal/g and
    # isn't a macro column, e.g. cocktails), but not a 10x slip like 4500 for 450.
    if implied - calories > 100 and implied - calories > 0.4 * implied:
        errors.append(
            f"Calories ({calories:g}) are lower than the protein/carbs/fat you entered "
            f"(they add up to about {implied:.0f} kcal). Please double-check the numbers."
        )
    elif calories - implied > 400 and calories > 3 * implied:
        errors.append(
            f"Calories ({calories:g}) are far higher than the protein/carbs/fat you entered "
            f"(they add up to about {implied:.0f} kcal). Please double-check the numbers."
        )
    return errors
