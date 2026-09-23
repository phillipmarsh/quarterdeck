# Quarterdeck

Hallway dashboard showing weather, train departures, and calendar events.
Built as a PWA for an always-on iPad display.

## Local preview

```bash
cd quarterdeck

# Install dependencies
uv sync

# Create and configure environment variables
cp .env.example .env
```

Edit `.env` with your real values — at minimum:

- **RTT_API_TOKEN** — sign in at [api-portal.rtt.io](https://api-portal.rtt.io) with an
  RTT unified login (accounts.realtimetrains.com) and copy the token shown
  (free for personal, non-commercial use). Both token kinds work: a refresh
  token is exchanged automatically for short-life access tokens.
- **ICAL_FEED_URLS** — grab from Google Calendar Settings → "Secret address in iCal format"
  and/or iCloud Calendar sharing
- The weather/train station defaults (Forest Hill → London Bridge / Highbury & Islington)
  are already set

Then run:

```bash
uv run uvicorn quarterdeck.app:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in your browser.
It works even with missing credentials — panels show "unavailable" gracefully.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `RTT_API_TOKEN` | Realtime Trains API access token | |
| `TRAIN_STATION_CRS` | Departure station CRS code | `FOH` |
| `TRAIN_DESTINATIONS` | Comma-separated destination CRS codes | `LBG,HHY` |
| `WEATHER_LATITUDE` | Weather location latitude | `51.4525` |
| `WEATHER_LONGITUDE` | Weather location longitude | `-0.0492` |
| `ICAL_FEED_URLS` | Comma-separated iCal feed URLs | |

Note: `webcal://` iCal URLs (as produced by Apple's share sheet) are
accepted and normalised to `https://` automatically.

## Data refresh

Data is fetched by background loops, not per request: weather every
30 minutes, trains every 30 seconds, calendar every 5 minutes. If a
refresh fails, panels keep showing the last good data with an
"As of HH:MM" marker, and the source retries on a shorter interval
until it recovers. A panel only shows an error when a source has
never succeeded — including a "check RTT API token" hint when the
trains API rejects the configured token.

## Deploy to Raspberry Pi

### 1. Get the code onto the Pi

Clone from GitHub:

```bash
# On the Pi
git clone https://github.com/phillipmarsh/quarterdeck.git ~/quarterdeck
```

Or rsync directly:

```bash
rsync -avz --exclude .venv quarterdeck/ pi@raspberrypi.local:~/quarterdeck/
```

### 2. Install uv and dependencies

```bash
ssh pi@raspberrypi.local

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
cd ~/quarterdeck
uv sync --no-dev
```

### 3. Configure environment

```bash
cp .env.example .env
nano .env  # fill in your real values
```

### 4. Test it works

```bash
uv run uvicorn quarterdeck.app:app --host 0.0.0.0 --port 8000
```

Check from your Mac: `http://raspberrypi.local:8000`

### 5. Create a systemd service

```bash
sudo nano /etc/systemd/system/quarterdeck.service
```

Paste:

```ini
[Unit]
Description=Quarterdeck Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/quarterdeck
ExecStart=/home/pi/.local/bin/uv run uvicorn quarterdeck.app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PATH=/home/pi/.local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable quarterdeck
sudo systemctl start quarterdeck
sudo systemctl status quarterdeck  # check it's running
```

### 6. Set up mDNS (optional — nicer URL)

```bash
sudo apt install avahi-daemon
sudo hostnamectl set-hostname quarterdeck
# Reboot — then accessible at http://quarterdeck.local:8000
```

### 7. Nginx reverse proxy (optional — port 80)

```bash
sudo apt install nginx
sudo nano /etc/nginx/sites-available/quarterdeck
```

Paste:

```nginx
server {
    listen 80;
    server_name quarterdeck.local;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

Enable and restart:

```bash
sudo ln -s /etc/nginx/sites-available/quarterdeck /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo systemctl restart nginx
```

Now accessible at `http://quarterdeck.local`.

## iPad setup

1. Open **Safari** → `http://quarterdeck.local` (or `:8000` without nginx)
2. Tap **Share** → **Add to Home Screen** → **Add**
3. Open the new icon — it launches full-screen, no browser chrome
4. **Settings → Display & Brightness → Auto-Lock → Never**
5. Keep the iPad plugged in
6. Optional: **Settings → Accessibility → Guided Access** → enable,
   then triple-click the home button in the app to lock to Quarterdeck

## Development

```bash
# Run tests
uv run pytest -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run pyright src/ tests/
```

## Data sources

- Weather by [Open-Meteo](https://open-meteo.com/) (CC BY 4.0)
- Train data by [Realtime Trains](https://www.realtimetrains.co.uk/)
- Calendar events from your own iCal feeds (Google Calendar, iCloud)

## Licence

[Apache 2.0](LICENSE)
