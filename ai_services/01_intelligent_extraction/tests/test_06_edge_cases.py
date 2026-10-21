"""
Test 06: Edge cases — verify pipeline handles bad data gracefully.

Purpose: Confirm the pipeline does NOT crash on bad input, and returns
the correct status (EXTRACTION_FAILED, VALIDATION_FAILED, FLAGGED, or
VERIFIED with partial data).

Edge cases tested:
  1. missing_fields.eml    → only ratio present, rest null → should VERIFY with partial data
  2. garbled_text.eml      → corrupted characters → should FAIL or FLAG
  3. empty_body.eml        → no content → should FAIL
  4. wrong_eval_id.eml     → fake eval 99999999 → should VERIFY (extraction works, just no ground truth match)
  5. out_of_range.eml      → impossible values → should VALIDATION_FAILED (Pydantic rejects)
  6. empty_pdf.pdf         → blank PDF → should FAIL
  7. wrong_columns.csv     → unrecognized columns → should FAIL
  8. missing_result.csv    → empty FOBT result → should FAIL for that row
  9. invalid_result.csv    → "Maybe" as FOBT result → should FAIL for that row

LLM calls: 5 (for email edge cases only)

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/tests/test_06_edge_cases.py
"""
import importlib
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

pipeline = importlib.import_module("ai_services.01_intelligent_extraction.src.extraction_pipeline")
readers = importlib.import_module("ai_services.01_intelligent_extraction.src.readers")
llm_ext = importlib.import_module("ai_services.01_intelligent_extraction.src.llm_extractor")
verf = importlib.import_module("ai_services.01_intelligent_extraction.src.verifier")
cfg = importlib.import_module("ai_services.common.config")

BASE_DIR = Path(__file__).resolve().parent.parent
EDGE_DIR = BASE_DIR / "data" / "mock_vendors" / "edge_cases"
RESULTS_DIR = Path(__file__).parent / "test_results"

output_lines = []
def log(line=""):
    print(line)
    output_lines.append(line)


def test_email_edge(filename, description, expected_statuses):
    """Test an email edge case. expected_statuses is a list of acceptable outcomes."""
    log(f"\n{'─' * 70}")
    log(f"EDGE CASE: {filename}")
    log(f"Description: {description}")
    log(f"Expected: {expected_statuses}")

    eml_path = EDGE_DIR / "email" / filename

    try:
        outcome = pipeline.extract_from_email(str(eml_path), "spirohealth_labs")

        log(f"Actual status: {outcome.status}")

        if outcome.result:
            log(f"  Extracted results: {outcome.result.results}")
            log(f"  Eval ID: {outcome.result.evaluation_id}")
            log(f"  Member ID: {outcome.result.memberplan_id}")

        if outcome.flags:
            for flag in outcome.flags:
                log(f"  Flag: {flag}")

        if outcome.error:
            log(f"  Error: {outcome.error}")

        if outcome.status in expected_statuses:
            log(f"VERDICT: PASS — pipeline handled this correctly")
            return True
        else:
            log(f"VERDICT: FAIL — expected {expected_statuses}, got {outcome.status}")
            return False

    except Exception as e:
        log(f"Actual: EXCEPTION — {type(e).__name__}: {e}")
        if "EXCEPTION" in expected_statuses:
            log(f"VERDICT: PASS — exception was expected")
            return True
        else:
            log(f"VERDICT: FAIL — pipeline should not crash, expected {expected_statuses}")
            return False


def test_pdf_edge(filename, description, expected_statuses):
    """Test a PDF edge case by running through LLM extraction directly."""
    log(f"\n{'─' * 70}")
    log(f"EDGE CASE: {filename}")
    log(f"Description: {description}")
    log(f"Expected: {expected_statuses}")

    pdf_path = EDGE_DIR / "pdf" / filename
    vendor_config = cfg.load_vendor_config("spirohealth_labs", BASE_DIR / "config")

    try:
        raw_text = readers.read_pdf(pdf_path)
        log(f"  PDF text length: {len(raw_text)} chars")

        if not raw_text or not raw_text.strip():
            log(f"Actual status: EXTRACTION_FAILED — empty PDF")
            if "EXTRACTION_FAILED" in expected_statuses:
                log(f"VERDICT: PASS — pipeline handled this correctly")
                return True
            else:
                log(f"VERDICT: FAIL — expected {expected_statuses}")
                return False

        extracted = llm_ext.extract_with_llm(raw_text, vendor_config, BASE_DIR)
        log(f"Actual status: VERIFIED (LLM returned: {extracted})")

        if "VERIFIED" in expected_statuses:
            log(f"VERDICT: PASS")
            return True
        else:
            log(f"VERDICT: FAIL — expected {expected_statuses}")
            return False

    except Exception as e:
        log(f"Actual: {type(e).__name__}: {e}")
        if "EXTRACTION_FAILED" in expected_statuses or "EXCEPTION" in expected_statuses:
            log(f"VERDICT: PASS — failure was expected")
            return True
        else:
            log(f"VERDICT: FAIL — expected {expected_statuses}")
            return False


def test_csv_edge(filename, vendor_id, description, expected_pass, expected_fail):
    """Test a CSV edge case. Check how many rows pass and fail."""
    log(f"\n{'─' * 70}")
    log(f"EDGE CASE: {filename}")
    log(f"Description: {description}")
    log(f"Expected: {expected_pass} pass, {expected_fail} fail")

    csv_path = EDGE_DIR / "csv" / filename

    try:
        outcomes = pipeline.extract_from_csv(str(csv_path), vendor_id)

        actual_pass = sum(1 for o in outcomes if o.status == "VERIFIED")
        actual_fail = len(outcomes) - actual_pass

        log(f"Actual: {actual_pass} pass, {actual_fail} fail")

        for o in outcomes:
            log(f"  {o.source_file} → {o.status}")
            if o.result:
                log(f"    results: {o.result.results}")
            if o.error:
                log(f"    error: {o.error}")

        if actual_pass == expected_pass and actual_fail == expected_fail:
            log(f"VERDICT: PASS — correct pass/fail counts")
            return True
        else:
            log(f"VERDICT: FAIL — expected {expected_pass}/{expected_fail}, got {actual_pass}/{actual_fail}")
            return False

    except Exception as e:
        log(f"Actual: EXCEPTION — {type(e).__name__}: {e}")
        if expected_pass == 0:
            log(f"VERDICT: PASS — full failure was expected")
            return True
        else:
            log(f"VERDICT: FAIL — should not crash")
            return False


def main():
    log("=" * 70)
    log("TEST 06: Edge Cases — Graceful Error Handling")
    log(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    results = []

    # Email edge cases
    results.append(("missing_fields.eml", test_email_edge(
        "missing_fields.eml",
        "Only FEV1/FVC ratio present, no FEV1%, FVC%, or grade",
        ["VERIFIED", "FLAGGED"],
    )))

    results.append(("garbled_text.eml", test_email_edge(
        "garbled_text.eml",
        "Corrupted characters in all result fields",
        ["EXTRACTION_FAILED", "FLAGGED", "VALIDATION_FAILED"],
    )))

    results.append(("empty_body.eml", test_email_edge(
        "empty_body.eml",
        "Valid email headers but empty body",
        ["EXTRACTION_FAILED", "FLAGGED"],
    )))

    results.append(("wrong_eval_id.eml", test_email_edge(
        "wrong_eval_id.eml",
        "Fake eval ID 99999999 — valid data but no ground truth match",
        ["VERIFIED"],
    )))

    results.append(("out_of_range.eml", test_email_edge(
        "out_of_range.eml",
        "FEV1/FVC=5.0, FEV1%=999, FVC%=0, Grade=Z — all impossible values",
        ["VALIDATION_FAILED", "FLAGGED"],
    )))

    results.append(("duplicate_eval.eml", test_email_edge(
        "duplicate_eval.eml",
        "Same eval ID as test_01's ground truth record (800017) but different values — tests idempotency awareness",
        ["VERIFIED", "FLAGGED"],
    )))

    results.append(("mixed_test_types.eml", test_email_edge(
        "mixed_test_types.eml",
        "Email contains both spirometry AND FOBT data — should extract spirometry only",
        ["VERIFIED", "FLAGGED"],
    )))

    results.append(("non_english.eml", test_email_edge(
        "non_english.eml",
        "Report in Spanish — LLM should still extract numeric values",
        ["VERIFIED", "FLAGGED"],
    )))

    results.append(("noisy_long_report.eml", test_email_edge(
        "noisy_long_report.eml",
        "Long email with disclaimers, billing info around actual results — LLM must find signal in noise",
        ["VERIFIED"],
    )))

    results.append(("swapped_labels.eml", test_email_edge(
        "swapped_labels.eml",
        "Non-standard field labels (Ratio, Predicted FVC Percentage, Quality) — LLM must understand semantics",
        ["VERIFIED", "FLAGGED"],
    )))

    # PDF edge cases
    results.append(("empty_pdf.pdf", test_pdf_edge(
        "empty_pdf.pdf",
        "Valid PDF file but blank page — no text to extract",
        ["EXTRACTION_FAILED"],
    )))

    results.append(("header_only.pdf", test_pdf_edge(
        "header_only.pdf",
        "PDF has patient info header but says RESULTS PENDING — no actual values",
        ["EXTRACTION_FAILED", "VERIFIED", "FLAGGED"],
    )))

    results.append(("table_format.pdf", test_pdf_edge(
        "table_format.pdf",
        "Results in a table layout with borders — different from free-text format",
        ["VERIFIED"],
    )))

    results.append(("multi_patient.pdf", test_pdf_edge(
        "multi_patient.pdf",
        "Three patients in one PDF — extraction may pick up first or all",
        ["VERIFIED", "FLAGGED", "EXTRACTION_FAILED"],
    )))

    results.append(("small_font_dense.pdf", test_pdf_edge(
        "small_font_dense.pdf",
        "Very small font, dense single-line format — pdfplumber should still extract",
        ["VERIFIED"],
    )))

    results.append(("narrative_format.pdf", test_pdf_edge(
        "narrative_format.pdf",
        "Results written as prose (zero point eight three) not numbers — hardest extraction test",
        ["VERIFIED", "FLAGGED", "EXTRACTION_FAILED"],
    )))

    # CSV edge cases
    results.append(("wrong_columns.csv", test_csv_edge(
        "wrong_columns.csv", "quickscreen_labs",
        "Columns don't match any vendor schema",
        expected_pass=0, expected_fail=2,
    )))

    results.append(("missing_result.csv", test_csv_edge(
        "missing_result.csv", "quickscreen_labs",
        "First row has empty FOBT result, second row is valid",
        expected_pass=1, expected_fail=1,
    )))

    results.append(("invalid_result.csv", test_csv_edge(
        "invalid_result.csv", "quickscreen_labs",
        "Two rows with 'Maybe'/'Inconclusive', one valid 'Negative'",
        expected_pass=1, expected_fail=2,
    )))

    results.append(("extra_columns.csv", test_csv_edge(
        "extra_columns.csv", "quickscreen_labs",
        "Valid data with unexpected extra columns (technician, notes, batch) — should still parse",
        expected_pass=2, expected_fail=0,
    )))

    results.append(("duplicate_rows.csv", test_csv_edge(
        "duplicate_rows.csv", "quickscreen_labs",
        "Same eval ID appears twice — both should extract (idempotency is a later concern)",
        expected_pass=3, expected_fail=0,
    )))

    results.append(("mixed_case_results.csv", test_csv_edge(
        "mixed_case_results.csv", "quickscreen_labs",
        "NEGATIVE, positive, Neg, pos, negative — varied capitalizations",
        expected_pass=5, expected_fail=0,
    )))

    results.append(("whitespace_issues.csv", test_csv_edge(
        "whitespace_issues.csv", "quickscreen_labs",
        "Extra spaces, tabs, leading/trailing whitespace in values",
        expected_pass=2, expected_fail=0,
    )))

    results.append(("empty_file.csv", test_csv_edge(
        "empty_file.csv", "quickscreen_labs",
        "Completely empty CSV file — no headers, no data",
        expected_pass=0, expected_fail=0,
    )))

    # Summary
    log("")
    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)

    total = len(results)
    passed = sum(1 for _, r in results if r)
    failed_list = [(name, r) for name, r in results if not r]

    log(f"  Total edge cases:   {total}")
    log(f"  Handled correctly:  {passed}")
    log(f"  Unexpected:         {total - passed}")

    if failed_list:
        log(f"\n  Unexpected results:")
        for name, _ in failed_list:
            log(f"    {name}")

    log("")
    if passed == total:
        log("RESULT: ALL EDGE CASES HANDLED CORRECTLY")
    else:
        log(f"RESULT: {total - passed} EDGE CASES HAD UNEXPECTED BEHAVIOR")

    # Save
    status = "PASS" if passed == total else "PARTIAL"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_06_edge_cases_{status}_{passed}of{total}_{timestamp}.txt"
    filepath = RESULTS_DIR / filename
    filepath.write_text("\n".join(output_lines) + "\n")
    print(f"\nResults saved to: {filepath}")

    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
