"""
De-identify Ground Truth — replaces real MEMBERPLANID and EVALUATIONID values
with sequential synthetic tokens so the dataset is safe to commit to git.

Why both IDs: EVALUATIONID alone is enough for anyone with access to
MediVisit's production/Snowflake systems to look up the real patient, visit
date, and address — tokenizing MEMBERPLANID alone is not sufficient
de-identification. All other columns (dates, lab result values, product
codes) are left untouched since they carry the clinical signal we need for
testing and aren't identifying on their own.

The mapping is deterministic (sorted ascending real ID -> sequential token),
so re-running this script against the same real export always produces the
same de-identified output.

Usage:
    cd /Users/njindal/Desktop/Study/PhD/aa_challenge
    source .venv/bin/activate
    python ai_services/01_intelligent_extraction/src/deidentify_ground_truth.py
"""
import csv
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REAL_CSV = BASE_DIR / "data" / "ground_truth" / "ancillary_results_1000.csv"
DEIDENTIFIED_CSV = BASE_DIR / "data" / "ground_truth" / "ancillary_results_1000_deidentified.csv"

MEMBERPLANID_TOKEN_START = 900001
EVALUATIONID_TOKEN_START = 800001


def build_token_map(real_ids: set[int], start: int) -> dict[int, int]:
    """Map each real ID to a sequential synthetic token, sorted ascending for determinism."""
    return {real_id: start + i for i, real_id in enumerate(sorted(real_ids))}


def main():
    if not REAL_CSV.exists():
        raise FileNotFoundError(
            f"Real ground truth not found at {REAL_CSV}. "
            f"Run the Snowflake query in data/ground_truth/ground_truth_query.sql "
            f"and save the export there first."
        )

    with open(REAL_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = rows[0].keys() if rows else []

    member_ids = {int(row["MEMBERPLANID"]) for row in rows}
    eval_ids = {int(row["EVALUATIONID"]) for row in rows}

    member_token_map = build_token_map(member_ids, MEMBERPLANID_TOKEN_START)
    eval_token_map = build_token_map(eval_ids, EVALUATIONID_TOKEN_START)

    logger.info("Tokenizing %d unique MEMBERPLANID values -> range [%d, %d]",
                len(member_token_map), MEMBERPLANID_TOKEN_START,
                MEMBERPLANID_TOKEN_START + len(member_token_map) - 1)
    logger.info("Tokenizing %d unique EVALUATIONID values -> range [%d, %d]",
                len(eval_token_map), EVALUATIONID_TOKEN_START,
                EVALUATIONID_TOKEN_START + len(eval_token_map) - 1)

    for row in rows:
        row["MEMBERPLANID"] = str(member_token_map[int(row["MEMBERPLANID"])])
        row["EVALUATIONID"] = str(eval_token_map[int(row["EVALUATIONID"])])

    DEIDENTIFIED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(DEIDENTIFIED_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote de-identified ground truth: %s (%d rows)", DEIDENTIFIED_CSV, len(rows))
    logger.info("This file is safe to commit — %s (the real export) stays git-ignored.", REAL_CSV.name)


if __name__ == "__main__":
    main()
