"""
Kafka Producer — simulates what the webhook/adapter would do in production.

In production:
  Vendor sends email → AWS SES webhook → adapter → publishes to Kafka

In our PoC:
  Mock vendor files on disk → this script reads them → publishes to Kafka

Each message is a small JSON pointer (not the file itself):
  { "vendor_id": "spirohealth_labs",
    "file_path": "mock_vendors/email/spiro_eval_19294621.eml",
    "file_type": "email",
    "received_at": "2026-10-18T00:15:00Z" }

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/src/kafka_producer.py
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Producer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = "localhost:9092"
TOPIC = "vendor.raw_payload_received"

BASE_DIR = Path(__file__).resolve().parent.parent
EMAIL_DIR = BASE_DIR / "data" / "mock_vendors" / "email"
PDF_DIR = BASE_DIR / "data" / "mock_vendors" / "pdf"
CSV_DIR = BASE_DIR / "data" / "mock_vendors" / "sftp_csv"


def delivery_callback(err, msg):
    """Called once per message to confirm delivery or report failure."""
    if err:
        logger.error("Message delivery failed: %s", err)
    else:
        logger.debug("Message delivered to %s [partition %d]", msg.topic(), msg.partition())


def publish_event(producer: Producer, vendor_id: str, file_path: str, file_type: str):
    """Publish one event to the Kafka topic."""
    event = {
        "vendor_id": vendor_id,
        "file_path": str(file_path),
        "file_type": file_type,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    producer.produce(
        topic=TOPIC,
        key=vendor_id,
        value=json.dumps(event),
        callback=delivery_callback,
    )


def main():
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})

    logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP)
    logger.info("Publishing to topic: %s", TOPIC)

    published = 0

    # ── Spirometry emails ──────────────────────────────────────────
    email_files = sorted(EMAIL_DIR.glob("spiro_eval_*.eml"))
    logger.info("Found %d spirometry email files", len(email_files))

    for eml_path in email_files:
        # Check for matching PDF
        pdf_path = PDF_DIR / eml_path.name.replace(".eml", ".pdf")
        pdf_str = str(pdf_path) if pdf_path.exists() else None

        event = {
            "vendor_id": "spirohealth_labs",
            "file_path": str(eml_path),
            "pdf_path": pdf_str,
            "file_type": "email",
            "received_at": datetime.now(timezone.utc).isoformat(),
        }

        producer.produce(
            topic=TOPIC,
            key="spirohealth_labs",
            value=json.dumps(event),
            callback=delivery_callback,
        )
        published += 1

    # ── Spirometry CSV batch ───────────────────────────────────────
    spiro_csv_files = sorted(CSV_DIR.glob("spirohealth_labs_*.csv"))
    for csv_path in spiro_csv_files:
        publish_event(producer, "spirohealth_labs", str(csv_path), "csv")
        published += 1

    # ── FOBT CSV batches ───────────────────────────────────────────
    fobt_csv_files = sorted(CSV_DIR.glob("quickscreen_labs_*.csv"))
    for csv_path in fobt_csv_files:
        publish_event(producer, "quickscreen_labs", str(csv_path), "csv")
        published += 1

    # Flush — wait for all messages to be delivered
    remaining = producer.flush(timeout=10)

    print("")
    print("=" * 60)
    print("KAFKA PRODUCER SUMMARY")
    print("=" * 60)
    print(f"  Topic:              {TOPIC}")
    print(f"  Messages published: {published}")
    print(f"  Undelivered:        {remaining}")
    print(f"  Spirometry emails:  {len(email_files)}")
    print(f"  Spirometry CSVs:    {len(spiro_csv_files)}")
    print(f"  FOBT CSVs:          {len(fobt_csv_files)}")


if __name__ == "__main__":
    main()
