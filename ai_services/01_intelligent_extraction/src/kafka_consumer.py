"""
Kafka Consumer — listens for vendor payload events and runs extraction.

This is the "worker" that runs continuously in the background.
When a message appears on the "vendor.raw_payload_received" topic:
  1. Reads the vendor file (email/PDF/CSV) from disk
  2. Runs the 3-layer extraction pipeline
  3. Logs the result to MongoDB
  4. Publishes the extracted result to "vendor.result.extracted" topic

In production this runs as a long-lived service. For our PoC it processes
all available messages and then exits.

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/src/kafka_consumer.py
"""
import importlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Consumer, Producer, KafkaError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = "localhost:9092"
INPUT_TOPIC = "vendor.raw_payload_received"
OUTPUT_TOPIC = "vendor.result.extracted"
CONSUMER_GROUP = "extraction-worker"

BASE_DIR = Path(__file__).resolve().parent.parent

# Lazy import to avoid digit-in-path issues
pipeline = importlib.import_module(
    "ai_services.01_intelligent_extraction.src.extraction_pipeline"
)
config_mod = importlib.import_module("ai_services.common.config")


def process_message(msg_value: dict, result_producer: Producer) -> dict:
    """Process one Kafka message — run extraction and return outcome."""
    vendor_id = msg_value["vendor_id"]
    file_path = msg_value["file_path"]
    file_type = msg_value["file_type"]
    pdf_path = msg_value.get("pdf_path")

    logger.info("Processing: vendor=%s, type=%s, file=%s",
                vendor_id, file_type, Path(file_path).name)

    start = time.time()

    if file_type == "email":
        outcome = pipeline.extract_from_email(file_path, vendor_id, pdf_path)
        outcomes = [outcome]
    elif file_type == "csv":
        outcomes = pipeline.extract_from_csv(file_path, vendor_id)
    else:
        logger.error("Unknown file_type: %s", file_type)
        return {"status": "ERROR", "reason": f"Unknown file_type: {file_type}"}

    elapsed = time.time() - start

    # Process each outcome
    verified = 0
    failed = 0

    for outcome in outcomes:
        # Log to MongoDB
        log_entry = {
            "vendor_id": vendor_id,
            "file_path": file_path,
            "file_type": file_type,
            "status": outcome.status,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "latency_seconds": round(elapsed, 2),
        }

        if outcome.result:
            log_entry["evaluation_id"] = outcome.result.evaluation_id
            log_entry["memberplan_id"] = outcome.result.memberplan_id
            log_entry["product_code"] = outcome.result.product_code

            # Publish extracted result to output topic
            result_event = {
                "vendor_id": vendor_id,
                "evaluation_id": outcome.result.evaluation_id,
                "memberplan_id": outcome.result.memberplan_id,
                "product_code": outcome.result.product_code,
                "status": outcome.status,
                "results": outcome.result.model_dump(mode="json"),
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            }
            result_producer.produce(
                topic=OUTPUT_TOPIC,
                key=str(outcome.result.evaluation_id),
                value=json.dumps(result_event),
            )
            verified += 1

        if outcome.error:
            log_entry["error"] = outcome.error
        if outcome.flags:
            log_entry["flags"] = outcome.flags

        # Save to MongoDB extraction_logs
        config_mod.log_extraction(log_entry)

        if outcome.status != "VERIFIED":
            failed += 1
            logger.warning("  %s → %s: %s", outcome.source_file, outcome.status,
                          outcome.error or "")
        else:
            logger.info("  %s → VERIFIED", outcome.source_file)

    return {
        "file": Path(file_path).name,
        "verified": verified,
        "failed": failed,
        "latency": round(elapsed, 2),
    }


def main():
    # Create consumer
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe([INPUT_TOPIC])

    # Create producer for output topic
    result_producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})

    logger.info("Kafka consumer started")
    logger.info("  Listening on: %s", INPUT_TOPIC)
    logger.info("  Publishing to: %s", OUTPUT_TOPIC)
    logger.info("  Consumer group: %s", CONSUMER_GROUP)

    total_processed = 0
    total_verified = 0
    total_failed = 0
    empty_polls = 0
    max_empty_polls = 10  # Exit after 10 consecutive empty polls (PoC mode)

    start_total = time.time()

    try:
        while True:
            msg = consumer.poll(timeout=2.0)

            if msg is None:
                empty_polls += 1
                if empty_polls >= max_empty_polls:
                    logger.info("No more messages after %d empty polls — exiting", max_empty_polls)
                    break
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Consumer error: %s", msg.error())
                continue

            # Reset empty poll counter
            empty_polls = 0

            # Parse message
            try:
                msg_value = json.loads(msg.value().decode("utf-8"))
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON in message: %s", e)
                continue

            # Process
            result = process_message(msg_value, result_producer)
            total_processed += 1
            total_verified += result.get("verified", 0)
            total_failed += result.get("failed", 0)

    except KeyboardInterrupt:
        logger.info("Consumer interrupted by user")
    finally:
        # Flush any pending output messages
        result_producer.flush(timeout=10)
        consumer.close()

    total_time = time.time() - start_total

    print("")
    print("=" * 60)
    print("KAFKA CONSUMER SUMMARY")
    print("=" * 60)
    print(f"  Messages consumed:  {total_processed}")
    print(f"  Results verified:   {total_verified}")
    print(f"  Results failed:     {total_failed}")
    print(f"  Total time:         {total_time:.1f}s")
    if total_processed > 0:
        print(f"  Avg per message:    {total_time / total_processed:.1f}s")


if __name__ == "__main__":
    main()
