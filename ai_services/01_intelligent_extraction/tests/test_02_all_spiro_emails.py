"""
Test 02: Extract ALL spirometry emails (email-only, no PDF) and verify against ground truth.

Purpose: Measure extraction accuracy across all 142 spirometry email reports.
Vendor: spirohealth_labs (email only)
Test type: SPIROMETRY
LLM calls: 142 (~7 min total, ~3s each)

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/tests/test_02_all_spiro_emails.py
"""
import csv
import importlib
import logging
import time
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

pipeline = importlib.import_module(
    "ai_services.01_intelligent_extraction.src.extraction_pipeline"
)

BASE_DIR = Path(__file__).resolve().parent.parent
GROUND_TRUTH_CSV = BASE_DIR / "data" / "ground_truth" / "ancillary_results_1000_deidentified.csv"
EMAIL_DIR = BASE_DIR / "data" / "mock_vendors" / "email"
PDF_DIR = BASE_DIR / "data" / "mock_vendors" / "pdf"
RESULTS_DIR = Path(__file__).parent / "test_results"


def load_spiro_ground_truth() -> dict[int, dict]:
    """Load ground truth keyed by evaluation_id for spirometry only."""
    evals = defaultdict(lambda: {
        "memberplan_id": None,
        "fev1_fvc_ratio": None,
        "fev1_pct_predicted": None,
        "fvc_pct_predicted": None,
        "session_grade": None,
    })

    with open(GROUND_TRUTH_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["PRODUCTCODE"] != "SPIROMETRY":
                continue

            eval_id = int(row["EVALUATIONID"])
            rec = evals[eval_id]
            rec["memberplan_id"] = int(row["MEMBERPLANID"])

            rt = row["RESULT_TYPE"]
            val = row["LAB_RESULTS"]

            if rt == "SPIRO_FEV1_FVC_RATIO":
                rec["fev1_fvc_ratio"] = float(val)
            elif rt == "SPIRO_FEV1_PCT_PRED(?)":
                rec["fev1_pct_predicted"] = float(val)
            elif rt == "SPIRO_FVC_PCT_PRED(?)":
                rec["fvc_pct_predicted"] = float(val)
            elif rt == "SPIRO_SESSION_GRADE":
                rec["session_grade"] = val.strip()

    return dict(evals)


def compare_result(outcome, expected: dict) -> dict:
    """Compare extraction outcome against ground truth. Returns comparison dict."""
    if outcome.status != "VERIFIED":
        return {
            "match": False,
            "reason": f"Status: {outcome.status} — {outcome.error or 'unknown'}",
            "details": {},
        }

    result = outcome.result
    details = {}
    all_match = True

    # Check memberplan_id
    if result.memberplan_id != expected["memberplan_id"]:
        all_match = False
        details["memberplan_id"] = f"expected={expected['memberplan_id']}, got={result.memberplan_id}"

    # Check result fields
    fields = ["fev1_fvc_ratio", "fev1_pct_predicted", "fvc_pct_predicted", "session_grade"]
    for field in fields:
        expected_val = expected[field]
        extracted_val = getattr(result.results, field)

        if expected_val is None and extracted_val is None:
            continue

        if isinstance(expected_val, float) and isinstance(extracted_val, float):
            match = abs(expected_val - extracted_val) < 0.01
        else:
            match = expected_val == extracted_val

        if not match:
            all_match = False
            details[field] = f"expected={expected_val}, got={extracted_val}"

    return {"match": all_match, "reason": "" if all_match else "field mismatch", "details": details}


def main():
    output_lines = []

    def log(line=""):
        print(line)
        output_lines.append(line)

    log("=" * 70)
    log("TEST 02: All Spirometry Emails (Email Only, No PDF) — Full Accuracy Test")
    log(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    # Load ground truth
    ground_truth = load_spiro_ground_truth()
    log(f"Ground truth loaded: {len(ground_truth)} spirometry evaluations")

    # Find all email files
    email_files = sorted(EMAIL_DIR.glob("spiro_eval_*.eml"))
    log(f"Email files found: {len(email_files)}")
    log("")

    # Run extraction on each
    passed = 0
    failed = 0
    errors = 0
    latencies = []
    failure_details = []

    start_total = time.time()

    for i, eml_path in enumerate(email_files, 1):
        eval_id_str = eml_path.stem.split("_")[-1]
        eval_id = int(eval_id_str)

        pdf_path = None  # email-only test — PDF tested separately in test_03

        expected = ground_truth.get(eval_id)
        if not expected:
            log(f"  [{i}/{len(email_files)}] eval {eval_id} — SKIP (not in ground truth)")
            continue

        start = time.time()
        try:
            outcome = pipeline.extract_from_email(eml_path, "spirohealth_labs", pdf_path)
        except Exception as e:
            elapsed = time.time() - start
            errors += 1
            log(f"  [{i}/{len(email_files)}] eval {eval_id} — ERROR ({elapsed:.1f}s): {e}")
            failure_details.append({"eval_id": eval_id, "status": "ERROR", "reason": str(e)})
            continue

        elapsed = time.time() - start
        latencies.append(elapsed)

        comparison = compare_result(outcome, expected)

        result = outcome.result
        log(f"\n  [{i}/{len(email_files)}] eval {eval_id} ({elapsed:.1f}s)")
        log(f"  {'Field':<25} {'Expected':<15} {'Extracted':<15} {'Match'}")
        log(f"  {'-' * 70}")

        # Log envelope fields
        for field in ["evaluation_id", "memberplan_id"]:
            exp_val = expected.get(field, eval_id if field == "evaluation_id" else expected["memberplan_id"])
            ext_val = getattr(result, field) if result else "N/A"
            match = exp_val == ext_val
            log(f"  {field:<25} {str(exp_val):<15} {str(ext_val):<15} {'PASS' if match else 'FAIL'}")

        # Log result fields
        if result:
            for field in ["fev1_fvc_ratio", "fev1_pct_predicted", "fvc_pct_predicted", "session_grade"]:
                exp_val = expected[field]
                ext_val = getattr(result.results, field)
                if isinstance(exp_val, float) and isinstance(ext_val, float):
                    match = abs(exp_val - ext_val) < 0.01
                elif exp_val is None and ext_val is None:
                    match = True
                else:
                    match = exp_val == ext_val
                log(f"  {field:<25} {str(exp_val):<15} {str(ext_val):<15} {'PASS' if match else 'FAIL'}")

        log(f"  {'-' * 70}")

        if comparison["match"]:
            passed += 1
            log(f"  RESULT: PASS")
        else:
            failed += 1
            log(f"  RESULT: FAIL — {comparison['reason']}")
            for field, detail in comparison["details"].items():
                log(f"    {field}: {detail}")
            failure_details.append({
                "eval_id": eval_id,
                "status": "FAIL",
                "reason": comparison["reason"],
                "details": comparison["details"],
            })

    total_time = time.time() - start_total
    total = passed + failed + errors

    # Summary
    log("")
    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)
    log(f"  Total processed:    {total}")
    log(f"  Passed:             {passed}")
    log(f"  Failed:             {failed}")
    log(f"  Errors:             {errors}")
    log(f"  Accuracy:           {(passed / total * 100) if total > 0 else 0:.1f}%")
    log(f"  Total time:         {total_time:.1f}s")
    if latencies:
        log(f"  Avg latency:        {sum(latencies) / len(latencies):.1f}s per extraction")
        log(f"  Min latency:        {min(latencies):.1f}s")
        log(f"  Max latency:        {max(latencies):.1f}s")
        throughput = len(latencies) / total_time * 3600
        log(f"  Throughput:         {throughput:.0f} extractions/hour")

    if failure_details:
        log(f"\n  Failed evaluations:")
        for fd in failure_details:
            log(f"    eval {fd['eval_id']}: {fd['status']} — {fd['reason']}")

    # Save results
    status = "PASS" if failed == 0 and errors == 0 else "PARTIAL" if passed > 0 else "FAIL"
    accuracy = f"{(passed / total * 100) if total > 0 else 0:.0f}pct"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_02_all_spiro_{status}_{accuracy}_{timestamp}.txt"
    filepath = RESULTS_DIR / filename
    filepath.write_text("\n".join(output_lines) + "\n")
    print(f"\nResults saved to: {filepath}")

    if failed > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
