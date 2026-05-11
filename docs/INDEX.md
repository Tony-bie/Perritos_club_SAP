# 📚 Documentation Index

Choose the right doc for your question:

---

## 🎯 "I want to understand what this system does"

→ **[ARCHITECTURE.md](ARCHITECTURE.md)**

**Contains**:
- What problem we're solving
- How the pipeline works (end-to-end)
- Component descriptions
- Design decisions (why HANA, why ML, hyperparameters)
- Performance metrics

**For**: Everyone (technical + non-technical)  
**Read time**: 10-15 min  
**Format**: Long-form narrative with diagrams

---

## 🚀 "I want to install and run this locally"

→ **[SETUP_GUIDE.md](SETUP_GUIDE.md)**

**Contains**:
- Prerequisites (Python, Git, etc.)
- Virtual environment setup
- Dependency installation
- Configuration (`.env` file)
- Running options (API server, single cycle, tests)
- Troubleshooting

**For**: Developers, DevOps  
**Read time**: 5-10 min (to install) + 5 min (to run)  
**Format**: Step-by-step instructions with examples

---

## 🎬 "I want to see the system working RIGHT NOW"

→ **Run this command**:

```bash
python tools/walkthrough_demo.py
```

**What it shows**:
- Configuration loading
- Data ingestion simulation
- ML anomaly detection
- Alert creation
- API queries
- Cleanup logic
- Performance metrics

**For**: Everyone (no setup required)  
**Time**: ~2 minutes  
**Format**: Interactive walkthrough (stdout)

---

## 🏗️ "I want to understand the code structure"

→ **Check the code comments**:

```
backend/
├── api/http/application.py       ← 8 REST endpoints
├── core/config.py                ← Settings + validation
├── services/
│   ├── ingestion/                ← Normalization, features
│   ├── detection/                ← ML model, alert logic
│   └── clients/sap_soc.py        ← SAP API client
└── storage/backends/store.py     ← DB drivers
```

**For**: Developers  
**Read time**: Depends on depth  
**Format**: Python docstrings + inline comments

---

## 🧪 "I want to check if everything works"

→ **Run the tests**:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

**What it validates**:
- Configuration loading
- API endpoints
- HANA integration (if configured)

**For**: QA, CI/CD  
**Time**: <1 second  
**Format**: Unit + integration tests

---

## 🔧 "I want to deploy to HANA Cloud"

→ **[SETUP_GUIDE.md](SETUP_GUIDE.md#hana-cloud-connection-detailed)**

**Steps**:
1. Get HANA credentials from SAP BTP
2. Add to `.env`
3. Run migrations: `python tools/run_hana_migrations.py`
4. Validate: `python tools/check_hana_ingestion.py`

**For**: DevOps, Platform Engineers  
**Time**: 10-15 min  
**Format**: Point-by-point instructions

---

## 🐛 "Something is broken"

→ Check these in order:

1. **Troubleshooting in [SETUP_GUIDE.md](SETUP_GUIDE.md#troubleshooting)**
   - Common errors + solutions
   
2. **Test output**:
   ```bash
   python -m unittest discover -s tests -p "test_*.py" -v
   ```

3. **Terminal logs**:
   ```bash
   python main.py
   # Watch the output for ERROR lines
   ```

4. **[ARCHITECTURE.md](ARCHITECTURE.md#faq)** — FAQ section

---

## 📋 Quick Reference

| Question | Document | Time |
|----------|----------|------|
| What does this do? | ARCHITECTURE.md | 10 min |
| How do I install? | SETUP_GUIDE.md | 10 min |
| Show me working! | `walkthrough_demo.py` | 2 min |
| How do I code it? | Code comments | varies |
| Is it working? | Run tests | <1 sec |
| How do I deploy? | SETUP_GUIDE.md | 15 min |
| Help, it's broken! | SETUP_GUIDE.md → FAQ | 10 min |

---

## 📚 Document Relationships

```
README.md (overview, links here)
    │
    ├─→ ARCHITECTURE.md (deep dive)
    │   └─→ Design decisions, metrics, FAQs
    │
    ├─→ SETUP_GUIDE.md (how-to)
    │   └─→ Installation, config, troubleshooting
    │
    └─→ tools/walkthrough_demo.py (see it working)
        └─→ 9-step demo, no setup needed
```

---

## ✨ Tips

- **First time?** → Start with walkthrough demo
- **Need details?** → Read ARCHITECTURE.md
- **Ready to code?** → Follow SETUP_GUIDE.md
- **Lost?** → Check FAQ in ARCHITECTURE.md or Troubleshooting in SETUP_GUIDE.md

---