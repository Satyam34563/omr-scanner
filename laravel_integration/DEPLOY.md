# Deploying the OMR Checker API on your VPS

This runs the OMR Checker as a background service (`api.py`) on
`127.0.0.1:8001`, reachable only from other processes on the same
server - your Laravel app calls it over localhost HTTP, nothing on
the public internet can reach it directly.

## 1. Get the project onto the server

Copy the whole `omr_project/` folder to the server, e.g.
`/opt/omr_project`. Keep `config.json`, `layout.json`, and
`students.xlsx`/whatever your student-lookup source is configured to
use in place - the API reads them at startup.

## 2. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
    poppler-utils \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0 \
    libglib2.0-0 libgl1
```

- `poppler-utils` - rasterizes the scans PDF (`pdftoppm`).
- `libpango`/`libcairo`/`libgdk-pixbuf` - required by `weasyprint`,
  which renders the result PDFs.
- `libgl1`/`libglib2.0-0` - required by `opencv-python` on a headless
  server (no display).

## 3. Python environment

```bash
cd /opt/omr_project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # now includes fastapi/uvicorn/python-multipart
```

## 4. Smoke-test it manually first

```bash
source venv/bin/activate
uvicorn api:app --host 127.0.0.1 --port 8001
```

In another terminal on the same server:

```bash
curl http://127.0.0.1:8001/health
# {"status":"ok"}
```

Ctrl-C to stop once that works.

## 5. Run it persistently with systemd

Create `/etc/systemd/system/omr-checker.service`:

```ini
[Unit]
Description=OMR Checker API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/omr_project
ExecStart=/opt/omr_project/venv/bin/uvicorn api:app --host 127.0.0.1 --port 8001
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Adjust `User=` to whichever account should own the process - `www-data`
is convenient since it'll match the ownership Laravel/php-fpm uses,
but any unprivileged user works as long as it can read
`omr_project/` and write to `output/`.

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now omr-checker
sudo systemctl status omr-checker
curl http://127.0.0.1:8001/health
```

View logs any time with:

```bash
sudo journalctl -u omr-checker -f
```

## 6. Wire up Laravel

See `routes_snippet.php`, `OmrController.php`, `upload.blade.php`,
`results.blade.php`, and `config_and_env_snippet.txt` in this same
folder - copy each into your existing Laravel app at the paths noted
in their header comments, then:

```bash
php artisan config:clear   # picks up the new OMR_API_URL from .env
```

Visit `/omr` (or whatever URL prefix you used in the route group) while
logged in, upload a scans PDF + answer key, and confirm you get a
results page with download links.

## 7. After a deploy/update

Any time you change files under `omr_project/` (new config, code
fixes, etc.):

```bash
sudo systemctl restart omr-checker
```

## Security checklist

- [ ] `--host 127.0.0.1` in both the manual test and the systemd unit
      - never `0.0.0.0`. Confirm with `ss -tlnp | grep 8001` and make
      sure it shows `127.0.0.1:8001`, not `0.0.0.0:8001`.
- [ ] No firewall rule/reverse-proxy exposes port 8001 externally.
- [ ] The `/omr` routes in Laravel sit behind your existing `auth`
      middleware (already the case in `routes_snippet.php`).
- [ ] `storage/app/private/omr_jobs/` (created automatically per job)
      holds student names/roll numbers/photos - it inherits Laravel's
      normal storage permissions, so nothing web-servable directly
      exposes it. Consider a periodic cleanup job (e.g. a scheduled
      `find storage/app/private/omr_jobs -mtime +30 -delete`) if you
      don't want old batches kept indefinitely.
