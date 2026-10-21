"""
Test 04: Extract spirometry CSV batch file (deterministic, no LLM) and verify against ground truth.

Purpose: Verify CSV parsing for the 5% of spirometry evals delivered via SFTP.
Vendor: spirohealth_labs (SFTP CSV)
Test type: SPIROMETRY
LLM calls: 0 (deterministic CSV parsing)

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/tests/test_04_spiro_csv.py
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

BASE_DIR = Path(__file__).resolve().parent.parent
GROUND_TRUTH_CSV = BASE_DIR / "data" / "ground_truth" / "ancillary_results_1000_deidentified.csv"
CSV_DIR = BASE_DIR / "data" / "mock_vendors" / "sftp_csv"
RESULTS_DIR = Path(__file__).parent / "test_results"


def load_spiro_ground_truth():
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


def main():
    pipeline = importlib.import_module("ai_services.01_intelligent_extraction.src.extraction_pipeline")

    output_lines = []
    def log(line=""):
        print(line)
        output_lines.append(line)

    log("=" * 70)
    log("TEST 04: Spirometry CSV Batch (Deterministic, No LLM)")
    log(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    ground_truth = load_spiro_ground_truth()
    log(f"Ground truth loaded: {len(ground_truth)} spirometry evaluations")

    csv_file = CSV_DIR / "spirohealth_labs_spirometry_batch_001.csv"
    log(f"CSV file: {csv_file.name}")
    log("")

    start_total = time.time()
    outcomes = pipeline.extract_from_csv(str(csv_file), "spirohealth_labs")
    total_time = time.time() - start_total

    passed = 0
    failed = 0
    errors = 0
    failure_details = []

    for i, outcome in enumerate(outcomes, 1):
        if outcome.status != "VERIFIED" or not outcome.result:
            errors += 1
            log(f"\n  [{i}/{len(outcomes)}] {outcome.source_file}")
            log(f"  RESULT: {outcome.status} — {outcome.error}")
            failure_details.append({"row": i, "status": outcome.status, "reason": outcome.error})
            continue

        result = outcome.result
        eval_id = result.evaluation_id
        expected = ground_truth.get(eval_id)

        if not expected:
            errors += 1
            log(f"\n  [{i}/{len(outcomes)}] eval {eval_id} — SKIP (not in ground truth)")
            continue

        log(f"\n  [{i}/{len(outcomes)}] eval {eval_id}")
        log(f"  {'Field':<25} {'Expected':<15} {'Extracted':<15} {'Match'}")
        log(f"  {'-' * 70}")

        all_match = True
        for field in ["evaluation_id", "memberplan_id"]:
            exp_val = eval_id if field == "evaluation_id" else expected["memberplan_id"]
            ext_val = getattr(result, field)
            match = exp_val == ext_val
            if not match: all_match = False
            log(f"  {field:<25} {str(exp_val):<15} {str(ext_val):<15} {'PASS' if match else 'FAIL'}")

        for field in ["fev1_fvc_ratio", "fev1_pct_predicted", "fvc_pct_predicted", "session_grade"]:
            exp_val = expected[field]
            ext_val = getattr(result.results, field)
            if isinstance(exp_val, float) and isinstance(ext_val, float):
                match = abs(exp_val - ext_val) < 0.01
            elif exp_val is None and ext_val is None:
                match = True
            else:
                match = exp_val == ext_val
            if not match: all_match = False
            log(f"  {field:<25} {str(exp_val):<15} {str(ext_val):<15} {'PASS' if match else 'FAIL'}")

        log(f"  {'-' * 70}")
        if all_match:
            passed += 1
            log(f"  RESULT: PASS")
        else:
            failed += 1
            log(f"  RESULT: FAIL")
            failure_details.append({"row": i, "eval_id": eval_id, "status": "FAIL"})

    total = passed + failed + errors
    log("")
    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)
    log(f"  Total processed:    {total}")
    log(f"  Passed:             {passed}")
    log(f"  Failed:             {failed}")
    log(f"  Errors:             {errors}")
    log(f"  Accuracy:           {(passed / total * 100) if total > 0 else 0:.1f}%")
    log(f"  Total time:         {total_time:.2f}s")

    if failure_details:
        log(f"\n  Failures:")
        for fd in failure_details:
            log(f"    {fd}")

    status = "PASS" if failed == 0 and errors == 0 else "PARTIAL" if passed > 0 else "FAIL"
    accuracy = f"{(passed / total * 100) if total > 0 else 0:.0f}pct"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_04_spiro_csv_{status}_{accuracy}_{timestamp}.txt"
    filepath = RESULTS_DIR / filename
    filepath.write_text("\n".join(output_lines) + "\n")
    print(f"\nResults saved to: {filepath}")

    if failed > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
