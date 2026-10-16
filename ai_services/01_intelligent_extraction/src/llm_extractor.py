"""
Layer 2: LLM Extraction

Takes raw text from Layer 1 readers, sends it to Claude with a
vendor-specific prompt template, and returns a candidate JSON dict.

The LLM is good at: understanding varied phrasing, identifying fields
in different report layouts, handling free text.

The LLM is NOT the final authority on numbers — Layer 3 verifies.
"""
import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage

from ai_services.common.llm_config import get_llm
from ai_services.common.config import load_prompt_template

logger = logging.getLogger(__name__)


def extract_with_llm(
    raw_text: str,
    vendor_config: dict,
    base_dir: str | Path,
) -> dict:
    """Call the LLM to extract structured data from raw vendor text.

    Args:
        raw_text: Plain text from Layer 1 reader (email body or PDF text)
        vendor_config: The vendor's JSON config (has prompt_template_file)
        base_dir: Base directory to resolve prompt_template_file path

    Returns:
        dict: Candidate extracted fields (unverified — Layer 3 checks these)

    Raises:
        ExtractionError: If LLM returns unparseable output
    """
    prompt_template = load_prompt_template(vendor_config, base_dir)
    prompt_text = prompt_template.replace("{raw_text}", raw_text)

    llm = get_llm(temperature=0.0)

    logger.info(
        "Calling LLM for vendor=%s, text_length=%d",
        vendor_config["vendor_id"],
        len(raw_text),
    )

    response = llm.invoke([HumanMessage(content=prompt_text)])
    response_text = response.content.strip()

    # Strip markdown code fences if the LLM wraps its response
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        response_text = "\n".join(lines).strip()

    try:
        extracted = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", response_text[:200])
        raise ExtractionError(
            f"LLM returned unparseable JSON for vendor "
            f"'{vendor_config['vendor_id']}': {e}"
        ) from e

    logger.info("LLM extraction complete: %d fields extracted", len(extracted))
    return extracted


def extract_from_csv_row(
    row: dict[str, str],
    vendor_config: dict,
) -> dict:
    """Deterministic extraction from a CSV row — no LLM needed.

    Maps vendor-specific column names to our canonical field names
    based on the vendor's config. For structured CSV data, this is
    more reliable and faster than calling an LLM.

    Args:
        row: A single CSV row as {column_name: value}
        vendor_config: The vendor's JSON config

    Returns:
        dict: Extracted fields in canonical naming
    """
    vendor_id = vendor_config["vendor_id"]

    if vendor_id == "spirohealth_labs":
        return _extract_spiro_csv(row)
    elif vendor_id == "quickscreen_labs":
        return _extract_fobt_csv(row)
    else:
        raise ExtractionError(f"No CSV mapping defined for vendor '{vendor_id}'")


def _extract_spiro_csv(row: dict[str, str]) -> dict:
    """Map spirohealth CSV columns to canonical fields."""
    return {
        "evaluation_id": _safe_int(row.get("eval_ref")),
        "memberplan_id": _safe_int(row.get("member_ref")),
        "date_of_service": row.get("test_date"),
        "fev1_fvc_ratio": _safe_float(row.get("fev1_fvc")),
        "fev1_pct_predicted": _safe_float(row.get("fev1_pct_pred")),
        "fvc_pct_predicted": _safe_float(row.get("fvc_pct_pred")),
        "session_grade": row.get("quality_grade") or None,
    }


def _extract_fobt_csv(row: dict[str, str]) -> dict:
    """Map quickscreen CSV columns to canonical fields.
    Handles all 3 CSV format variations (standard, abbreviated, verbose)."""
    eval_id = _safe_int(
        row.get("evaluation_id") or row.get("eval_id") or row.get("CaseNumber")
    )
    member_id = _safe_int(
        row.get("member_id") or row.get("mbr_plan_id") or row.get("PatientPlanID")
    )
    dos = row.get("test_date") or row.get("dos") or row.get("ServiceDate")

    raw_result = (
        row.get("fobt_result") or row.get("result") or row.get("OccultBloodScreenResult") or ""
    ).strip().upper()

    if raw_result in ("POSITIVE", "POS", "DETECTED", "ABNORMAL"):
        result = "Positive"
    elif raw_result in ("NEGATIVE", "NEG", "NOT DETECTED", "NORMAL"):
        result = "Negative"
    else:
        raise ExtractionError(f"Unrecognized FOBT result value: '{raw_result}'")

    return {
        "evaluation_id": eval_id,
        "memberplan_id": member_id,
        "date_of_service": dos,
        "result": result,
    }


def _safe_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def _safe_int(val: str | None) -> int | None:
    if not val or not val.strip():
        return None
    try:
        return int(float(val.strip()))
    except ValueError:
        return None


class ExtractionError(Exception):
    """Raised when extraction fails — routes to human review."""
    pass
