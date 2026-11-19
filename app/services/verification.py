"""Evidence consistency check (deterministic safety net against AI conversions, misreads and invented numbers).

The AI returns a value AND the exact source text it read it from. If the value does not appear in that text,
something happened in between - a silent unit conversion (F13: "INR 0.21 per gram" -> 210 per kg), a misread
digit, or a hallucination. We cannot tell which, so we never guess: the value is flagged for a human to verify.
"""
import re

from app.schemas import SupplierQuotation

_NUM = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")
CHECKED_FIELDS = ("unit_price",)   # the value that drives the decision; extend when evaluation shows the need


def numbers_in(text: str) -> list:
    return [float(n.replace(",", "")) for n in _NUM.findall(text or "")]


def _appears(value: float, text: str) -> bool:
    return any(abs(n - value) <= 1e-6 * max(1.0, abs(value)) for n in numbers_in(text))


def verify_quotation(q: SupplierQuotation) -> list:
    """Returns human-readable warnings, one per checked value that is not found in its own evidence quote."""
    warnings = []
    for f in CHECKED_FIELDS:
        value, ev = getattr(q, f), q.evidence.get(f)
        if value is None or ev is None or not ev.quote or not numbers_in(ev.quote):
            continue  # nothing to compare against (absence of evidence is handled elsewhere)
        if not _appears(float(value), ev.quote):
            unit = f" per {q.price_per}" if f == "unit_price" and q.price_per else ""
            warnings.append(f"{f}: extracted {value:g}{unit}, but the source text says \"{ev.quote}\" - "
                            "please verify the value and unit")
    return warnings
