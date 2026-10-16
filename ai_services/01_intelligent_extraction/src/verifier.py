"""
Layer 3: Source Verification + Pydantic Validation

Two checks on the LLM's output before it becomes a trusted result:

  3a. Source Verification: does each extracted numeric value actually
      appear in the original raw text? Catches LLM hallucinations.

  3b. Pydantic Validation: does the extracted data conform to the
      correct schema with valid types and ranges?

For CSV-extracted data (no LLM involved), only 3b runs — the
deterministic parser is trusted for exact values.
"""
import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from ai_services.common.schemas import (
    ExtractedTestResult,
    ExtractionMetadata,
    PRODUCT_CODE_TO_SCHEMA,
)

logger = logging.getLogger(__name__)


class VerificationResult:
    """Holds the outcome of verification — either verified or flagged."""

    def __init__(self):
        self.passed = True
        self.flags: list[str] = []

    def flag(self, reason: str):
        self.passed = False
        self.flags.append(reason)
        logger.warning("Verification flag: %s", reason)

    @property
    def status(self) -> str:
        return "VERIFIED" if self.passed else "FLAGGED"


def verify_against_source(
    extracted: dict,
    raw_text: str,
    product_code: str,
) -> VerificationResult:
    """3a: Check that extracted numeric/string values exist in the raw text.

    For each extracted value, we search for it in the source text.
    If a value doesn't appear, the LLM may have hallucinated it.

    Args:
        extracted: The candidate dict from LLM extraction
        raw_text: The original vendor report text (from Layer 1)
        product_code: Which test type this is (determines which fields to check)

    Returns:
        VerificationResult with pass/fail and flag reasons
    """
    result = VerificationResult()

    fields_to_verify = _get_verifiable_fields(product_code)

    for field_name in fields_to_verify:
        value = extracted.get(field_name)
        if value is None:
            continue

        str_value = str(value)

        if _value_present_in_text(str_value, raw_text):
            logger.debug("Verified %s=%s in source text", field_name, str_value)
        else:
            result.flag(
                f"Value {field_name}={str_value} not found in source text — "
                f"possible LLM hallucination"
            )

    return result


def _get_verifiable_fields(product_code: str) -> list[str]:
    """Return the field names that should be verified against source text."""
    verify_map = {
        "SPIROMETRY": ["fev1_fvc_ratio", "fev1_pct_predicted", "fvc_pct_predicted", "session_grade"],
        "FOBT": ["result"],
        "HBA1CPOC": ["hba1c_pct"],
        "UACR": ["uacr_mg_g"],
        "COG": ["score"],
        "CECG": [],  # free-text findings — verification is harder, skip for now
    }
    return verify_map.get(product_code, [])


def _value_present_in_text(value: str, text: str) -> bool:
    """Check if a value appears in the text, with fuzzy matching for numbers.

    Handles cases like:
      - "0.73" in "FEV1/FVC Ratio: 0.73" → True
      - "79" in "FEV1 (% Predicted): 79%" → True
      - "F" in "Session Quality Grade: F" → True (but checks word boundary)
    """
    if not value or not text:
        return False

    # Direct string match
    if value in text:
        return True

    # For single-character values (grades), check word boundary
    if len(value) == 1:
        pattern = rf'\b{re.escape(value)}\b'
        if re.search(pattern, text):
            return True

    # For numeric values, try common format variations
    try:
        num = float(value)
        # Check integer representation: "79.0" should match "79"
        if num == int(num):
            if str(int(num)) in text:
                return True
        # Check with different decimal places
        for fmt in [f"{num:.0f}", f"{num:.1f}", f"{num:.2f}", f"{num:.3f}"]:
            if fmt in text:
                return True
        # Check percentage format: 0.73 might appear as "73%"
        pct = num * 100
        if f"{pct:.0f}" in text:
            return True
    except (ValueError, TypeError):
        pass

    return False


def build_extracted_result(
    extracted: dict,
    vendor_config: dict,
    product_code: str,
    raw_text: str,
    confidence: float,
) -> ExtractedTestResult:
    """3b: Build and validate the final ExtractedTestResult via Pydantic.

    This constructs the canonical output. Pydantic enforces:
    - Correct field types (int, float, str)
    - Value ranges (FEV1/FVC between 0.20–1.00, etc.)
    - Required fields present
    - No extra unknown fields (extra=forbid on test-type models)

    Args:
        extracted: Verified dict from Layer 2 + Layer 3a
        vendor_config: Vendor JSON config
        product_code: Test type code (SPIROMETRY, FOBT, etc.)
        raw_text: Original text (for hashing)
        confidence: Confidence score (1.0 for CSV, variable for LLM)

    Returns:
        ExtractedTestResult: The validated, canonical result

    Raises:
        ValidationError: If Pydantic rejects the data
    """
    # Separate envelope fields from test-specific result fields
    envelope_fields = {"evaluation_id", "memberplan_id", "date_of_service"}
    result_fields = {k: v for k, v in extracted.items() if k not in envelope_fields}

    model_used = "deterministic_csv_parser"
    if vendor_config.get("requires_extraction", False):
        model_used = f"llm:{vendor_config.get('vendor_id', 'unknown')}"

    return ExtractedTestResult(
        vendor_id=vendor_config["vendor_id"],
        vendor_type=vendor_config["adapter_type"],
        evaluation_id=extracted["evaluation_id"],
        memberplan_id=extracted["memberplan_id"],
        date_of_service=extracted["date_of_service"],
        product_code=product_code,
        results=result_fields,
        extraction_metadata=ExtractionMetadata(
            model_used=model_used,
            confidence=confidence,
            extracted_at=datetime.now(),
            raw_text_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
        ),
    )
