import json
from pathlib import Path
from algorithm import data_loader as dl

OUT = Path("D:/信息可视化/metro_coupling/data/algorithm/output/frontend_data")

# Load summaries to build timeline
summaries = {}
for f in OUT.glob("summary_*.json"):
    parts = f.stem.replace("summary_", "").split("_")
    if len(parts) != 2:
        continue
    code, yr = parts[0], int(parts[1])
    with open(f, encoding="utf-8") as fp:
        summaries[(code, yr)] = json.load(fp)

# Group by city
timeline = {}
for (code, yr), s in summaries.items():
    city_name = dl.CODE_TO_CITY_NAME.get(code, code)
    if code not in timeline:
        timeline[code] = {"cityCode": code, "cityName": city_name, "timeline": []}
    timeline[code]["timeline"].append({
        "year": yr,
        "U1": s.get("average_U1"),
        "U2": s.get("average_U2"),
        "D": s.get("average_D"),
        "C": s.get("average_C"),
        "stationCount": s.get("station_count"),
        "levelCounts": s.get("level_counts", {}),
    })

# Sort each city's timeline by year
for code in timeline:
    timeline[code]["timeline"].sort(key=lambda x: x["year"])

with open(OUT / "city_timeline.json", "w", encoding="utf-8") as f:
    json.dump(timeline, f, ensure_ascii=False, indent=2)

print(f"Generated city_timeline.json for {len(timeline)} cities")
for code, data in timeline.items():
    years = [t["year"] for t in data["timeline"]]
    print(f"  {code}: {min(years)}-{max(years)} ({len(years)} years)")