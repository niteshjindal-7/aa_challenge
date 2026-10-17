#!/usr/bin/env bash
# ============================================================
# MediVisit AI/ML Services — Local Development Setup
# ============================================================
# Prerequisites: Docker Desktop running, Python 3.11+, pyenv
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh           (run everything)
#   Or copy-paste individual sections as needed
# ============================================================

set -e

echo "============================================================"
echo " MediVisit AI/ML Services — Setup"
echo "============================================================"

# ── Step 1: Python Environment ─────────────────────────────────
echo ""
echo "[Step 1] Python environment..."

if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment with Python 3.11.8..."
    pyenv local 3.11.8
    python3 -m venv .venv
else
    echo "  .venv already exists — skipping"
fi

source .venv/bin/activate
echo "  Python: $(python --version)"

echo "  Installing dependencies..."
pip install -e ".[dev]" --quiet
echo "  Dependencies installed ✓"

# ── Step 2: Docker Images ──────────────────────────────────────
echo ""
echo "[Step 2] Pulling Docker images..."

docker pull mongo:7.0
docker pull redis:7.2-alpine
docker pull confluentinc/cp-kafka:7.6.0
# MinIO skipped — Zscaler blocks pull. Using local filesystem for PoC.
# MinIO stays in system design diagram as production blob storage (Azure Blob / S3).
echo "  Docker images pulled ✓"

# ── Step 3: Start Docker Services ──────────────────────────────
echo ""
echo "[Step 3] Starting Docker services..."

docker compose up -d
echo "  Waiting 5 seconds for services to initialize..."
sleep 5

echo "  Checking service status:"
docker ps --filter name=medivisit --format "    {{.Names}}: {{.Status}}"
echo "  Docker services started ✓"

# ── Step 4: Generate Mock Vendor Data ──────────────────────────
echo ""
echo "[Step 4] Generating mock vendor data..."

# Check if ground truth exists
GT_FILE="ai_services/01_intelligent_extraction/data/ground_truth/ancillary_results_1000.csv"
if [ ! -f "$GT_FILE" ]; then
    echo "  WARNING: Ground truth file not found at $GT_FILE"
    echo "  Run the Snowflake query from data/ground_truth/ground_truth_query.sql"
    echo "  and save output as $GT_FILE"
else
    python -m ai_services.01_intelligent_extraction.src.generate_mock_vendor_data
    echo "  Mock vendor data generated ✓"
fi

# ── Step 5: Verify Everything ──────────────────────────────────
echo ""
echo "[Step 5] Verification..."

# Check Python packages
python -c "
import pymongo, redis, pdfplumber, pydantic, langchain_anthropic
print('  Python packages: ✓')
"

# Check Docker services
docker exec medivisit_mongodb mongosh -u admin -p localdev --eval "db.runCommand({ping:1})" --quiet > /dev/null 2>&1 && echo "  MongoDB: ✓" || echo "  MongoDB: ✗"
docker exec medivisit_redis redis-cli -a localdev ping > /dev/null 2>&1 && echo "  Redis: ✓" || echo "  Redis: ✗"
docker exec medivisit_kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null 2>&1 && echo "  Kafka: ✓" || echo "  Kafka: ✗"

echo ""
echo "============================================================"
echo " Setup complete!"
echo "============================================================"
echo ""
echo " Services:"
echo "   MongoDB:  mongodb://admin:localdev@localhost:27017/medivisit"
echo "   Redis:    redis://:localdev@localhost:6379"
echo "   Kafka:    localhost:9092"
echo ""
echo " Useful commands:"
echo "   docker compose ps              — check service status"
echo "   docker compose down            — stop all services"
echo "   docker compose down -v         — stop + delete all data"
echo "   docker logs medivisit_kafka    — check Kafka logs"
echo "   docker logs medivisit_mongodb  — check MongoDB logs"
echo "   docker exec -it medivisit_mongodb mongosh -u admin -p localdev"
echo "                                  — open MongoDB shell"
echo ""
echo " Run tests:"
echo "   python ai_services/01_intelligent_extraction/tests/test_01_single_spiro_email.py"
echo "   python ai_services/01_intelligent_extraction/tests/test_02_all_spiro_emails.py"
echo "   python ai_services/01_intelligent_extraction/tests/test_03_all_spiro_pdfs.py"
echo "   python ai_services/01_intelligent_extraction/tests/test_04_spiro_csv.py"
echo "   python ai_services/01_intelligent_extraction/tests/test_05_fobt_csv.py"
echo "   python ai_services/01_intelligent_extraction/tests/test_06_edge_cases.py"
echo ""
