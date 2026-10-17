"""
Seed MongoDB — loads vendor configs from JSON files into MongoDB.

This is the migration step: JSON files on disk → MongoDB documents.
After this, the extraction pipeline can read configs from MongoDB
instead of the filesystem. Adding a new vendor = inserting a document.

Collections created:
  vendors           — vendor configuration (adapter type, prompt, schema)
  extraction_logs   — will be populated by the extraction pipeline

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/src/seed_mongodb.py
"""
import json
import logging
from pathlib import Path
from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MONGO_URI = "mongodb://admin:localdev@localhost:27017"
MONGO_DB = "medivisit"

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def main():
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]

    logger.info("Connected to MongoDB: %s", MONGO_URI)
    logger.info("Database: %s", MONGO_DB)

    # ── Seed vendor configs ────────────────────────────────────────
    vendors_collection = db["vendors"]

    config_files = list(CONFIG_DIR.glob("*.json"))
    logger.info("Found %d vendor config files in %s", len(config_files), CONFIG_DIR)

    for config_file in config_files:
        with open(config_file) as f:
            vendor_data = json.load(f)

        vendor_id = vendor_data["vendor_id"]

        # Upsert: update if exists, insert if new
        result = vendors_collection.update_one(
            {"vendor_id": vendor_id},
            {"$set": vendor_data},
            upsert=True,
        )

        if result.upserted_id:
            logger.info("  Inserted new vendor: %s", vendor_id)
        else:
            logger.info("  Updated existing vendor: %s", vendor_id)

    # ── Create extraction_logs collection with index ───────────────
    if "extraction_logs" not in db.list_collection_names():
        db.create_collection("extraction_logs")
        logger.info("Created collection: extraction_logs")

    # Index on evaluation_id for fast lookups
    db["extraction_logs"].create_index("evaluation_id")
    db["extraction_logs"].create_index("vendor_id")
    db["extraction_logs"].create_index("extracted_at")
    logger.info("Created indexes on extraction_logs")

    # ── Verify ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MONGODB SEED COMPLETE")
    print("=" * 60)

    print(f"\nCollections in '{MONGO_DB}':")
    for name in db.list_collection_names():
        count = db[name].count_documents({})
        print(f"  {name}: {count} documents")

    print(f"\nVendors loaded:")
    for vendor in vendors_collection.find({}, {"_id": 0, "vendor_id": 1, "vendor_name": 1, "adapter_type": 1}):
        print(f"  {vendor['vendor_id']}: {vendor['vendor_name']} ({vendor['adapter_type']})")

    client.close()


if __name__ == "__main__":
    main()
