"""
Test 01: Extract a single spirometry email+PDF and verify against ground truth.

Purpose: Confirm the 3-layer pipeline works end-to-end for one vendor report.
Vendor: spirohealth_labs (email + PDF)
Test type: SPIROMETRY
LLM calls: 1

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/tests/test_01_single_spiro_email.py
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

pipeline = importlib.import_module(
    "ai_services.01_intelligent_extraction.src.extraction_pipeline"
)

# Ground truth for eval 800017 (de-identified token; originally eval 19294621
# in the real Snowflake export — see deidentify_ground_truth.py)
EXPECTED = {
    "evaluation_id": 800017,
    "memberplan_id": 900456,
    "fev1_fvc_ratio": 0.82,
    "fev1_pct_predicted": 59.0,
    "fvc_pct_predicted": 60.0,
    "session_grade": "F",
}

EMAIL_PATH = "ai_services/01_intelligent_extraction/data/mock_vendors/email/spiro_eval_800017.eml"
PDF_PATH = "ai_services/01_intelligent_extraction/data/mock_vendors/pdf/spiro_eval_800017.pdf"

RESULTS_DIR = Path(__file__).parent / "test_results"


def main():
    output_lines = []

    def log(line=""):
        print(line)
        output_lines.append(line)

    log("=" * 70)
    log("TEST 01: Single Spirometry Email + PDF Extraction")
    log(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    # Run extraction
    outcome = pipeline.extract_from_email(EMAIL_PATH, "spirohealth_labs", PDF_PATH)

    log(f"\nExtraction status: {outcome.status}")

    if outcome.status != "VERIFIED":
        log("FAIL — extraction did not verify")
        if outcome.error:
            log(f"  Error: {outcome.error}")
        if outcome.flags:
            for flag in outcome.flags:
                log(f"  Flag: {flag}")
        save_results(output_lines, "FAIL")
        sys.exit(1)

    # Compare against ground truth
    result = outcome.result
    log(f"\nComparing extracted values against ground truth:")
    log(f"{'Field':<25} {'Expected':<15} {'Extracted':<15} {'Match'}")
    log("-" * 70)

    all_match = True

    for field in ["evaluation_id", "memberplan_id"]:
        expected_val = EXPECTED[field]
        extracted_val = getattr(result, field)
        match = expected_val == extracted_val
        if not match:
            all_match = False
        log(f"{field:<25} {str(expected_val):<15} {str(extracted_val):<15} {'PASS' if match else 'FAIL'}")

    results = result.results
    for field in ["fev1_fvc_ratio", "fev1_pct_predicted", "fvc_pct_predicted", "session_grade"]:
        expected_val = EXPECTED[field]
        extracted_val = getattr(results, field)

        if isinstance(expected_val, float) and isinstance(extracted_val, float):
            match = abs(expected_val - extracted_val) < 0.01
        else:
            match = expected_val == extracted_val

        if not match:
            all_match = False
        log(f"{field:<25} {str(expected_val):<15} {str(extracted_val):<15} {'PASS' if match else 'FAIL'}")

    log("-" * 70)
    if all_match:
        log("RESULT: ALL FIELDS MATCH GROUND TRUTH — TEST PASSED")
    else:
        log("RESULT: MISMATCH DETECTED — TEST FAILED")

    save_results(output_lines, "PASS" if all_match else "FAIL")

    if not all_match:
        sys.exit(1)


def save_results(lines: list[str], status: str):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_01_single_spiro_{status}_{timestamp}.txt"
    filepath = RESULTS_DIR / filename
    filepath.write_text("\n".join(lines) + "\n")
    print(f"\nResults saved to: {filepath}")


if __name__ == "__main__":
    main()
