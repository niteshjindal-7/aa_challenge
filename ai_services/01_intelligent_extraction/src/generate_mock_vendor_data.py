"""
Mock Vendor Data Generator — reads ground truth CSV and generates
realistic vendor reports in email (.eml), PDF, and CSV formats.

Vendors:
  spirohealth_labs    → SPIROMETRY → 95% email+PDF, 5% CSV batch
  quickscreen_labs    → FOBT       → 100% SFTP CSV

Usage:
    python -m ai_services.01_intelligent_extraction.src.generate_mock_vendor_data
"""
import csv
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fpdf import FPDF


BASE_DIR = Path(__file__).resolve().parent.parent
GROUND_TRUTH_CSV = BASE_DIR / "data" / "ground_truth" / "ancillary_results_1000.csv"
OUTPUT_EMAIL_DIR = BASE_DIR / "data" / "mock_vendors" / "email"
OUTPUT_PDF_DIR = BASE_DIR / "data" / "mock_vendors" / "pdf"
OUTPUT_CSV_DIR = BASE_DIR / "data" / "mock_vendors" / "sftp_csv"

SPIRO_CSV_FRACTION = 0.05  # 5% of spirometry evals go to CSV instead of email+PDF


# ===========================================================================
# SPIROMETRY — clinical interpretation helpers
# ===========================================================================

def interpret_fev1_fvc_ratio(ratio: float) -> str:
    if ratio >= 0.80:
        return "Normal airflow; no obstructive pattern identified."
    elif ratio >= 0.70:
        return "Borderline ratio. Mild airflow limitation may be present."
    elif ratio >= 0.60:
        return "Moderate obstructive pattern detected. Recommend clinical correlation."
    elif ratio >= 0.50:
        return "Moderately severe obstruction. Bronchodilator response testing advised."
    else:
        return "Severe obstructive ventilatory defect. Urgent pulmonary consultation recommended."


def interpret_fev1_pct(pct: float) -> str:
    if pct >= 80:
        return "FEV1 within normal limits."
    elif pct >= 60:
        return "Mildly reduced FEV1."
    elif pct >= 40:
        return "Moderately reduced FEV1."
    else:
        return "Severely reduced FEV1."


def interpret_session_grade(grade: str) -> str:
    grade_map = {
        "A": "Excellent session quality - highly reproducible maneuvers.",
        "B": "Good session quality - meets acceptability criteria.",
        "C": "Acceptable session quality - meets minimum criteria.",
        "D": "Below-standard session quality - results should be interpreted with caution.",
        "E": "Poor session quality - consider retesting.",
        "F": "Failed session quality - results unreliable, retest required.",
        "U": "Unacceptable session - unable to produce valid maneuvers.",
    }
    return grade_map.get(grade, "Session quality not graded.")


# ===========================================================================
# Randomizers for varied report styles
# ===========================================================================

SPIRO_DOCTORS = [
    ("Dr. Jennifer Walsh, MD", "Chief Pulmonologist"),
    ("Dr. Michael Torres, DO", "Pulmonary Function Specialist"),
    ("Dr. Aisha Patel, MD", "Respiratory Medicine Consultant"),
    ("Dr. Robert Kim, MD", "Senior Pulmonologist"),
    ("Dr. Sarah Okonkwo, MD", "Clinical Pulmonary Director"),
]

EMAIL_STYLES = ["formal", "concise", "detailed"]


# ===========================================================================
# Ground truth loaders
# ===========================================================================

def load_spirometry_evaluations() -> list[dict]:
    """Group all SPIROMETRY rows for each evaluation into one record."""
    evals = defaultdict(lambda: {
        "memberplan_id": None,
        "evaluation_id": None,
        "date_of_service": None,
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

            key = (row["MEMBERPLANID"], row["EVALUATIONID"])
            rec = evals[key]
            rec["memberplan_id"] = int(row["MEMBERPLANID"])
            rec["evaluation_id"] = int(row["EVALUATIONID"])
            rec["date_of_service"] = row["DATEOFSERVICE"]

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

    return list(evals.values())


def load_fobt_evaluations() -> list[dict]:
    """Load all FOBT rows — one row per evaluation."""
    evals = []
    with open(GROUND_TRUTH_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["PRODUCTCODE"] != "FOBT":
                continue
            evals.append({
                "memberplan_id": int(row["MEMBERPLANID"]),
                "evaluation_id": int(row["EVALUATIONID"]),
                "date_of_service": row["DATEOFSERVICE"],
                "result": row["LAB_RESULTS"].strip(),
            })
    return evals


# ===========================================================================
# SPIROMETRY — email generator (.eml text files)
# ===========================================================================

def generate_spiro_email(rec: dict, doctor: tuple, style: str) -> str:
    doc_name, doc_title = doctor
    eval_id = rec["evaluation_id"]
    mp_id = rec["memberplan_id"]
    dos = rec["date_of_service"]
    ratio = rec["fev1_fvc_ratio"]
    fev1_pct = rec["fev1_pct_predicted"]
    fvc_pct = rec["fvc_pct_predicted"]
    grade = rec["session_grade"]

    if style == "formal":
        body = f"""Dear MediVisit Clinical Team,

Please find enclosed the spirometry analysis results for the patient evaluation
completed on {dos}.

Patient Reference: MemberPlan ID {mp_id}
Evaluation Reference: {eval_id}
Date of Testing: {dos}

SPIROMETRY RESULTS:

"""
        if ratio is not None:
            body += f"  FEV1/FVC Ratio: {ratio:.2f}\n"
            body += f"  Interpretation: {interpret_fev1_fvc_ratio(ratio)}\n\n"
        if fev1_pct is not None:
            body += f"  FEV1 (% Predicted): {fev1_pct:.0f}%\n"
            body += f"  Interpretation: {interpret_fev1_pct(fev1_pct)}\n\n"
        if fvc_pct is not None:
            body += f"  FVC (% Predicted): {fvc_pct:.0f}%\n\n"
        if grade is not None:
            body += f"  Session Quality Grade: {grade}\n"
            body += f"  Note: {interpret_session_grade(grade)}\n\n"

        body += f"""This report was generated by SpiroHealth Laboratories automated analysis
platform and reviewed by {doc_name}.

If you have any questions regarding these findings, please contact our
clinical support team at support@spirohealthlabs.com.

Sincerely,
{doc_name}
{doc_title}
SpiroHealth Laboratories Inc.
"""

    elif style == "concise":
        body = f"""SpiroHealth Labs - Spirometry Report
Eval: {eval_id} | Member: {mp_id} | Date: {dos}

"""
        if ratio is not None:
            body += f"FEV1/FVC: {ratio}\n"
        if fev1_pct is not None:
            body += f"FEV1%Pred: {fev1_pct:.0f}\n"
        if fvc_pct is not None:
            body += f"FVC%Pred: {fvc_pct:.0f}\n"
        if grade is not None:
            body += f"Grade: {grade}\n"
        body += f"\n- {doc_name}\n"

    else:  # detailed
        body = f"""PULMONARY FUNCTION TEST REPORT
SpiroHealth Laboratories Inc.
Report Date: {datetime.now().strftime('%B %d, %Y')}

PATIENT INFORMATION:
  MediVisit Evaluation ID: {eval_id}
  MemberPlan ID: {mp_id}
  Date of Service: {dos}

CLINICAL FINDINGS:

The patient underwent spirometry testing as part of a preventative health
evaluation. The following results were obtained:

"""
        if ratio is not None:
            body += f"1. FEV1/FVC Ratio: {ratio:.2f}\n"
            body += f"   {interpret_fev1_fvc_ratio(ratio)}\n\n"
        if fev1_pct is not None:
            body += f"2. FEV1 Percent of Predicted: {fev1_pct:.0f}%\n"
            body += f"   {interpret_fev1_pct(fev1_pct)}\n\n"
        if fvc_pct is not None:
            body += f"3. FVC Percent of Predicted: {fvc_pct:.0f}%\n\n"
        if grade is not None:
            body += f"4. Session Quality Assessment: Grade {grade}\n"
            body += f"   {interpret_session_grade(grade)}\n\n"

        if ratio is not None and ratio < 0.70:
            body += "RECOMMENDATION: Given the obstructive pattern observed, "
            body += "bronchodilator reversibility testing is recommended.\n\n"
        else:
            body += "RECOMMENDATION: Continue routine monitoring per clinical guidelines.\n\n"

        body += f"""Electronically signed by:
{doc_name}, {doc_title}
SpiroHealth Laboratories Inc.
Tel: (555) 234-5678 | Fax: (555) 234-5679
"""

    eml = f"""From: results@spirohealthlabs.com
To: vendor-intake@medivisit.com
Subject: Spirometry Results - Evaluation {eval_id}
Date: {dos}
Content-Type: text/plain; charset="utf-8"

{body}"""

    return eml


# ===========================================================================
# SPIROMETRY — PDF generator
# ===========================================================================

def generate_spiro_pdf(rec: dict, doctor: tuple, output_path: Path):
    doc_name, doc_title = doctor
    eval_id = rec["evaluation_id"]
    mp_id = rec["memberplan_id"]
    dos = rec["date_of_service"]
    ratio = rec["fev1_fvc_ratio"]
    fev1_pct = rec["fev1_pct_predicted"]
    fvc_pct = rec["fvc_pct_predicted"]
    grade = rec["session_grade"]

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "SpiroHealth Laboratories", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Pulmonary Function Test Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "PATIENT INFORMATION", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Evaluation ID: {eval_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"MemberPlan ID: {mp_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Date of Service: {dos}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "SPIROMETRY RESULTS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    if ratio is not None:
        pdf.cell(0, 6, f"FEV1/FVC Ratio: {ratio:.2f}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, f"  {interpret_fev1_fvc_ratio(ratio)}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.ln(2)

    if fev1_pct is not None:
        pdf.cell(0, 6, f"FEV1 (% Predicted): {fev1_pct:.0f}%", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, f"  {interpret_fev1_pct(fev1_pct)}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.ln(2)

    if fvc_pct is not None:
        pdf.cell(0, 6, f"FVC (% Predicted): {fvc_pct:.0f}%", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    if grade is not None:
        pdf.cell(0, 6, f"Session Quality Grade: {grade}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, f"  {interpret_session_grade(grade)}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.ln(4)

    pdf.ln(8)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Electronically signed by: {doc_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"{doc_title}, SpiroHealth Laboratories Inc.", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(output_path))


# ===========================================================================
# FOBT — CSV variations for realism
# ===========================================================================

FOBT_CSV_FORMATS = [
    {
        "name": "standard",
        "headers": ["evaluation_id", "member_id", "test_date", "fobt_result"],
        "result_map": {"Positive": "Positive", "Negative": "Negative"},
    },
    {
        "name": "abbreviated",
        "headers": ["eval_id", "mbr_plan_id", "dos", "result"],
        "result_map": {"Positive": "POS", "Negative": "NEG"},
    },
    {
        "name": "verbose",
        "headers": ["CaseNumber", "PatientPlanID", "ServiceDate", "OccultBloodScreenResult", "Interpretation"],
        "result_map": {"Positive": "DETECTED", "Negative": "NOT DETECTED"},
        "interpretation_map": {"Positive": "Abnormal - refer for colonoscopy", "Negative": "Normal - no follow-up needed"},
    },
]


# ===========================================================================
# Main generator
# ===========================================================================

def main():
    random.seed(42)

    OUTPUT_EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)

    # ----- SPIROMETRY (spirohealth_labs) -----
    spiro_evals = load_spirometry_evaluations()
    random.shuffle(spiro_evals)

    csv_cutoff = int(len(spiro_evals) * SPIRO_CSV_FRACTION)
    spiro_csv_evals = spiro_evals[:csv_cutoff]
    spiro_email_evals = spiro_evals[csv_cutoff:]

    # 95% as email + PDF
    for rec in spiro_email_evals:
        eval_id = rec["evaluation_id"]
        doctor = random.choice(SPIRO_DOCTORS)
        style = random.choice(EMAIL_STYLES)

        eml_content = generate_spiro_email(rec, doctor, style)
        (OUTPUT_EMAIL_DIR / f"spiro_eval_{eval_id}.eml").write_text(eml_content)

        generate_spiro_pdf(rec, doctor, OUTPUT_PDF_DIR / f"spiro_eval_{eval_id}.pdf")

    print(f"SPIROMETRY: {len(spiro_email_evals)} email+PDF reports generated")

    # 5% as SFTP CSV batch file
    spiro_csv_path = OUTPUT_CSV_DIR / "spirohealth_batch_results.csv"
    with open(spiro_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "eval_ref", "member_ref", "test_date",
            "fev1_fvc", "fev1_pct_pred", "fvc_pct_pred", "quality_grade",
        ])
        for rec in spiro_csv_evals:
            writer.writerow([
                rec["evaluation_id"],
                rec["memberplan_id"],
                rec["date_of_service"],
                rec["fev1_fvc_ratio"] if rec["fev1_fvc_ratio"] is not None else "",
                int(rec["fev1_pct_predicted"]) if rec["fev1_pct_predicted"] is not None else "",
                int(rec["fvc_pct_predicted"]) if rec["fvc_pct_predicted"] is not None else "",
                rec["session_grade"] if rec["session_grade"] is not None else "",
            ])
    print(f"SPIROMETRY: {len(spiro_csv_evals)} evals in SFTP CSV batch at {spiro_csv_path}")

    # ----- FOBT (quickscreen_labs) -----
    fobt_evals = load_fobt_evaluations()

    # Split FOBT into multiple CSV batch files with varied formats (realism)
    random.shuffle(fobt_evals)
    chunk_size = len(fobt_evals) // 3
    fobt_chunks = [
        ("fobt_batch_001.csv", fobt_evals[:chunk_size], FOBT_CSV_FORMATS[0]),
        ("fobt_batch_002.csv", fobt_evals[chunk_size:chunk_size*2], FOBT_CSV_FORMATS[1]),
        ("fobt_batch_003.csv", fobt_evals[chunk_size*2:], FOBT_CSV_FORMATS[2]),
    ]

    total_fobt = 0
    for filename, chunk, fmt in fobt_chunks:
        csv_path = OUTPUT_CSV_DIR / filename
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fmt["headers"])
            for rec in chunk:
                mapped_result = fmt["result_map"][rec["result"]]
                row_data = [
                    rec["evaluation_id"],
                    rec["memberplan_id"],
                    rec["date_of_service"],
                    mapped_result,
                ]
                if "interpretation_map" in fmt:
                    row_data.append(fmt["interpretation_map"][rec["result"]])
                writer.writerow(row_data)
        total_fobt += len(chunk)
        print(f"FOBT: {len(chunk)} results in {filename} (format: {fmt['name']})")

    print(f"\nFOBT total: {total_fobt} results across 3 CSV batch files")

    # ----- Summary -----
    print("\n" + "=" * 60)
    print("MOCK VENDOR DATA GENERATION COMPLETE")
    print("=" * 60)
    print(f"  spirohealth_labs (email+PDF): {len(spiro_email_evals)} reports")
    print(f"  spirohealth_labs (SFTP CSV):  {len(spiro_csv_evals)} evals in batch")
    print(f"  quickscreen_labs (SFTP CSV):  {total_fobt} FOBT results in 3 batches")
    print(f"  Total vendor files: {len(spiro_email_evals)*2 + 1 + 3}")
    print(f"    Emails: {OUTPUT_EMAIL_DIR}")
    print(f"    PDFs:   {OUTPUT_PDF_DIR}")
    print(f"    CSVs:   {OUTPUT_CSV_DIR}")


if __name__ == "__main__":
    main()
