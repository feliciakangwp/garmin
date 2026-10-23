# Garmin training dashboard

Read-only dashboard built from the Garmin Personal API, using only Python's standard library.

- `./refresh.sh` (Mac/Linux) or `refresh.bat` (Windows): pulls new data and rebuilds `dashboard.html`
- `python3 pull.py --full` pulls your full history; after that, re-runs only fetch what is new
- Race dates and the goal are at the top of `build.py`

The API key comes from `.env.local` (`GARMIN_PERSONAL_API_KEY=`) or, in a Claude cloud session,
from the environment's network secret. `.env.local`, `data/` and `dashboard.html` hold your key or
your data and are git-ignored.
