"""
Redis client — extraction result caching and idempotency (dedup).

Two purposes:
  1. Idempotency: if the same vendor report arrives twice, skip re-extraction
  2. LLM cache: avoid redundant LLM calls for identical content

Key format: extraction:{content_hash}
Value: JSON string of the extraction result
TTL: 24 hours (re-extract after that in case prompts improved)
"""
import hashlib
import json
import logging
import os

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://:localdev@localhost:6379/0")
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def get_cached_result(content_hash: str) -> dict | None:
    """Check if extraction result exists in Redis cache."""
    try:
        r = _get_redis()
        key = f"extraction:{content_hash}"
        cached = r.get(key)
        if cached:
            logger.info("Redis cache HIT for hash %s...", content_hash[:12])
            return json.loads(cached)
        logger.debug("Redis cache MISS for hash %s...", content_hash[:12])
        return None
    except Exception as e:
        logger.warning("Redis unavailable, skipping cache check: %s", e)
        return None


def cache_result(content_hash: str, result: dict) -> None:
    """Store extraction result in Redis cache with TTL."""
    try:
        r = _get_redis()
        key = f"extraction:{content_hash}"
        r.setex(key, CACHE_TTL_SECONDS, json.dumps(result))
        logger.debug("Cached result for hash %s... (TTL: %ds)", content_hash[:12], CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Redis unavailable, skipping cache store: %s", e)


def get_cache_stats() -> dict:
    """Get Redis cache statistics for monitoring."""
    try:
        r = _get_redis()
        info = r.info("stats")
        keys = r.dbsize()
        return {
            "total_cached": keys,
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
            "connected": True,
        }
    except Exception:
        return {"connected": False}
