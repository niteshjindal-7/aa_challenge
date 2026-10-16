"""
Extraction Pipeline — orchestrates Layer 1 → Layer 2 → Layer 3.

Entry points:
  extract_from_email()  → email/PDF vendor reports (LLM-powered)
  extract_from_csv()    → SFTP CSV batch files (deterministic)
  run_batch()           → process all files for a given vendor

Each returns ExtractedTestResult objects or flags failures for human review.

Usage:
    python -m ai_services.01_intelligent_extraction.src.extraction_pipeline
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from ai_services.common.config import load_vendor_config
from ai_services.common.schemas import ExtractedTestResult

from .readers import read_email, read_pdf, read_csv_rows
from .llm_extractor import extract_with_llm, extract_from_csv_row, ExtractionError
from .verifier import verify_against_source, build_extracted_result

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


class ExtractionOutcome:
    """Result of one extraction attempt — either success or flagged."""

    def __init__(
        self,
        source_file: str,
        status: str,
        result: ExtractedTestResult | None = None,
        error: str | None = None,
        flags: list[str] | None = None,
    ):
        self.source_file = source_file
        self.status = status
        self.result = result
        self.error = error
        self.flags = flags or []

    def to_dict(self) -> dict:
        d = {
            "source_file": self.source_file,
            "status": self.status,
        }
        if self.result:
            d["result"] = self.result.model_dump(mode="json")
        if self.error:
            d["error"] = self.error
        if self.flags:
            d["flags"] = self.flags
        return d


# ---------------------------------------------------------------------------
# Email/PDF extraction (LLM-powered)
# ---------------------------------------------------------------------------

def extract_from_email(
    email_path: str | Path,
    vendor_id: str,
    pdf_path: str | Path | None = None,
) -> ExtractionOutcome:
    """Extract structured data from a vendor email report.

    Pipeline: read email → (optionally read PDF) → LLM extract → verify → validate

    Args:
        email_path: Path to .eml file
        vendor_id: Which vendor sent this (loads config)
        pdf_path: Optional companion PDF (same eval, vendor sends both)
    """
    email_path = Path(email_path)
    vendor_config = load_vendor_config(vendor_id, CONFIG_DIR)
    product_code = vendor_config["test_types"][0]

    # Layer 1: Read the raw text
    raw_text = read_email(email_path)

    if pdf_path:
        pdf_text = read_pdf(pdf_path)
        raw_text = raw_text + "\n\n--- PDF ATTACHMENT ---\n\n" + pdf_text

    # Layer 2: LLM extraction
    try:
        extracted = extract_with_llm(raw_text, vendor_config, BASE_DIR)
    except ExtractionError as e:
        return ExtractionOutcome(
            source_file=str(email_path),
            status="EXTRACTION_FAILED",
            error=str(e),
        )

    # Layer 3a: Verify extracted values exist in source text
    verification = verify_against_source(extracted, raw_text, product_code)

    if not verification.passed:
        return ExtractionOutcome(
            source_file=str(email_path),
            status="FLAGGED",
            flags=verification.flags,
            error=f"Verification failed: {len(verification.flags)} issues",
        )

    # Layer 3b: Pydantic validation
    try:
        result = build_extracted_result(
            extracted=extracted,
            vendor_config=vendor_config,
            product_code=product_code,
            raw_text=raw_text,
            confidence=0.95,
        )
    except Exception as e:
        return ExtractionOutcome(
            source_file=str(email_path),
            status="VALIDATION_FAILED",
            error=f"Pydantic validation failed: {e}",
        )

    return ExtractionOutcome(
        source_file=str(email_path),
        status="VERIFIED",
        result=result,
    )


# ---------------------------------------------------------------------------
# CSV extraction (deterministic — no LLM)
# ---------------------------------------------------------------------------

def extract_from_csv(
    csv_path: str | Path,
    vendor_id: str,
) -> list[ExtractionOutcome]:
    """Extract structured data from a vendor CSV batch file.

    Pipeline: read CSV rows → deterministic parse → validate (no LLM, no verification)

    Args:
        csv_path: Path to the CSV file
        vendor_id: Which vendor sent this (loads config)

    Returns:
        List of ExtractionOutcome, one per CSV row
    """
    csv_path = Path(csv_path)
    vendor_config = load_vendor_config(vendor_id, CONFIG_DIR)
    product_code = vendor_config["test_types"][0]

    rows = read_csv_rows(csv_path)
    outcomes = []

    for i, row in enumerate(rows):
        try:
            extracted = extract_from_csv_row(row, vendor_config)

            result = build_extracted_result(
                extracted=extracted,
                vendor_config=vendor_config,
                product_code=product_code,
                raw_text=str(row),
                confidence=1.0,
            )

            outcomes.append(ExtractionOutcome(
                source_file=f"{csv_path.name}:row_{i+1}",
                status="VERIFIED",
                result=result,
            ))

        except (ExtractionError, Exception) as e:
            outcomes.append(ExtractionOutcome(
                source_file=f"{csv_path.name}:row_{i+1}",
                status="EXTRACTION_FAILED",
                error=str(e),
            ))

    return outcomes


# ---------------------------------------------------------------------------
# Batch runner — process all files for a vendor
# ---------------------------------------------------------------------------

def run_batch(
    vendor_id: str,
    input_dir: str | Path | None = None,
) -> list[ExtractionOutcome]:
    """Process all vendor files in a directory.

    Auto-detects file type from vendor config (email vs sftp).

    Args:
        vendor_id: Which vendor to process
        input_dir: Override input directory (defaults to mock_vendors/)
    """
    vendor_config = load_vendor_config(vendor_id, CONFIG_DIR)
    adapter_type = vendor_config["adapter_type"]

    if input_dir is None:
        data_dir = BASE_DIR / "data" / "mock_vendors"
    else:
        data_dir = Path(input_dir)

    outcomes = []

    if adapter_type == "email":
        email_dir = data_dir / "email"
        pdf_dir = data_dir / "pdf"

        email_files = sorted(email_dir.glob("*.eml"))
        logger.info("Processing %d email files for vendor %s", len(email_files), vendor_id)

        for eml_path in email_files:
            eval_id = eml_path.stem.split("_")[-1]
            pdf_path = pdf_dir / f"{eml_path.stem.replace('.eml', '')}.pdf"
            if not pdf_path.exists():
                pdf_path = None

            outcome = extract_from_email(eml_path, vendor_id, pdf_path)
            outcomes.append(outcome)

            logger.info(
                "  %s → %s%s",
                eml_path.name,
                outcome.status,
                f" ({outcome.error})" if outcome.error else "",
            )

    elif adapter_type == "sftp":
        csv_dir = data_dir / "sftp_csv"
        file_pattern = vendor_config.get("file_pattern", "*.csv")
        csv_files = sorted(csv_dir.glob(file_pattern))

        logger.info("Processing %d CSV files for vendor %s", len(csv_files), vendor_id)

        for csv_path in csv_files:
            csv_outcomes = extract_from_csv(csv_path, vendor_id)
            outcomes.extend(csv_outcomes)

            verified = sum(1 for o in csv_outcomes if o.status == "VERIFIED")
            failed = len(csv_outcomes) - verified
            logger.info(
                "  %s → %d verified, %d failed",
                csv_path.name,
                verified,
                failed,
            )

    return outcomes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("INTELLIGENT DATA EXTRACTION PIPELINE")
    print("=" * 60)

    # Process FOBT CSV files first (no LLM needed, fast)
    print("\n--- quickscreen_labs (FOBT / SFTP CSV) ---")
    fobt_outcomes = run_batch("quickscreen_labs")
    fobt_verified = sum(1 for o in fobt_outcomes if o.status == "VERIFIED")
    print(f"FOBT: {fobt_verified}/{len(fobt_outcomes)} verified")

    # Process spirometry CSV batch (no LLM)
    print("\n--- spirohealth_labs CSV batch (SPIROMETRY / SFTP CSV) ---")
    spiro_csv_outcomes = extract_from_csv(
        BASE_DIR / "data" / "mock_vendors" / "sftp_csv" / "spirohealth_labs_spirometry_batch_001.csv",
        "spirohealth_labs",
    )
    spiro_csv_verified = sum(1 for o in spiro_csv_outcomes if o.status == "VERIFIED")
    print(f"Spiro CSV: {spiro_csv_verified}/{len(spiro_csv_outcomes)} verified")

    # Process spirometry emails (LLM-powered — expensive, do a sample)
    print("\n--- spirohealth_labs (SPIROMETRY / Email+PDF) ---")
    email_dir = BASE_DIR / "data" / "mock_vendors" / "email"
    pdf_dir = BASE_DIR / "data" / "mock_vendors" / "pdf"
    email_files = sorted(email_dir.glob("spiro_eval_*.eml"))[:5]  # sample 5

    print(f"Processing {len(email_files)} sample emails (of {len(list(email_dir.glob('*.eml')))} total)...")
    email_outcomes = []
    for eml_path in email_files:
        pdf_path = pdf_dir / eml_path.name.replace(".eml", ".pdf")
        if not pdf_path.exists():
            pdf_path = None
        outcome = extract_from_email(eml_path, "spirohealth_labs", pdf_path)
        email_outcomes.append(outcome)
        print(f"  {eml_path.name} → {outcome.status}")
        if outcome.result:
            print(f"    results: {outcome.result.results}")
        if outcome.flags:
            for flag in outcome.flags:
                print(f"    FLAG: {flag}")
        if outcome.error:
            print(f"    ERROR: {outcome.error}")

    email_verified = sum(1 for o in email_outcomes if o.status == "VERIFIED")
    print(f"Spiro Email: {email_verified}/{len(email_outcomes)} verified")

    # Summary
    all_outcomes = fobt_outcomes + spiro_csv_outcomes + email_outcomes
    total = len(all_outcomes)
    verified = sum(1 for o in all_outcomes if o.status == "VERIFIED")
    flagged = sum(1 for o in all_outcomes if o.status == "FLAGGED")
    failed = sum(1 for o in all_outcomes if o.status in ("EXTRACTION_FAILED", "VALIDATION_FAILED"))

    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"  Total processed:  {total}")
    print(f"  Verified:         {verified}")
    print(f"  Flagged:          {flagged}")
    print(f"  Failed:           {failed}")


if __name__ == "__main__":
    main()
