"""
Layer 1: Deterministic File Readers

These readers extract raw text from vendor files. They do NOT interpret
the content — they just hand clean text to Layer 2 (LLM extraction).

Readers:
  read_email()  → extracts body text from .eml files
  read_pdf()    → extracts text from PDF files using pdfplumber
  read_csv()    → reads CSV rows and returns them as list of dicts
"""
import csv
import email
import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


def read_email(file_path: str | Path) -> str:
    """Extract plain text body from a .eml file."""
    file_path = Path(file_path)
    raw = file_path.read_text(encoding="utf-8")
    msg = email.message_from_string(raw)

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                break
    else:
        body = msg.get_payload(decode=False)
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")

    logger.info("Read email: %s (%d chars)", file_path.name, len(body))
    return body


def read_pdf(file_path: str | Path) -> str:
    """Extract text from all pages of a PDF file."""
    file_path = Path(file_path)
    pages_text = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    full_text = "\n".join(pages_text)
    logger.info("Read PDF: %s (%d pages, %d chars)", file_path.name, len(pages_text), len(full_text))
    return full_text


def read_csv_rows(file_path: str | Path) -> list[dict[str, str]]:
    """Read a CSV file and return rows as list of dicts.
    Each dict has the CSV column headers as keys."""
    file_path = Path(file_path)
    rows = []

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    logger.info("Read CSV: %s (%d rows, columns: %s)", file_path.name, len(rows),
                list(rows[0].keys()) if rows else [])
    return rows
