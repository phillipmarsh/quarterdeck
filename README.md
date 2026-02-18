# Quarterdeck

Hallway dashboard showing weather, train departures, and calendar events.
Built as a PWA for an always-on iPad display.

## Setup

```bash
# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your RTT credentials, iCal URLs, location, etc.

# Run locally
uv run uvicorn quarterdeck.app:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in your browser.

## Configuration

All configuration is via environment variables (see `.env.example`):

- **RTT_USERNAME / RTT_PASSWORD** — Realtime Trains API credentials
- **TRAIN_STATION_CRS** — Your departure station CRS code
- **TRAIN_DESTINATIONS** — Comma-separated destination CRS codes
- **WEATHER_LATITUDE / WEATHER_LONGITUDE** — Location for weather
- **ICAL_FEED_URLS** — Comma-separated iCal feed URLs

## Development

```bash
# Run tests
uv run pytest -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run pyright src/ tests/
```

## iPad Setup

1. Open Safari on the iPad and navigate to your Quarterdeck URL
2. Share → "Add to Home Screen" (launches as full-screen PWA)
3. Settings → Display & Brightness → Auto-Lock → Never
4. Keep the iPad plugged in
