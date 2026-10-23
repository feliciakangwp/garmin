"""Check the key works and show the 5 latest activities."""
from garmin_api import get, read_key

print("API key:", "set" if read_key() else "NOT set")
acts = get("/activitylist-service/activities/search/activities?start=0&limit=5") or []
print(f"Connected. Your {len(acts)} latest activities:")
for a in acts:
    km = (a.get("distance") or 0) / 1000
    print(f"  {a.get('startTimeLocal', '')[:10]}  {a.get('activityType', {}).get('typeKey', '?'):<22} {km:6.2f} km")
