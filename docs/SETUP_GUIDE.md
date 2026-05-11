# 📋 SETUP GUIDE — How to Install & Run the System

**Tiempo estimado**: 15 minutos (primera vez)  
**Audiencia**: Developers, DevOps  
**Objetivo**: Get the system running locally or on HANA Cloud

---

## ✅ Prerequisites

Asegúrate de tener instalado:
- Python 3.11+ (`python --version`)
- pip (package manager)
- Git
- SAP HANA Cloud credentials (username, password, host) — opcional para dev

---

## 🚀 Quick Start (5 minutes)

### 1. Clone the repository

```bash
git clone https://github.com/Tony-bie/Perritos_club_SAP.git
cd Perritos_club_SAP
```

### 2. Create virtual environment

```bash
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

**For local development (SQLite)**:
```bash
pip install -r requirements.txt
```

**For HANA Cloud integration** (add later):
```bash
pip install -r requirements-hana.txt
```

### 4. Setup `.env` file

Copy the template:
```bash
cp .env.example .env
```

Edit `.env` with your settings:
```bash
# === LOCAL (SQLite) Setup ===
STORAGE_BACKEND=sqlite
SQLITE_PATH=./pipeline.db

# === OR HANA Cloud Setup ===
STORAGE_BACKEND=hana
HANA_HOST=your-hana-host.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=your-password
HANA_SCHEMA=SOC_PIPELINE
HANA_ENCRYPT=true

# === SAP SOC API ===
SAP_SOC_BASE_URL=http://localhost:8000
SAP_SOC_TOKEN=your-sap-token

# === API Admin ===
ADMIN_API_KEY=your-admin-key

# === Optional: Telegram Notifications ===
TOKEN_BOT_TELEGRAM=your-telegram-token
CHAT_IDS=123456789,987654321
```

**⚠️ IMPORTANT**: Never commit `.env` to git. It's in `.gitignore`.

### 5. Run the system

```bash
# Option A: Run backend API server
python -m backend.api.http.application

# Option B: Run ingestion cycle once
python main.py

# Option C: Run tests
python -m unittest discover -s tests -p "test_*.py"
```

---

## 🔧 Configuration Details

### Storage Backend Choice

| Setting | Value | When to use | Notes |
|---------|-------|-----------|-------|
| **Local (fast)** | `sqlite` | Development, testing | Data saved in `./pipeline.db` |
| **HANA Cloud (prod)** | `hana` | Production, multi-team | Persistent, scalable, BTP native |

**Switch between them**: Just change `STORAGE_BACKEND` in `.env` and restart.

---

### SAP SOC API Configuration

Required for ingestion:

```env
SAP_SOC_BASE_URL=http://localhost:8000    # Where SAP API is running
SAP_SOC_TOKEN=your-api-key                # Bearer token for auth
REQUEST_TIMEOUT_SECONDS=30                # Default timeout
MAX_RETRIES=3                             # Retry attempts
RETRY_BACKOFF_SECONDS=2                   # Wait between retries
```

**Test SAP connectivity**:
```bash
curl -H "Authorization: Bearer ${SAP_SOC_TOKEN}" \
  "${SAP_SOC_BASE_URL}/health"
```

---

### HANA Cloud Connection (Detailed)

#### Step 1: Get HANA credentials from SAP BTP

1. Go to: https://account.hanatrial.ondemand.com
2. Login
3. Click "Go To Your Trial Account" → "trial" (subaccount)
4. Left menu: **SAP HANA Cloud** → **SAP HANA Database Explorer**
5. Click **Add Database** → Select **SAP HANA Database**
6. Fill in your HANA instance details
7. You'll see:
   - **Host**: `xxxxx.hna1.prod-us10.hanacloud.ondemand.com`
   - **Port**: `443`
   - **User**: `DBADMIN` (or your DB user)
   - **Password**: (ask your team lead)

#### Step 2: Add to `.env`

```env
STORAGE_BACKEND=hana
HANA_HOST=xxxxx.hna1.prod-us10.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=your-password
HANA_SCHEMA=SOC_PIPELINE
HANA_ENCRYPT=true
HANA_VALIDATE_CERTIFICATE=true
```

#### Step 3: Run migrations

**First time only**: Creates schema + tables + views

```bash
python tools/run_hana_migrations.py
```

**Check success**:
```bash
python tools/check_hana_ingestion.py
```

---

### Optional: Telegram Notifications

Setup your bot to get alerts on Telegram:

#### Step 1: Create Telegram Bot

1. Open Telegram
2. Search for **@BotFather**
3. Send `/start` → `/newbot`
4. Follow prompts, get your **token**

#### Step 2: Add to `.env`

```env
TOKEN_BOT_TELEGRAM=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
CHAT_IDS=111222333,444555666
```

#### Step 3: Test

```bash
python -c "from backend.api.http.application import bot; print(bot)"
```

If no errors, Telegram is configured ✅

**Note**: If token is invalid, the system still works (just no Telegram alerts).

---

## 🧪 Running Tests

### Run all tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run specific test module

```bash
python -m unittest tests.test_config -v
python -m unittest tests.test_block_c_api -v
python -m unittest tests.test_block_c_hana_integration -v
```

### Expected output (all passing)

```
test_enable_worker_defaults_to_true ... ok
test_db_env_vars_override_hana_cloud_uaa_binding_for_sql_login ... ok
test_dashboard_summary_endpoint ... ok
test_recent_alerts_windows_and_runs_endpoints ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.065s
OK
```

---

## 🔄 Running the System

### Option 1: Manual Ingestion Cycle

Run once, then exit:

```bash
python main.py
```

**What it does**:
1. Connect to SAP SOC API
2. Fetch logs for current 30-min window
3. Normalize + extract features
4. Train/score ML model
5. Create alerts
6. Store in HANA/SQLite
7. Exit

**Output**:
```
INFO: Starting ingestion cycle...
INFO: Fetched 3912 logs from SAP SOC API
INFO: Extracted 95 window metrics
INFO: Anomalies detected: 6
INFO: Alerts created: 2
INFO: Cleanup skipped (ran at 2026-05-10 02:00:00)
INFO: Cycle complete. Stored in HANA.
```

### Option 2: API Server (with background worker)

Run server + background ingestion loop:

```bash
python -m uvicorn backend.api.http.application:app --host 0.0.0.0 --port 8000
```

**What it does**:
1. Start FastAPI server on http://localhost:8000
2. Background thread: ingestion cycle every 30 min (configurable)
3. 8 endpoints ready for requests

**Test endpoints**:

```bash
# Health check
curl http://localhost:8000/health

# SAP connection status
curl http://localhost:8000/health/sap

# Trigger manual ingestion
curl -X POST http://localhost:8000/run/ingestion \
  -H "Authorization: Bearer ${ADMIN_API_KEY}"

# Get recent alerts
curl "http://localhost:8000/alerts/recent?limit=5" \
  -H "Authorization: Bearer ${ADMIN_API_KEY}"

# Dashboard summary (24 hours)
curl "http://localhost:8000/dashboard/summary?time_window_hours=24" \
  -H "Authorization: Bearer ${ADMIN_API_KEY}"

# Admin cleanup (delete data older than 90 days)
curl -X POST http://localhost:8000/api/admin/cleanup \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"retention_days": 90}'
```

---

## 📊 Verify Everything Works

### Checklist

- [ ] `.env` file exists with correct values
- [ ] Virtual environment activated (`which python` shows `.venv`)
- [ ] Dependencies installed (`pip list | grep fastapi`)
- [ ] Tests passing (`python -m unittest discover -s tests` → OK)
- [ ] SAP API reachable (`curl ${SAP_SOC_BASE_URL}/health`)
- [ ] HANA connection works (if using HANA):
  ```bash
  python tools/check_hana_ingestion.py
  ```
- [ ] API server starts:
  ```bash
  python -m uvicorn backend.api.http.application:app --port 8000
  # Wait for: "Uvicorn running on http://0.0.0.0:8000"
  ```

---

## 🐛 Troubleshooting

### "ModuleNotFoundError: No module named 'backend'"

**Solution**: Activate venv + reinstall
```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

### "Connection refused to SAP SOC API"

**Solution**: Check SAP_SOC_BASE_URL in `.env`
```bash
# Test
curl -v ${SAP_SOC_BASE_URL}/health
```

---

### "HANA connection failed: invalid password"

**Solution**: Verify HANA credentials in `.env`
```bash
# Double-check:
echo $HANA_HOST
echo $HANA_USER
# Try manually in HANA Cockpit
```

---

### "Tests are being skipped"

**Expected behavior** if HANA_HOST not set:
```
tests.test_block_c_hana_integration ... skipped (HANA_HOST not configured)
```

This is OK. HANA tests skip gracefully in local dev.

---

### "Telegram bot not sending messages"

**Solution**: Check TOKEN_BOT_TELEGRAM
```bash
# If empty/invalid:
# - No error (system tolerates missing token)
# - Just no Telegram notifications
# - All other features work fine
```

---

## 📚 Next Steps

1. **Run a test ingestion cycle**:
   ```bash
   python main.py
   ```

2. **Start the API server**:
   ```bash
   python -m uvicorn backend.api.http.application:app --port 8000
   ```

3. **Query the dashboard**:
   ```bash
   curl "http://localhost:8000/dashboard/summary?time_window_hours=24"
   ```

4. **Read ARCHITECTURE.md** for deep dive into components

---

## 🎓 Quick Reference

### Key Files

| File | Purpose |
|------|---------|
| `.env` | Configuration (secrets, API keys) |
| `main.py` | Single ingestion cycle entry point |
| `backend/api/http/application.py` | API server + 8 endpoints |
| `backend/core/config.py` | Settings loader (37 config fields) |
| `backend/storage/backends/store.py` | Data persistence (HANA/SQLite) |
| `sql/migrations/` | Database schema (4 migration files) |
| `tests/` | Unit + integration tests |

### Common Commands

| Command | What it does |
|---------|--------------|
| `python main.py` | Run ingestion once |
| `python -m unittest discover -s tests` | Run all tests |
| `python tools/run_hana_migrations.py` | Initialize HANA schema |
| `python -m uvicorn backend.api.http.application:app --port 8000` | Start API server |

---

## ❓ Questions?

Check:
1. **ARCHITECTURE.md** — For "Why?" questions (design decisions)
2. **Code comments** — Most functions have docstrings
3. **Tests** — Living documentation (`tests/test_*.py`)
4. **Terminal output** — Logging is verbose by default

---

