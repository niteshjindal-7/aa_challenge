"""
Test 05: Extract ALL FOBT CSV batch files (deterministic, no LLM) and verify against ground truth.

Purpose: Verify CSV parsing across all 3 FOBT batch files (444 results, varied formats).
Vendor: quickscreen_labs (SFTP CSV)
Test type: FOBT
LLM calls: 0 (deterministic CSV parsing)

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/tests/test_05_fobt_csv.py
"""
import csv
import importlib
import logging
import time
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent.parent
GROUND_TRUTH_CSV = BASE_DIR / "data" / "ground_truth" / "ancillary_results_1000.csv"
CSV_DIR = BASE_DIR / "data" / "mock_vendors" / "sftp_csv"
RESULTS_DIR = Path(__file__).parent / "test_results"


def load_fobt_ground_truth():
    evals = {}
    with open(GROUND_TRUTH_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["PRODUCTCODE"] != "FOBT":
                continue
            eval_id = int(row["EVALUATIONID"])
            evals[eval_id] = {
                "memberplan_id": int(row["MEMBERPLANID"]),
                "result": row["LAB_RESULTS"].strip(),
            }
    return evals


def main():
    pipeline = importlib.import_module("ai_services.01_intelligent_extraction.src.extraction_pipeline")

    output_lines = []
    def log(line=""):
        print(line)
        output_lines.append(line)

    log("=" * 70)
    log("TEST 05: All FOBT CSV Batches (Deterministic, No LLM)")
    log(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    ground_truth = load_fobt_ground_truth()
    log(f"Ground truth loaded: {len(ground_truth)} FOBT evaluations")

    csv_files = sorted(CSV_DIR.glob("quickscreen_labs_fobt_*.csv"))
    log(f"CSV batch files found: {len(csv_files)}")
    log("")

    passed = 0
    failed = 0
    errors = 0
    failure_details = []

    start_total = time.time()

    for csv_file in csv_files:
        log(f"--- Processing: {csv_file.name} ---")
        outcomes = pipeline.extract_from_csv(str(csv_file), "quickscreen_labs")

        for i, outcome in enumerate(outcomes, 1):
            if outcome.status != "VERIFIED" or not outcome.result:
                errors += 1
                log(f"  row {i}: {outcome.status} — {outcome.error}")
                failure_details.append({"file": csv_file.name, "row": i, "status": outcome.status, "reason": outcome.error})
                continue

            result = outcome.result
            eval_id = result.evaluation_id
            expected = ground_truth.get(eval_id)

            if not expected:
                errors += 1
                log(f"  row {i}: eval {eval_id} — SKIP (not in ground truth)")
                continue

            ext_result = result.results.result
            exp_result = expected["result"]
            exp_member = expected["memberplan_id"]
            ext_member = result.memberplan_id

            member_match = exp_member == ext_member
            result_match = exp_result == ext_result
            all_match = member_match and result_match

            log(f"\n  eval {eval_id}")
            log(f"  {'Field':<25} {'Expected':<15} {'Extracted':<15} {'Match'}")
            log(f"  {'-' * 70}")
            log(f"  {'evaluation_id':<25} {str(eval_id):<15} {str(result.evaluation_id):<15} PASS")
            log(f"  {'memberplan_id':<25} {str(exp_member):<15} {str(ext_member):<15} {'PASS' if member_match else 'FAIL'}")
            log(f"  {'fobt_result':<25} {str(exp_result):<15} {str(ext_result):<15} {'PASS' if result_match else 'FAIL'}")
            log(f"  {'-' * 70}")

            if all_match:
                passed += 1
                log(f"  RESULT: PASS")
            else:
                failed += 1
                log(f"  RESULT: FAIL")
                failure_details.append({"file": csv_file.name, "eval_id": eval_id, "status": "FAIL"})

        log("")

    total_time = time.time() - start_total
    total = passed + failed + errors

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
    filename = f"test_05_fobt_csv_{status}_{accuracy}_{timestamp}.txt"
    filepath = RESULTS_DIR / filename
    filepath.write_text("\n".join(output_lines) + "\n")
    print(f"\nResults saved to: {filepath}")

    if failed > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
