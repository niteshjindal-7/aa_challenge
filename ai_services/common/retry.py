"""
Error handling — retry logic, circuit breaker, dead-letter logging.

Retry: if LLM times out or returns an error, retry with exponential backoff
  (wait 2s, then 4s, then 8s before giving up)

Circuit Breaker: if LLM fails N times in a row, stop calling it for a cooldown
  period. Process CSV-only vendors while waiting. Prevents flooding a broken service.

Dead Letter: after all retries exhausted, log the failed extraction to MongoDB
  as a "dead letter" for human review later.
"""
import logging
import time
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Stops calling a service after N consecutive failures."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.last_failure_time = None
        self.is_open = False

    def record_success(self):
        self.failure_count = 0
        self.is_open = False

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(
                "Circuit breaker OPEN — %d consecutive failures. "
                "Cooldown for %ds.",
                self.failure_count,
                self.cooldown_seconds,
            )

    def can_proceed(self) -> bool:
        if not self.is_open:
            return True
        elapsed = time.time() - self.last_failure_time
        if elapsed >= self.cooldown_seconds:
            logger.info("Circuit breaker cooldown expired — allowing retry")
            self.is_open = False
            self.failure_count = 0
            return True
        logger.warning(
            "Circuit breaker OPEN — %ds remaining in cooldown",
            int(self.cooldown_seconds - elapsed),
        )
        return False

    @property
    def status(self) -> dict:
        return {
            "is_open": self.is_open,
            "failure_count": self.failure_count,
            "cooldown_seconds": self.cooldown_seconds,
        }


# Global circuit breaker for LLM calls
llm_circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=60)


def retry_with_backoff(max_retries: int = 3, base_delay: float = 2.0):
    """Decorator: retry a function with exponential backoff on failure.

    Usage:
        @retry_with_backoff(max_retries=3, base_delay=2.0)
        def call_llm(text):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                # Check circuit breaker before each attempt
                if not llm_circuit_breaker.can_proceed():
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is open — LLM calls blocked for "
                        f"{llm_circuit_breaker.cooldown_seconds}s"
                    )

                try:
                    result = func(*args, **kwargs)
                    llm_circuit_breaker.record_success()
                    return result
                except Exception as e:
                    last_exception = e
                    llm_circuit_breaker.record_failure()

                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                            attempt, max_retries, e, delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts failed: %s", max_retries, e
                        )

            raise last_exception

        return wrapper
    return decorator


def log_dead_letter(vendor_id: str, file_path: str, error: str) -> None:
    """Log a failed extraction as a dead letter in MongoDB for human review."""
    try:
        from ai_services.common.config import log_extraction

        dead_letter = {
            "vendor_id": vendor_id,
            "file_path": file_path,
            "status": "DEAD_LETTER",
            "error": error,
            "requires_human_review": True,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        log_extraction(dead_letter)
        logger.info("Dead letter logged for vendor=%s, file=%s", vendor_id, file_path)
    except Exception as e:
        logger.error("Failed to log dead letter: %s", e)


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and LLM calls are blocked."""
    pass
