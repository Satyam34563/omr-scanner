# Deploying the Question-Paper Generator to production (Ubuntu / DigitalOcean)

The feature has **two halves**:

1. **`sms` Laravel app** — the admin UI at `/paper` (controller, routes, views,
   `paper_presets` table). Deployed like any other `sms` change.
2. **The engine stack** — lives here in `omr_project`:
   - `paper_engine/` — Python selection engine (`engine/`, `cli/`). Stdlib only
     for selection/metadata; `cli/export.py` needs openpyxl + weasyprint.
   - `paper_docx/` — Node docx builder (`build_docx.js`, `mathToOmml.js`,
     `logo.png`, `school_config.json`). Needs `npm install`.
   - **`questions.db` + `images/`** — the question bank. NOT in any repo; copied
     to the server separately (see step 4).

The `sms` app calls the engine as local subprocesses (Symfony Process), so the
engine must be on the **same server** as `sms`, reachable at the paths you set in
`sms`'s `.env` (`PAPER_*`).

---

## One-time server setup

### 1. Pull the engine (this repo) on the server
```bash
cd /path/to/omr_project
git pull
```

### 2. Install engine dependencies
```bash
bash setup_paper.sh
```
This installs Node, weasyprint's system libs, Devanagari fonts, `npm install` in
`paper_docx/`, and the Python deps in the omr venv. Verify:
```bash
./venv/bin/python -c 'import openpyxl, weasyprint; print("py deps OK")'
```

### 3. Deploy the `sms` app
```bash
cd /path/to/sms
git pull                      # master now includes the /paper feature
composer install --no-dev -o
php artisan config:clear
php artisan tenants:artisan "migrate"   # creates paper_presets in every tenant DB
```

### 4. Copy the question bank to the server
`questions.db` + `images/` are not in a repo. From your Mac:
```bash
# adjust the server user/host/path
rsync -avz --progress \
  /Users/satyamsuman/Documents/QUESTION_BANK/questions.db \
  /Users/satyamsuman/Documents/QUESTION_BANK/images \
  user@server:/path/to/question_bank/
```
> `questions.db` is a **live, growing** DB on the Mac (the ingestion pipeline
> keeps adding questions). The server copy is a snapshot — re-run this rsync
> whenever you want prod to see newly added questions.

### 5. Set the `PAPER_*` env vars in `sms/.env` (server paths!)
The `config/services.php` defaults point at the Mac. Override every path:
```
PAPER_ENGINE_DIR=/path/to/omr_project/paper_engine
PAPER_BUILD_DOCX=/path/to/omr_project/paper_docx/build_docx.js
PAPER_SCHOOL_CONFIG=/path/to/omr_project/paper_docx/school_config.json
PAPER_QUESTIONS_DB=/path/to/question_bank/questions.db
PAPER_IMAGE_BASE=/path/to/question_bank
PAPER_PYTHON_BIN=python3
PAPER_NODE_BIN=/usr/bin/node
PAPER_EXPORT_PYTHON=/path/to/omr_project/venv/bin/python
PAPER_EXTRA_PATH=/usr/local/bin:/usr/bin
# optional scoring defaults
PAPER_ANSWER_MARKS=1.5
PAPER_ANSWER_NEGATIVE=0.25
```
Then `php artisan config:clear` (and reload php-fpm).

---

## Smoke test on the server
```bash
cd /path/to/omr_project/paper_engine
python3 -m cli.metadata --db /path/to/question_bank/questions.db --query languages
```
Then in the app: open **/paper**, pick a language + total, **Generate** — you
should get 5 downloads (question paper, 2 answer keys, OMR .xlsx, metadata .pdf).

## Notes / gotchas
- **PHP subprocess PATH**: php-fpm's PATH is minimal; `PAPER_NODE_BIN` must be an
  absolute path (that's why the default is not a bare `node`). `PaperEngine` also
  prepends `PAPER_EXTRA_PATH` to the subprocess PATH.
- **Permissions**: the php-fpm user must be able to read `questions.db`/`images/`
  and write `sms/storage/app/paper_jobs/` + the usage sidecar DB
  (`paper_engine/paper_usage.db` by default — or set `PAPER_USAGE_DB`).
- **Python version**: the engine is Python 3.9+ compatible; Ubuntu's `python3`
  is fine. Do NOT use `str | None`-style syntax if you edit the engine.
- **Tenants**: run the migration for every healthy tenant. A tenant whose DB is
  missing (e.g. `sha`) will error — fix or remove that tenant first.
