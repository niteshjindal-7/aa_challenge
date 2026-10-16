"""
Canonical schemas — the contract between extraction (PoC 1) and validation (PoC 2).
Every vendor result, regardless of source format, must be normalized into these shapes.
"""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class SpirometryResult(BaseModel):
    fev1_fvc_ratio: Optional[float] = Field(None, ge=0.20, le=1.00)
    fev1_pct_predicted: Optional[float] = Field(None, ge=10, le=200)
    fvc_pct_predicted: Optional[float] = Field(None, ge=10, le=200)
    session_grade: Optional[str] = Field(None, pattern="^[A-FU]$")


class CECGResult(BaseModel):
    findings: list[str] = Field(default_factory=list)
    severity: Optional[str] = Field(None, pattern="^(EMERGENT|TIME_SENSITIVE|NON_URGENT)$")


class FOBTResult(BaseModel):
    result: str = Field(pattern="^(Positive|Negative)$")


class HBA1CResult(BaseModel):
    hba1c_pct: float = Field(ge=3.0, le=20.0)


class UACRResult(BaseModel):
    uacr_mg_g: float = Field(ge=0.01, le=5000.0)
    is_below_30: bool = False


class COGResult(BaseModel):
    score: int = Field(ge=1, le=99)
    severity: Optional[str] = Field(None, pattern="^(Normal|Low|Borderline)$")


class ExtractedTestResult(BaseModel):
    """The canonical output of the extraction service.
    This is what the Vendor Integration Domain hands to the Test Result Domain."""
    vendor_id: str
    vendor_type: str = Field(pattern="^(email|sftp|rest)$")
    evaluation_id: int
    memberplan_id: int
    date_of_service: date
    product_code: str
    results: dict

    class ExtractionMetadata(BaseModel):
        model_used: str
        confidence: float = Field(ge=0.0, le=1.0)
        extracted_at: datetime
        raw_text_hash: str

    extraction_metadata: Optional[ExtractionMetadata] = None
