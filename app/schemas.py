from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field, field_validator

Value = Union[float, bool, str, None]


def _norm_key(v: str) -> str:
    return v.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_date(v):
    if v in (None, "", "null"):
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date format: {s!r}")


# ---------- Evidence ----------
class Evidence(BaseModel):
    source_document: str = ""
    page: Optional[int] = None
    quote: Optional[str] = Field(None, description="Exact text copied from the document")
    confidence: float = Field(0.5, ge=0, le=1)

    @field_validator("page", mode="before")
    @classmethod
    def _page(cls, v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None          # e.g. "1-2" or "n/a": keep the quote, drop the page

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        if v is None:
            return 0.5
        v = float(v)
        return v / 100 if 1 < v <= 100 else v   # LLM sometimes answers 95 instead of 0.95


def _clean_evidence_map(v):
    """LLMs often return {"unit_price": null} for fields that are absent. Absent value =
    no evidence, which is not an error - drop those entries instead of failing validation."""
    if not isinstance(v, dict):
        return {}
    return {k: e for k, e in v.items() if isinstance(e, (dict, Evidence)) and e}


# ---------- RFQ (buyer side) ----------
class TechRequirement(BaseModel):
    name: str
    operator: Literal[">=", "<=", ">", "<", "==", "present"] = ">="
    value: Value = None
    unit: Optional[str] = None
    mandatory: bool = True
    evidence: Optional[Evidence] = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _norm_key(v)


class RFQRequirements(BaseModel):
    rfq_id: str = ""
    product_name: Optional[str] = None
    required_quantity: Optional[float] = None
    unit: Optional[str] = None
    technical_requirements: list[TechRequirement] = []
    required_certificates: list[str] = []
    max_delivery_days: Optional[int] = None
    payment_terms: Optional[str] = None
    currency: Optional[str] = None
    tax_basis: Optional[str] = None
    evidence: dict[str, Evidence] = {}

    @field_validator("evidence", mode="before")
    @classmethod
    def _ev(cls, v):
        return _clean_evidence_map(v)

    @field_validator("technical_requirements", "required_certificates", mode="before")
    @classmethod
    def _lists(cls, v):
        return [] if v is None else v

    def missing_core_fields(self) -> list[str]:
        return [f for f in ("product_name", "required_quantity", "unit")
                if getattr(self, f) in (None, "")]


# ---------- Supplier quotation ----------
class OfferedSpec(BaseModel):
    name: str
    value: Value = None
    unit: Optional[str] = None
    evidence: Optional[Evidence] = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _norm_key(v)


class SupplierQuotation(BaseModel):
    supplier_name: str
    source_document: str = ""
    quotation_number: Optional[str] = None
    quotation_date: Optional[date] = None
    valid_until: Optional[date] = None
    product_name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    price_per: Optional[str] = Field(None, description="Unit the price refers to: kg, g, MT...")
    currency: Optional[str] = None
    tax_status: Literal["inclusive", "exclusive", "unknown"] = "unknown"
    tax_rate_percent: Optional[float] = None
    freight_cost: Optional[float] = None
    delivery_days: Optional[int] = None
    payment_terms: Optional[str] = None
    specifications: list[OfferedSpec] = []
    certificates: list[str] = []
    exclusions: list[str] = []
    conflicts: list[str] = Field([], description="Contradictions found inside the document")
    verification_warnings: list[str] = Field([], description="Values that do not match their own source text")
    evidence: dict[str, Evidence] = {}
    extraction_status: Literal["extracted", "validated", "review_required", "failed"] = "extracted"

    @field_validator("quotation_date", "valid_until", mode="before")
    @classmethod
    def _d(cls, v):
        return _parse_date(v)

    @field_validator("evidence", mode="before")
    @classmethod
    def _ev(cls, v):
        return _clean_evidence_map(v)

    @field_validator("certificates", "exclusions", "conflicts", "specifications", "verification_warnings",
                     mode="before")
    @classmethod
    def _lists(cls, v):
        return [] if v is None else v

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        return v.strip().upper() if v else v


# ---------- Evaluation ----------
class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RequirementCheck(BaseModel):
    requirement: str
    required: str
    offered: str
    status: CheckStatus
    mandatory: bool
    reason: str


class Finding(BaseModel):
    supplier_name: Optional[str] = None
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    category: str
    message: str


class SupplierEvaluation(BaseModel):
    supplier_name: str
    checks: list[RequirementCheck] = []
    normalized_unit_price: Optional[float] = None   # RFQ currency per RFQ unit, excl. tax
    total_cost: Optional[float] = None
    commercially_comparable: bool = True
    price_notes: list[str] = []
    findings: list[Finding] = []

    @computed_field
    @property
    def mandatory_failures(self) -> int:
        return sum(c.mandatory and c.status == CheckStatus.FAIL for c in self.checks)

    @computed_field
    @property
    def unknowns(self) -> int:
        return sum(c.status in (CheckStatus.UNKNOWN, CheckStatus.REVIEW_REQUIRED) for c in self.checks)

    @computed_field
    @property
    def overall_status(self) -> str:
        if self.mandatory_failures:
            return "NOT_COMPLIANT"
        open_mandatory = any(c.mandatory and c.status not in (CheckStatus.PASS, CheckStatus.NOT_APPLICABLE)
                             for c in self.checks)
        if open_mandatory or not self.commercially_comparable:
            return "NEEDS_CLARIFICATION"
        return "COMPLIANT"

    @computed_field
    @property
    def risk_level(self) -> str:
        if self.mandatory_failures or any(f.severity == "HIGH" for f in self.findings):
            return "HIGH"
        if self.unknowns or any(f.severity == "MEDIUM" for f in self.findings):
            return "MEDIUM"
        return "LOW"


class WorkflowStatus(str, Enum):
    CREATED = "CREATED"
    DOCUMENTS_UPLOADED = "DOCUMENTS_UPLOADED"
    EXTRACTING = "EXTRACTING"
    EXTRACTION_REVIEW_REQUIRED = "EXTRACTION_REVIEW_REQUIRED"
    EVALUATING = "EVALUATING"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REPORT_GENERATED = "REPORT_GENERATED"
    FAILED = "FAILED"
