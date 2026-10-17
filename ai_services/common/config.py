"""
Config loader — reads vendor configs from JSON files OR MongoDB.

The extraction pipeline calls load_vendor_config() which tries MongoDB first,
falls back to JSON files if MongoDB is unavailable. This means:
  - Development: works without Docker (reads JSON files)
  - Production: reads from MongoDB (config-driven, no code deployment)
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://admin:localdev@localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "medivisit")


# ── JSON file-based config (original, always available) ────────────

def load_json_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return json.load(f)


def _load_vendor_from_file(vendor_id: str, config_dir: str | Path) -> dict[str, Any]:
    config_dir = Path(config_dir)
    vendor_file = config_dir / f"{vendor_id}.json"
    if not vendor_file.exists():
        raise FileNotFoundError(f"No config for vendor '{vendor_id}' at {vendor_file}")
    return load_json_config(vendor_file)


def _list_vendors_from_files(config_dir: str | Path) -> list[str]:
    config_dir = Path(config_dir)
    return [f.stem for f in config_dir.glob("*.json")]


# ── MongoDB-based config (production, config-driven) ───────────────

def _get_mongo_db():
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    client.admin.command("ping")
    return client[MONGO_DB]


def _load_vendor_from_mongo(vendor_id: str) -> dict[str, Any]:
    db = _get_mongo_db()
    doc = db["vendors"].find_one({"vendor_id": vendor_id}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"No config for vendor '{vendor_id}' in MongoDB")
    return doc


def _list_vendors_from_mongo() -> list[str]:
    db = _get_mongo_db()
    return [doc["vendor_id"] for doc in db["vendors"].find({}, {"vendor_id": 1, "_id": 0})]


# ── Public API — tries MongoDB first, falls back to JSON files ─────

def load_vendor_config(vendor_id: str, config_dir: str | Path) -> dict[str, Any]:
    """Load vendor config. Tries MongoDB first, falls back to JSON file."""
    try:
        config = _load_vendor_from_mongo(vendor_id)
        logger.info("Loaded vendor '%s' from MongoDB", vendor_id)
        return config
    except Exception:
        logger.info("MongoDB unavailable, loading vendor '%s' from JSON file", vendor_id)
        return _load_vendor_from_file(vendor_id, config_dir)


def list_vendors(config_dir: str | Path) -> list[str]:
    """List all vendors. Tries MongoDB first, falls back to JSON files."""
    try:
        vendors = _list_vendors_from_mongo()
        logger.debug("Listed vendors from MongoDB: %s", vendors)
        return vendors
    except Exception:
        logger.debug("MongoDB unavailable, listing vendors from JSON files")
        return _list_vendors_from_files(config_dir)


def load_prompt_template(vendor_config: dict, base_dir: str | Path) -> str:
    """Load the prompt template file referenced in a vendor config.
    Resolves the prompt_template_file path relative to base_dir."""
    base_dir = Path(base_dir)
    template_file = vendor_config.get("prompt_template_file")
    if not template_file:
        raise ValueError(f"Vendor '{vendor_config.get('vendor_id')}' has no prompt_template_file")
    full_path = base_dir / template_file
    if not full_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {full_path}")
    return full_path.read_text()


def log_extraction(log_entry: dict) -> None:
    """Write an extraction log entry to MongoDB. Silently skips if MongoDB unavailable."""
    try:
        db = _get_mongo_db()
        db["extraction_logs"].insert_one(log_entry)
        logger.debug("Extraction log saved for eval %s", log_entry.get("evaluation_id"))
    except Exception as e:
        logger.warning("Could not save extraction log to MongoDB: %s", e)
