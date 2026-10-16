"""
Canonical schemas — the contract between extraction (PoC 1) and validation (PoC 2).
Every vendor result, regardless of source format, must be normalized into these shapes.
"""
from datetime import date, datetime
from typing import Optional, Union
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Per-test-type result models
# ---------------------------------------------------------------------------

class SpirometryResult(BaseModel):
    model_config = {"extra": "forbid"}
    fev1_fvc_ratio: Optional[float] = Field(None, ge=0.20, le=1.00)
    fev1_pct_predicted: Optional[float] = Field(None, ge=10, le=200)
    fvc_pct_predicted: Optional[float] = Field(None, ge=10, le=200)
    session_grade: Optional[str] = Field(None, pattern="^[A-FU]$")


class CECGResult(BaseModel):
    model_config = {"extra": "forbid"}
    findings: list[str] = Field(default_factory=list)
    severity: Optional[str] = Field(None, pattern="^(EMERGENT|TIME_SENSITIVE|NON_URGENT)$")


class FOBTResult(BaseModel):
    model_config = {"extra": "forbid"}
    result: str = Field(pattern="^(Positive|Negative)$")


class HBA1CResult(BaseModel):
    model_config = {"extra": "forbid"}
    hba1c_pct: float = Field(ge=3.0, le=20.0)


class UACRResult(BaseModel):
    model_config = {"extra": "forbid"}
    uacr_mg_g: float = Field(ge=0.01, le=5000.0)
    is_below_30: bool = False


class COGResult(BaseModel):
    model_config = {"extra": "forbid"}
    score: int = Field(ge=1, le=99)
    severity: Optional[str] = Field(None, pattern="^(Normal|Low|Borderline)$")


# Map product_code → the Pydantic model that validates its results
PRODUCT_CODE_TO_SCHEMA: dict[str, type[BaseModel]] = {
    "SPIROMETRY": SpirometryResult,
    "CECG": CECGResult,
    "FOBT": FOBTResult,
    "HBA1CPOC": HBA1CResult,
    "UACR": UACRResult,
    "COG": COGResult,
}

# Union of all test result types for type hints
TestResultUnion = Union[
    SpirometryResult, CECGResult, FOBTResult,
    HBA1CResult, UACRResult, COGResult,
]


# ---------------------------------------------------------------------------
# Extraction metadata — top-level for easy standalone import
# ---------------------------------------------------------------------------

class ExtractionMetadata(BaseModel):
    model_used: str
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_at: datetime
    raw_text_hash: str


# ---------------------------------------------------------------------------
# Canonical extracted result — the envelope
# ---------------------------------------------------------------------------

class ExtractedTestResult(BaseModel):
    """The canonical output of the extraction service.
    This is what the Vendor Integration Domain hands to the Test Result Domain."""
    vendor_id: str
    vendor_type: str = Field(pattern="^(email|sftp|rest)$")
    evaluation_id: int
    memberplan_id: int
    date_of_service: date
    product_code: str
    results: TestResultUnion
    extraction_metadata: Optional[ExtractionMetadata] = None

    @model_validator(mode="before")
    @classmethod
    def validate_results_match_product_code(cls, data: dict) -> dict:
        """Ensure the results dict is validated against the correct
        test-type schema based on product_code."""
        if not isinstance(data, dict):
            return data

        product_code = data.get("product_code")
        results = data.get("results")

        if product_code and results and isinstance(results, dict):
            schema_cls = PRODUCT_CODE_TO_SCHEMA.get(product_code)
            if schema_cls is None:
                raise ValueError(f"Unknown product_code: '{product_code}'. "
                                 f"Valid codes: {list(PRODUCT_CODE_TO_SCHEMA.keys())}")
            data["results"] = schema_cls(**results)

        return data
