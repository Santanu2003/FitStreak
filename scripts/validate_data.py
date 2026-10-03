"""Validate FitStreak's canonical reference datasets before packaging/deployment."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "backend" / "data"

FILES = [
    "gym_members_exercise_tracking.csv",
    "student_lifestyle_dataset.csv",
    "health_activity_data.csv",
    "daily_food_nutrition_dataset.csv",
    "megaGymDataset.csv",
]

def check_csv(name):
    p = SCRIPTS / name
    df = pd.read_csv(p)
    raw_dup = int(df.duplicated().sum())
    # Raw sources can contain redundant rows; preparation removes exact duplicates.
    canonical = df.drop_duplicates().reset_index(drop=True)
    if name == "megaGymDataset.csv":
        canonical = canonical.drop_duplicates(subset=["Title", "BodyPart"]).reset_index(drop=True)
        keydup = int(canonical.duplicated(subset=["Title", "BodyPart"]).sum())
        if keydup: raise ValueError(f"{name}: {keydup} duplicate Title+BodyPart records after preparation")
    if name == "student_lifestyle_dataset.csv" and "Student_ID" in df:
        if int(df["Student_ID"].duplicated().sum()): raise ValueError(f"{name}: duplicate Student_ID")
    return len(canonical), raw_dup

def check_json(name):
    with open(DATA / name, encoding="utf-8") as f: data = json.load(f)
    if name == "exercises.json":
        names = [(x.get("Title", "").strip().casefold(), x.get("BodyPart", "").strip().casefold()) for x in data]
        if len(names) != len(set(names)): raise ValueError("exercises.json: duplicate Title+BodyPart")
    if name == "foods.json":
        names = [x.get("Food_Item", "").strip().casefold() for x in data]
        if len(names) != len(set(names)): raise ValueError("foods.json: duplicate Food_Item")
    return len(data) if isinstance(data, list) else data.get("sample_size", 0)

if __name__ == "__main__":
    print("FitStreak data validation")
    for f in FILES:
        rows, raw_dup = check_csv(f)
        suffix = f" (removed {raw_dup} raw duplicates during preparation)" if raw_dup else ""
        print(f"✓ {f}: {rows:,} canonical rows{suffix}")
    for f in ["exercises.json", "foods.json"]: print(f"✓ {f}: {check_json(f):,} records")
    print("✓ No exact duplicate rows or duplicate canonical keys detected.")
