"""
Test 03: Extract ALL spirometry PDFs (PDF only, no email) and verify against ground truth.

Purpose: Measure extraction accuracy across all 142 spirometry PDF reports.
Vendor: spirohealth_labs (PDF only)
Test type: SPIROMETRY
LLM calls: 142 (~7 min total, ~3s each)

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/tests/test_03_all_spiro_pdfs.py
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
PDF_DIR = BASE_DIR / "data" / "mock_vendors" / "pdf"
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
    readers = importlib.import_module("ai_services.01_intelligent_extraction.src.readers")
    llm_ext = importlib.import_module("ai_services.01_intelligent_extraction.src.llm_extractor")
    verf = importlib.import_module("ai_services.01_intelligent_extraction.src.verifier")
    cfg = importlib.import_module("ai_services.common.config")

    output_lines = []
    def log(line=""):
        print(line)
        output_lines.append(line)

    log("=" * 70)
    log("TEST 03: All Spirometry PDFs (PDF Only, No Email) — Full Accuracy Test")
    log(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    ground_truth = load_spiro_ground_truth()
    log(f"Ground truth loaded: {len(ground_truth)} spirometry evaluations")

    pdf_files = sorted(PDF_DIR.glob("spiro_eval_*.pdf"))
    log(f"PDF files found: {len(pdf_files)}")
    log("")

    vendor_config = cfg.load_vendor_config("spirohealth_labs", BASE_DIR / "config")
    product_code = "SPIROMETRY"

    passed = 0
    failed = 0
    errors = 0
    latencies = []
    failure_details = []
    start_total = time.time()

    for i, pdf_path in enumerate(pdf_files, 1):
        eval_id_str = pdf_path.stem.split("_")[-1]
        eval_id = int(eval_id_str)
        expected = ground_truth.get(eval_id)
        if not expected:
            log(f"  [{i}/{len(pdf_files)}] eval {eval_id} — SKIP (not in ground truth)")
            continue

        start = time.time()
        try:
            raw_text = readers.read_pdf(pdf_path)
            extracted = llm_ext.extract_with_llm(raw_text, vendor_config, BASE_DIR)
            verification = verf.verify_against_source(extracted, raw_text, product_code)

            if not verification.passed:
                elapsed = time.time() - start
                failed += 1
                latencies.append(elapsed)
                log(f"\n  [{i}/{len(pdf_files)}] eval {eval_id} ({elapsed:.1f}s)")
                log(f"  RESULT: FLAGGED")
                for flag in verification.flags:
                    log(f"    {flag}")
                failure_details.append({"eval_id": eval_id, "status": "FLAGGED", "reason": str(verification.flags)})
                continue

            result = verf.build_extracted_result(
                extracted=extracted, vendor_config=vendor_config,
                product_code=product_code, raw_text=raw_text, confidence=0.95,
            )
        except Exception as e:
            elapsed = time.time() - start
            errors += 1
            log(f"\n  [{i}/{len(pdf_files)}] eval {eval_id} ({elapsed:.1f}s)")
            log(f"  RESULT: ERROR — {e}")
            failure_details.append({"eval_id": eval_id, "status": "ERROR", "reason": str(e)})
            continue

        elapsed = time.time() - start
        latencies.append(elapsed)

        log(f"\n  [{i}/{len(pdf_files)}] eval {eval_id} ({elapsed:.1f}s)")
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
            failure_details.append({"eval_id": eval_id, "status": "FAIL", "reason": "field mismatch"})

    total_time = time.time() - start_total
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

    status = "PASS" if failed == 0 and errors == 0 else "PARTIAL" if passed > 0 else "FAIL"
    accuracy = f"{(passed / total * 100) if total > 0 else 0:.0f}pct"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_03_all_spiro_pdfs_{status}_{accuracy}_{timestamp}.txt"
    filepath = RESULTS_DIR / filename
    filepath.write_text("\n".join(output_lines) + "\n")
    print(f"\nResults saved to: {filepath}")

    if failed > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
