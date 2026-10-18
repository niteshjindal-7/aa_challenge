"""
FastAPI Service — REST API for the Intelligent Data Extraction service.

Endpoints:
  POST /webhooks/vendor-email    → receives vendor email payload, publishes to Kafka
  POST /webhooks/vendor-sftp     → receives SFTP file notification, publishes to Kafka
  GET  /vendors                  → list registered vendors from MongoDB
  GET  /extractions/{eval_id}    → check extraction status/result for an evaluation
  GET  /extractions/stats        → extraction statistics
  GET  /health                   → service health check (Kafka, MongoDB, Redis status)

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    uvicorn ai_services.01_intelligent_extraction.src.api:app --reload --port 8000

    Then open: http://localhost:8000/docs  (Swagger UI)
"""
import importlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Lazy imports
config_mod = importlib.import_module("ai_services.common.config")
redis_client = importlib.import_module("ai_services.common.redis_client")
retry_mod = importlib.import_module("ai_services.common.retry")

app = FastAPI(
    title="MediVisit Intelligent Data Extraction",
    description="AI-powered extraction of structured test results from vendor reports",
    version="0.1.0",
)

KAFKA_BOOTSTRAP = "localhost:9092"
TOPIC = "vendor.raw_payload_received"


# ── Request/Response models ────────────────────────────────────────

class VendorEmailPayload(BaseModel):
    vendor_id: str
    file_path: str
    pdf_path: str | None = None

class VendorSFTPPayload(BaseModel):
    vendor_id: str
    file_path: str

class ExtractionStatusResponse(BaseModel):
    evaluation_id: int
    status: str
    vendor_id: str | None = None
    product_code: str | None = None
    extracted_at: str | None = None
    latency_seconds: float | None = None


# ── Kafka producer (lazy init) ─────────────────────────────────────

_kafka_producer = None

def get_kafka_producer():
    global _kafka_producer
    if _kafka_producer is None:
        from confluent_kafka import Producer
        _kafka_producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})
    return _kafka_producer


# ── Endpoints ──────────────────────────────────────────────────────

@app.post("/webhooks/vendor-email", tags=["Webhooks"])
def receive_vendor_email(payload: VendorEmailPayload):
    """Receive a vendor email notification and publish to Kafka for extraction.

    In production: AWS SES / SendGrid webhook calls this endpoint.
    In PoC: called manually or by a test script.
    """
    # Verify file exists
    if not Path(payload.file_path).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {payload.file_path}")

    # Publish to Kafka
    event = {
        "vendor_id": payload.vendor_id,
        "file_path": payload.file_path,
        "pdf_path": payload.pdf_path,
        "file_type": "email",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    producer = get_kafka_producer()
    producer.produce(
        topic=TOPIC,
        key=payload.vendor_id,
        value=json.dumps(event),
    )
    producer.flush(timeout=5)

    logger.info("Published vendor email event to Kafka: vendor=%s, file=%s",
                payload.vendor_id, Path(payload.file_path).name)

    return {
        "status": "accepted",
        "message": "Event published to Kafka for extraction",
        "vendor_id": payload.vendor_id,
        "file": Path(payload.file_path).name,
    }


@app.post("/webhooks/vendor-sftp", tags=["Webhooks"])
def receive_vendor_sftp(payload: VendorSFTPPayload):
    """Receive an SFTP file drop notification and publish to Kafka for extraction."""
    if not Path(payload.file_path).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {payload.file_path}")

    event = {
        "vendor_id": payload.vendor_id,
        "file_path": payload.file_path,
        "file_type": "csv",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    producer = get_kafka_producer()
    producer.produce(
        topic=TOPIC,
        key=payload.vendor_id,
        value=json.dumps(event),
    )
    producer.flush(timeout=5)

    logger.info("Published vendor SFTP event to Kafka: vendor=%s, file=%s",
                payload.vendor_id, Path(payload.file_path).name)

    return {
        "status": "accepted",
        "message": "Event published to Kafka for extraction",
        "vendor_id": payload.vendor_id,
        "file": Path(payload.file_path).name,
    }


@app.get("/vendors", tags=["Vendors"])
def list_vendors():
    """List all registered vendors from MongoDB (falls back to JSON files)."""
    config_dir = Path(__file__).resolve().parent.parent / "config"
    vendors = config_mod.list_vendors(config_dir)

    vendor_details = []
    for vid in vendors:
        try:
            cfg = config_mod.load_vendor_config(vid, config_dir)
            vendor_details.append({
                "vendor_id": cfg["vendor_id"],
                "vendor_name": cfg.get("vendor_name", ""),
                "adapter_type": cfg["adapter_type"],
                "test_types": cfg.get("test_types", []),
                "requires_extraction": cfg.get("requires_extraction", False),
            })
        except Exception as e:
            vendor_details.append({"vendor_id": vid, "error": str(e)})

    return {"vendors": vendor_details, "total": len(vendor_details)}


@app.get("/extractions/stats", tags=["Extractions"])
def get_extraction_stats():
    """Get extraction statistics from MongoDB."""
    try:
        db = config_mod._get_mongo_db()
        collection = db["extraction_logs"]

        total = collection.count_documents({})
        verified = collection.count_documents({"status": "VERIFIED"})
        failed = collection.count_documents({"status": {"$ne": "VERIFIED"}})
        dead_letters = collection.count_documents({"status": "DEAD_LETTER"})

        # Get vendor breakdown
        vendor_stats = list(collection.aggregate([
            {"$group": {"_id": "$vendor_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]))

        return {
            "total": total,
            "verified": verified,
            "failed": failed,
            "dead_letters": dead_letters,
            "by_vendor": {s["_id"]: s["count"] for s in vendor_stats if s["_id"]},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {e}")


@app.get("/extractions/{eval_id}", tags=["Extractions"])
def get_extraction_status(eval_id: int):
    """Check extraction status for a specific evaluation ID from MongoDB."""
    try:
        db = config_mod._get_mongo_db()
        logs = list(
            db["extraction_logs"]
            .find({"evaluation_id": eval_id}, {"_id": 0})
            .sort("extracted_at", -1)
            .limit(5)
        )
        if not logs:
            raise HTTPException(status_code=404, detail=f"No extractions found for eval {eval_id}")
        return {"evaluation_id": eval_id, "extractions": logs, "total": len(logs)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {e}")


@app.get("/health", tags=["Health"])
def health_check():
    """Service health check — verifies Kafka, MongoDB, Redis connectivity."""
    health = {"service": "intelligent-data-extraction", "status": "healthy", "components": {}}

    # MongoDB
    try:
        db = config_mod._get_mongo_db()
        db.command("ping")
        health["components"]["mongodb"] = {"status": "connected"}
    except Exception as e:
        health["components"]["mongodb"] = {"status": "disconnected", "error": str(e)}
        health["status"] = "degraded"

    # Redis
    redis_stats = redis_client.get_cache_stats()
    health["components"]["redis"] = redis_stats
    if not redis_stats.get("connected"):
        health["status"] = "degraded"

    # Kafka
    try:
        from confluent_kafka import Producer
        p = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})
        p.flush(timeout=2)
        health["components"]["kafka"] = {"status": "connected", "bootstrap": KAFKA_BOOTSTRAP}
    except Exception as e:
        health["components"]["kafka"] = {"status": "disconnected", "error": str(e)}
        health["status"] = "degraded"

    # Circuit breaker
    health["components"]["llm_circuit_breaker"] = retry_mod.llm_circuit_breaker.status

    return health
