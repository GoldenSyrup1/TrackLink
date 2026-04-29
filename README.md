# TrackLink

Trajectory intelligence platform â€” people scoring and startup landscape mapping.

## Setup
```bash
cp .env.example .env
# fill in .env values
pip install -r requirements.txt
playwright install chromium
alembic upgrade head
uvicorn api.main:app --reload
```
