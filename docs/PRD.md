# Quarterdeck — Hallway Dashboard

## Context

Repurpose an old iPad as an always-on hallway dashboard showing weather, train departures, and calendar events. Built as a **web app** (not native iOS) to avoid Apple Developer account signing hassles. The iPad runs Safari in full-screen PWA mode — visually identical to a native app.

## Architecture

```
[iPad Safari PWA] <--- HTTP ---> [FastAPI on Raspberry Pi]
                                        |
                                  ┌─────┼──────┐
                             Open-Meteo  RTT   iCal feeds
                             (weather)  (trains) (calendars)
```

- **Backend**: Python + FastAPI on Raspberry Pi (local network)
- **Frontend**: Server-rendered HTML (Jinja2) + HTMX for auto-refresh
- **No JS framework** — HTMX (~14KB) handles all dynamic updates

## Data Sources

| Source | API | Auth | Cache TTL |
|--------|-----|------|-----------|
| Weather | Open-Meteo (`api.open-meteo.com/v1/forecast`) | None | 30 min |
| Trains | Realtime Trains (`api.rtt.io/api/v1`) | Basic auth (free registration) | 30 sec |
| Google Calendar | iCal "Secret address" URL from Google Calendar settings | None (URL is secret) | 5 min |
| Apple Calendar | iCal subscription URL from iCloud | None (URL is secret) | 5 min |

## Layout (landscape iPad)

```
┌──────────────────────────────────────────────────────┐
│  Tue 17 Feb              14°C Partly Cloudy      9:42 │
├───────────────────────┬──────────────────────────────┤
│  TRAINS               │  TODAY                       │
│                       │                              │
│  → London Bridge      │  09:00  Team standup         │
│    09:48  (6 min)     │  11:30  Dentist              │
│    09:54  (12 min)    │  14:00  1:1 with Sarah       │
│    10:01  (19 min)    │  17:30  Gym class            │
│                       │                              │
│  → Highbury & Isl.    │                              │
│    09:52  (10 min)    │                              │
│    10:07  (25 min)    │                              │
├───────────────────────┴──────────────────────────────┤
│  10° ☁  11° ☁  12° 🌧  13° 🌧  14° ⛅  15° ☀       │
└──────────────────────────────────────────────────────┘
```

Dark nautical theme: navy background (#0a1628), amber accents (#ffb347), monospace clock. Readable from 2+ metres.

## Key Design Decisions

1. **HTMX over JS framework**: Each section polls independently at different intervals. No build step, no JS state management. ~14KB total.
2. **Server-rendered partials**: Backend renders HTML fragments with Jinja2. No JSON API needed for the frontend — simpler debugging, works without JS.
3. **iCal for both calendars**: Both Google and Apple calendars accessed via iCal URLs. Same parsing code, no OAuth, no API keys. User grabs URLs from calendar settings once.
4. **Graceful degradation**: Each panel renders independently. If trains API is down, weather and calendar still work. Stale cached data shown with timestamp.
5. **TTL caching**: Simple in-memory cache (cachetools). No Redis, no database. Appropriate for a single-user dashboard.

## Error Handling

- Each service call is wrapped in try/except at the route level (not within services)
- Failed service → error string stored in DashboardData → template shows "X data unavailable"
- Other panels unaffected
- Stale cache continues serving while API recovers
- Clock always works (client-side JS)

## Deployment

- systemd service on Raspberry Pi for auto-start
- Avahi/mDNS for `http://quarterdeck.local`
- iPad Safari → "Add to Home Screen" for full-screen PWA mode
