# MediVisit AI/ML Services — Aspiring Architects Challenge

> **Repo scope**: This repository holds the backend architecture + working proof-of-concept code produced for the Signify Health *Aspiring Architects* practical challenge. It is **not** the Patient Portal UI — it is the backend domain services and AI/ML pipelines that the portal (and the clinician iPad app) consume.

---

## 1. Project Summary

### 1.1 The business problem
MediVisit is a healthcare logistics company that sends clinicians to patients' homes to perform Medicare preventative-care tests (spirometry, diabetic eye exams, urine analysis, cognitive screening, FOBT, UACR, HbA1c, etc.). Raw test data is captured on a clinician iPad and shipped to **third‑party specialist vendor labs** for clinical interpretation. MediVisit is paid **per valid test** by insurance companies, so turning vendor data into clean, trustworthy, structured results — quickly — is a direct revenue concern, not just a nice-to-have.

The catch: every vendor delivers its results differently, and MediVisit doesn't control the format:

| Delivery mechanism | Format | Needs AI? |
|---|---|---|
| REST webhook | Already structured JSON | No |
| SFTP file drop | CSV/XML with inconsistent, vendor-specific columns | No (deterministic mapping) |
| Email | Free-text body + PDF attachment | **Yes** — unstructured, must be read like a human would |

New vendors are onboarded regularly, so hard-coding per-vendor parsing logic doesn't scale. The architecture needs to treat "how a vendor delivers data" as a pluggable, config-driven concern, and normalize every vendor's output into one canonical, validated schema before it reaches the rest of the system (billing, patient portal, notifications).

### 1.2 What this repo builds (PoC 1 of planned AI/ML services)
`ai_services/01_intelligent_extraction` is the proof-of-concept backend for the **Vendor Integration Domain**'s AI extraction capability. It demonstrates a production-shaped (not toy) pipeline:

1. **Layer 1 — Deterministic readers**: pull raw text out of `.eml` emails, PDF attachments, and CSV files. No interpretation happens here.
2. **Layer 2 — Extraction**: for email/PDF vendors, an LLM (Claude, via a company SSO gateway) reads the raw text and returns candidate structured fields using a vendor-specific prompt template. For CSV/SFTP vendors, extraction is **fully deterministic** (column mapping) — no LLM needed, because the data is already semi-structured and column names are known per vendor config.
3. **Layer 3 — Trust layer**: every LLM-extracted value is checked against the original source text (catches hallucinations), and the final record is validated through strict Pydantic schemas (type + clinical range checks) before it's considered "VERIFIED."

The result is a canonical `ExtractedTestResult` object — identical in shape regardless of whether the vendor sent an email, a CSV, or (in production) a REST payload. This is the same contract the rest of the system (Test Result Domain, Reporting & Billing, Patient Portal) will eventually consume.

Supporting infrastructure (all run locally via Docker, mirroring how it would work in the cloud):
- **MongoDB** — vendor configuration documents (adapter type, prompt template, schema) and an `extraction_logs` audit collection. Config loading falls back to local JSON files if Mongo is unavailable, so the pipeline also works with zero Docker running.
- **Redis** — idempotency/dedup cache so the same vendor report is never re-extracted (and never re-billed for re-processing) twice, plus general LLM result caching (24h TTL).
- **Kafka (KRaft mode, no Zookeeper)** — the event backbone. A producer simulates a vendor webhook/SFTP notification (`vendor.raw_payload_received`); a consumer runs the full extraction pipeline and publishes the normalized result (`vendor.result.extracted`) for downstream domains.
- **FastAPI** — the REST surface: webhook ingestion endpoints, vendor registry, extraction status/stats lookups, health check.

### 1.3 Reliability & data-quality patterns demonstrated
- **Source verification** — numeric/text values extracted by the LLM must actually appear in the original vendor text (fuzzy-matches formats like `0.73` vs `73%`), or the record is `FLAGGED` for human review instead of silently trusted.
- **Pydantic schema validation** — per-test-type models (`SpirometryResult`, `FOBTResult`, `HBA1CResult`, `UACRResult`, `COGResult`, `CECGResult`) enforce clinically valid ranges and reject unknown fields (`extra="forbid"`).
- **Retry + circuit breaker** — LLM calls retry with exponential backoff (2s/4s/8s); after 5 consecutive failures, a circuit breaker opens for 60s so a broken LLM gateway doesn't get hammered, while CSV-only vendors keep flowing.
- **Dead-letter logging** — extraction failures that exhaust retries are logged to MongoDB (`status: DEAD_LETTER`) flagged for human review, instead of being silently dropped.
- **Idempotency** — content-hash based Redis cache means a duplicate vendor delivery (common with email/SFTP redelivery) is a cache hit, not a repeated LLM call or duplicate downstream event.
- **Config-driven vendor onboarding** — adding a new email/SFTP vendor is a new JSON/Mongo document + prompt template file, not a code change.

### 1.4 Validation against real data
Ground truth is pulled from Snowflake (`MARTS_PREVIOUS.DPS.FACTANCILLARY*`, see [ground_truth_query.sql](/Users/njindal/Desktop/Study/PhD/aa_challenge/ai_services/01_intelligent_extraction/data/ground_truth/ground_truth_query.sql)) for 1,000 real member evaluations across 2026 Q1. Before anything is committed to git, [deidentify_ground_truth.py](/Users/njindal/Desktop/Study/PhD/aa_challenge/ai_services/01_intelligent_extraction/src/deidentify_ground_truth.py) replaces every `MEMBERPLANID` and `EVALUATIONID` with a sequential synthetic token (clinical values, dates, and product codes are untouched — they carry the test signal and aren't identifying on their own). A mock-vendor generator then re-renders those same (now-tokenized) evaluations as realistic vendor emails/PDFs/CSVs with varied phrasing and formats, so the pipeline's output can be diffed field-by-field against the known-correct — but de-identified — values. Current results (see [tests/test_results/](/Users/njindal/Desktop/Study/PhD/aa_challenge/ai_services/01_intelligent_extraction/tests/test_results)):

| Test | Scope | Result |
|---|---|---|
| `test_01` | 1 spirometry email+PDF | PASS — exact match |
| `test_02` | All 142 spirometry emails (LLM) | **100%** verified, ~2.1s avg latency/extraction |
| `test_03` | All 142 spirometry PDFs (LLM) | **100%** verified |
| `test_04` | Spirometry CSV batch (deterministic) | **100%** (7/7) |
| `test_05` | FOBT CSV batch, 3 vendor formats (deterministic) | **100%** (444/444) |
| `test_06` | 24 adversarial edge cases (garbled text, empty files, out-of-range values, bad CSV columns, etc.) | 20/24 behaved as expected — the 4 gaps are tracked, not hidden, and are good discussion material for the architecture review |

### 1.5 What's intentionally out of scope / not yet built
- `ai_services/02_data_quality_validation` through `06_predictive_scheduling` are **placeholder directories** for the other planned AI/ML PoCs (Test Result validation, automated triage, patient engagement, natural-language search, predictive scheduling). They are currently empty — reserved so the team's final architecture can reference a consistent numbering scheme.
- A production MinIO/S3/Azure Blob object store was intentionally skipped for the PoC (local filesystem stands in for it); it remains part of the target system design.
- The Patient Portal frontend and the Insurance & Billing system are explicitly out of scope — this repo only defines the contracts other teams would integrate against.

### 1.6 Design & architecture diagram
Full system design diagram (domains, data flow, vendor adapters, event topics): [MediVisit architecture diagram](https://drive.google.com/file/d/1BYaZvcL7jDyLdA3iGMbzj1ed0nnva_yy/view?usp=drive_link)

---

## 2. Project Directory Structure

```
aa_challenge/
├── README.md                          # this file
├── pyproject.toml                     # single Python project — deps for all ai_services/ PoCs
├── setup.sh                           # one-shot local environment bootstrap script
├── docker-compose.yml                 # MongoDB + Redis + Kafka (KRaft mode), local dev only
├── .env.example                       # LLM_MODEL env var template (copy to .env)
├── .python-version                    # pyenv pin → 3.11.8
│
├── docs/                              # ⚠️ git-ignored — proprietary design notes, challenge
│                                      #   brief PDFs, architecture diagrams (incl. the
│                                      #   draw.io export design_2110_1725). Kept locally only;
│                                      #   not distributed via git. See §5 if you need these.
│
└── ai_services/                       # all AI/ML backend PoCs live under one Python package
    ├── __init__.py
    │
    ├── common/                        # shared across every PoC — the shared contract layer
    │   ├── schemas.py                 #   canonical Pydantic models (ExtractedTestResult +
    │   │                              #   6 per-test-type result schemas: Spirometry, CECG,
    │   │                              #   FOBT, HbA1c, UACR, Cognitive)
    │   ├── config.py                  #   vendor config loader (MongoDB → JSON file fallback)
    │   ├── llm_config.py              #   Claude LLM client via Signify's SSO/Okta gateway
    │   ├── redis_client.py            #   idempotency + LLM result caching helpers
    │   └── retry.py                   #   exponential backoff, circuit breaker, dead-letter log
    │
    ├── 01_intelligent_extraction/     # ✅ implemented — AI-powered vendor result extraction
    │   ├── config/                    #   per-vendor JSON configs (adapter type, prompt file…)
    │   │   ├── spirohealth_labs.json  #     email+PDF vendor → SPIROMETRY (needs LLM)
    │   │   └── quickscreen_labs.json  #     SFTP/CSV vendor → FOBT (deterministic, no LLM)
    │   ├── prompts/                   #   LLM prompt templates, one per test type
    │   │   ├── spirometry_extraction.txt
    │   │   └── fobt_extraction.txt
    │   ├── src/
    │   │   ├── readers.py             #   Layer 1 — read .eml / .pdf / .csv → raw text/rows
    │   │   ├── llm_extractor.py       #   Layer 2 — LLM call (email/PDF) + deterministic CSV
    │   │   │                         #     column mapping (SFTP)
    │   │   ├── verifier.py            #   Layer 3 — source-text verification + Pydantic build
    │   │   ├── extraction_pipeline.py #   orchestrates Layers 1→2→3, batch runner, CLI entry
    │   │   ├── kafka_producer.py      #   simulates vendor webhook/SFTP arrival → Kafka
    │   │   ├── kafka_consumer.py      #   long-running worker: Kafka → pipeline → Mongo/Redis
    │   │   ├── api.py                 #   FastAPI service (webhooks, vendor registry, stats)
    │   │   ├── seed_mongodb.py        #   loads config/*.json vendor configs into MongoDB
    │   │   ├── deidentify_ground_truth.py    # real Snowflake export → synthetic-token CSV
    │   │   │                         #   (swaps MEMBERPLANID/EVALUATIONID, nothing else)
    │   │   └── generate_mock_vendor_data.py  # de-identified ground truth → realistic mock
    │   │                             #   vendor emails/PDFs/CSVs for testing
    │   ├── data/
    │   │   ├── ground_truth/
    │   │   │   ├── ground_truth_query.sql                   # the Snowflake query (committed)
    │   │   │   ├── ancillary_results_1000.csv                # ⚠️ git-ignored — raw real export
    │   │   │   │                                             #   (only needed if refreshing)
    │   │   │   └── ancillary_results_1000_deidentified.csv  # ✅ committed — synthetic tokens,
    │   │   │                                                 #   this is what tests run against
    │   │   └── mock_vendors/          #   ✅ committed — generated from the de-identified CSV
    │   │       ├── email/             #     142 realistic spirometry vendor emails (.eml)
    │   │       ├── pdf/                #     142 matching PDF report attachments
    │   │       ├── sftp_csv/          #     FOBT (3 formats) + spirometry CSV batches
    │   │       └── edge_cases/        #     hand-crafted adversarial email/pdf/csv inputs
    │   └── tests/
    │       ├── test_01_single_spiro_email.py   # 1 email+PDF vs ground truth
    │       ├── test_02_all_spiro_emails.py     # all 142 emails vs ground truth
    │       ├── test_03_all_spiro_pdfs.py       # all 142 PDFs vs ground truth
    │       ├── test_04_spiro_csv.py            # spirometry CSV batch vs ground truth
    │       ├── test_05_fobt_csv.py             # FOBT CSV batches (3 formats) vs ground truth
    │       ├── test_06_edge_cases.py           # 24 adversarial/malformed inputs
    │       └── test_results/          #   ⚠️ git-ignored — timestamped run output logs
    │
    ├── 02_data_quality_validation/    # 🔲 placeholder — not yet implemented
    ├── 03_automated_triage/           # 🔲 placeholder — not yet implemented
    ├── 04_patient_engagement/         # 🔲 placeholder — not yet implemented
    ├── 05_nl_search/                  # 🔲 placeholder — not yet implemented
    └── 06_predictive_scheduling/      # 🔲 placeholder — not yet implemented
```

> **Why `01_intelligent_extraction` instead of a normal Python package name?** Folder names starting with a digit aren't valid Python *identifiers*, so you can't `import ai_services.01_intelligent_extraction...` directly in code. Every script in this repo instead uses `importlib.import_module("ai_services.01_intelligent_extraction.src.xxx")` (string-based import) or invokes the module via `python -m ai_services.01_intelligent_extraction.src.xxx` on the command line — both work fine because the restriction only applies to literal dotted syntax, not to string module paths. You'll see this pattern throughout `api.py`, `kafka_consumer.py`, and every test file.

---

## 3. Step-by-Step: Environment Setup, Running & Testing

All commands below assume you start at the repo root:
```bash
cd /path/to/aa_challenge
```

### 3.0 Prerequisites
- macOS with Docker Desktop installed and **running**
- `pyenv` installed (for the pinned Python 3.11.8)
- Access to the Signify Okta SSO gateway CLI, `ai-gateway-login` (installed via Self Service / Workspace One) — **only required if you want to run the LLM-powered email/PDF extraction.** CSV/deterministic extraction and all infra steps work without it.

### 3.1 Python environment
```bash
# Pin + install Python 3.11.8 (reads .python-version) and create a venv
pyenv local 3.11.8
python3 -m venv .venv
source .venv/bin/activate

python --version          # should print Python 3.11.8

# Install the project (core deps + dev tools: pytest, ruff, black)
pip install -e ".[dev]"
```
> Everything after this point assumes `source .venv/bin/activate` has been run in your current shell. Each new terminal session needs to re-activate it.

### 3.2 Environment variables
```bash
cp .env.example .env
```
`.env` only needs one variable — the LLM model name (auth is handled transparently by the Okta gateway, no API key is stored in this repo):
```
LLM_MODEL=claude-sonnet-4-5
```

### 3.3 Docker infrastructure (MongoDB, Redis, Kafka)
```bash
# Pull images once
docker pull mongo:7.0
docker pull redis:7.2-alpine
docker pull confluentinc/cp-kafka:7.6.0

# Start all services in the background
docker compose up -d

# Confirm they're healthy
docker compose ps
docker ps --filter name=medivisit --format "{{.Names}}: {{.Status}}"
```
You should see three running containers: `medivisit_mongodb` (27017), `medivisit_redis` (6379), `medivisit_kafka` (9092).

Quick connectivity checks:
```bash
docker exec medivisit_mongodb mongosh -u admin -p localdev --eval "db.runCommand({ping:1})"
docker exec medivisit_redis redis-cli -a localdev ping
docker exec medivisit_kafka kafka-topics --bootstrap-server localhost:9092 --list
```

To stop everything later: `docker compose down` (keeps data) or `docker compose down -v` (wipes volumes too).

> **Note:** The extraction pipeline's config loader (`ai_services/common/config.py`) tries MongoDB first and **automatically falls back to the local JSON files** in `ai_services/01_intelligent_extraction/config/` if Mongo isn't reachable. So you can run the core extraction/tests (§3.6) even before Docker is up — Docker is required for the Kafka/API/Mongo-audit-log flows in §3.7–3.9.

### 3.4 Ground truth data — already provided, no Snowflake needed
The de-identified ground truth fixture (`data/ground_truth/ancillary_results_1000_deidentified.csv`) and the already-generated mock vendor files (`data/mock_vendors/`) are **committed to this repo**, so you can skip straight to §3.6/§3.10 and run the full test suite right after cloning — nothing to download, nothing to pull from Snowflake.

`MEMBERPLANID` and `EVALUATIONID` in that fixture are synthetic sequential tokens (`900xxx` / `800xxx`), not real member identifiers — see [deidentify_ground_truth.py](/Users/njindal/Desktop/Study/PhD/aa_challenge/ai_services/01_intelligent_extraction/src/deidentify_ground_truth.py). The clinical values (FEV1/FVC ratios, grades, FOBT results, dates) are the real values from the Snowflake pull — only the two ID columns were swapped — so accuracy results are still meaningful.

**Only if you need to refresh the fixture** with a brand-new Snowflake pull (e.g. a larger sample, a different date range):
1. Run the query in [ground_truth_query.sql](/Users/njindal/Desktop/Study/PhD/aa_challenge/ai_services/01_intelligent_extraction/data/ground_truth/ground_truth_query.sql) against Snowflake (`MARTS_PREVIOUS.DPS`).
2. Save the output as `ai_services/01_intelligent_extraction/data/ground_truth/ancillary_results_1000.csv` (this exact filename is **git-ignored** — it's the one place real member data is allowed to live locally, and it must never be committed).
3. Re-run the de-identification step:
   ```bash
   python ai_services/01_intelligent_extraction/src/deidentify_ground_truth.py
   ```
   This overwrites `ancillary_results_1000_deidentified.csv` with freshly tokenized data. Review the diff, then commit it along with regenerated mock vendor data (§3.5) if you want to share the refresh with the team.

### 3.5 (Re)generate mock vendor data — only needed after refreshing ground truth
The committed `data/mock_vendors/` files were generated from the de-identified CSV above and are ready to use as-is. Only run this if you changed `ancillary_results_1000_deidentified.csv` (§3.4) and need to regenerate matching vendor emails/PDFs/CSVs:
```bash
python -m ai_services.01_intelligent_extraction.src.generate_mock_vendor_data
```
Expect ~142 spirometry `.eml` files, ~142 matching PDFs, and FOBT/spirometry CSV batches under `ai_services/01_intelligent_extraction/data/mock_vendors/`.

### 3.6 Run the extraction pipeline directly (no Docker required)
Runs a representative batch across both vendors (FOBT CSV, spirometry CSV, and a sample of 5 spirometry emails) and prints a summary:
```bash
python -m ai_services.01_intelligent_extraction.src.extraction_pipeline
```

You can also call the pipeline for one specific file, e.g. to test a single vendor email + its PDF attachment from a Python shell:
```bash
python - <<'EOF'
import importlib
pipeline = importlib.import_module("ai_services.01_intelligent_extraction.src.extraction_pipeline")

outcome = pipeline.extract_from_email(
    "ai_services/01_intelligent_extraction/data/mock_vendors/email/spiro_eval_19294621.eml",
    "spirohealth_labs",
    "ai_services/01_intelligent_extraction/data/mock_vendors/pdf/spiro_eval_19294621.pdf",
)
print(outcome.status)
print(outcome.result.model_dump(mode="json") if outcome.result else outcome.error)
EOF
```
Or extract an entire CSV batch (no LLM, deterministic):
```bash
python - <<'EOF'
import importlib
pipeline = importlib.import_module("ai_services.01_intelligent_extraction.src.extraction_pipeline")

outcomes = pipeline.extract_from_csv(
    "ai_services/01_intelligent_extraction/data/mock_vendors/sftp_csv/quickscreen_labs_fobt_batch_001.csv",
    "quickscreen_labs",
)
verified = sum(1 for o in outcomes if o.status == "VERIFIED")
print(f"{verified}/{len(outcomes)} verified")
EOF
```

### 3.7 Seed MongoDB with vendor configs (optional, enables Mongo-backed config + audit log)
```bash
python ai_services/01_intelligent_extraction/src/seed_mongodb.py
```
This loads `config/spirohealth_labs.json` and `config/quickscreen_labs.json` into the `medivisit.vendors` collection, and creates the (initially empty) `medivisit.extraction_logs` collection used for the audit trail.

### 3.8 End-to-end Kafka flow (requires Docker services up)
Run these in **two separate terminals** (both with `.venv` activated):

**Terminal A — start the consumer/worker** (keeps running, processes messages as they arrive, exits after 10 consecutive empty polls in this PoC):
```bash
python ai_services/01_intelligent_extraction/src/kafka_consumer.py
```

**Terminal B — publish vendor file events** (simulates vendor webhook/SFTP arrival):
```bash
python ai_services/01_intelligent_extraction/src/kafka_producer.py
```
Watch Terminal A log each file being read → extracted → verified, then check MongoDB:
```bash
docker exec -it medivisit_mongodb mongosh -u admin -p localdev \
  --eval 'db.getSiblingDB("medivisit").extraction_logs.countDocuments({status:"VERIFIED"})'
```

### 3.9 Run the FastAPI service
```bash
uvicorn ai_services.01_intelligent_extraction.src.api:app --reload --port 8000
```
Open **http://localhost:8000/docs** for interactive Swagger UI, or try it from the CLI:
```bash
# List registered vendors (Mongo, falls back to JSON files)
curl http://localhost:8000/vendors

# Simulate an inbound vendor email webhook (publishes to Kafka — run kafka_consumer.py to process it)
curl -X POST http://localhost:8000/webhooks/vendor-email \
  -H "Content-Type: application/json" \
  -d '{
        "vendor_id": "spirohealth_labs",
        "file_path": "ai_services/01_intelligent_extraction/data/mock_vendors/email/spiro_eval_19294621.eml",
        "pdf_path": "ai_services/01_intelligent_extraction/data/mock_vendors/pdf/spiro_eval_19294621.pdf"
      }'

# Simulate an inbound SFTP CSV drop notification
curl -X POST http://localhost:8000/webhooks/vendor-sftp \
  -H "Content-Type: application/json" \
  -d '{
        "vendor_id": "quickscreen_labs",
        "file_path": "ai_services/01_intelligent_extraction/data/mock_vendors/sftp_csv/quickscreen_labs_fobt_batch_001.csv"
      }'

# Check extraction stats / a specific evaluation (requires MongoDB + at least one run of kafka_consumer.py)
curl http://localhost:8000/extractions/stats
curl http://localhost:8000/extractions/19294621
```

### 3.10 Running the test suite
Each test script in `ai_services/01_intelligent_extraction/tests/` is self-contained — it runs the real extraction pipeline against mock vendor files and diffs the output against ground truth, then writes a timestamped report to `tests/test_results/`. Run them individually:

```bash
# Fast sanity check — 1 email+PDF, 1 LLM call, compares all 6 fields to Snowflake ground truth
python ai_services/01_intelligent_extraction/tests/test_01_single_spiro_email.py

# Full LLM accuracy run — all 142 spirometry emails (~142 LLM calls, ~5 min)
python ai_services/01_intelligent_extraction/tests/test_02_all_spiro_emails.py

# Same, but reading the PDF attachment instead of the email body
python ai_services/01_intelligent_extraction/tests/test_03_all_spiro_pdfs.py

# Deterministic CSV path — spirometry batch, 0 LLM calls, should be instant
python ai_services/01_intelligent_extraction/tests/test_04_spiro_csv.py

# Deterministic CSV path — FOBT batches across 3 differing vendor column formats
python ai_services/01_intelligent_extraction/tests/test_05_fobt_csv.py

# Adversarial / malformed-input handling (garbled text, empty files, out-of-range values…)
python ai_services/01_intelligent_extraction/tests/test_06_edge_cases.py
```
Each script exits `0` on full pass and non-zero if anything failed, so they're CI-friendly (`echo $?` after running, or chain with `&&`). Expected results — see §1.4 above; `test_06` is expected to surface a few known gaps (it's designed to find edge cases, not just confirm the happy path).

### 3.11 Lint / format (dev tooling, installed via `.[dev]`)
```bash
ruff check ai_services/
black --check ai_services/
```

---

## 4. Architecture at a Glance

```
Vendor (email / SFTP / REST)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│          Vendor Integration Domain (this PoC)              │
│                                                              │
│  Layer 1: readers.py        → raw text/rows                │
│  Layer 2: llm_extractor.py  → candidate structured fields   │
│             (Claude via Signify SSO gateway, email/PDF)     │
│             (deterministic column mapping, SFTP/CSV)        │
│  Layer 3: verifier.py       → source-text check + Pydantic  │
│                                                              │
│  Kafka:   vendor.raw_payload_received → vendor.result.extracted
│  Mongo:   vendor configs + extraction_logs audit trail       │
│  Redis:   idempotency / dedup cache (24h TTL)                │
│  FastAPI: webhook ingestion + vendor/status/stats endpoints  │
└───────────────────────────────────────────────────────────┘
        │
        ▼
  ExtractedTestResult (canonical schema, common/schemas.py)
        │
        ▼
  Test Result Domain → Reporting & Billing → Patient Portal
  (not implemented in this PoC — contract-only boundary)
```

---

## 5. Notes on git-ignored content

Most data used by this PoC is now **committed** (de-identified ground truth + generated mock vendor files — see §3.4). Only a few paths are intentionally excluded from version control (`.gitignore`) — if they appear "missing" after a fresh clone, that's expected, not broken:

| Path | Why it's git-ignored |
|---|---|
| `docs/` | Proprietary challenge brief PDFs, internal design notes, and reference material — kept local-only |
| `ancillary_results_1000.csv` (exact file, under `data/ground_truth/`) | The **raw, real** Snowflake export — contains real `MEMBERPLANID`/`EVALUATIONID`. Only needed if refreshing the fixture (§3.4); never commit it |
| `**/test_results/` | Timestamped output logs from test runs — regenerated every run |
| `.env`, `.venv/`, `__pycache__/`, `*.egg-info/` | Standard local environment / build artifacts |

`ground_truth_query.sql`, `ancillary_results_1000_deidentified.csv`, and everything under `data/mock_vendors/` (including `edge_cases/`) are tracked in git — they contain only synthetic ID tokens or hand-crafted test fixtures, no real member identifiers.

The architecture/design diagram itself isn't git-ignored because it isn't in this repo at all — it's hosted externally, linked in §1.6. Other planning docs under `docs/` (challenge brief PDFs, internal notes) remain local-only; ask a teammate who already has them if you need one.
