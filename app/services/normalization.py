"""Units, currencies, tax basis. Deterministic. Original values are never modified."""
from dataclasses import dataclass, field
from typing import Optional

from app.schemas import RFQRequirements, SupplierQuotation

_UNITS = {
    "mg": ("mass", 1e-6), "g": ("mass", 1e-3), "gm": ("mass", 1e-3), "gram": ("mass", 1e-3),
    "grams": ("mass", 1e-3), "kg": ("mass", 1.0), "kgs": ("mass", 1.0), "kilogram": ("mass", 1.0),
    "kilograms": ("mass", 1.0), "mt": ("mass", 1000.0), "tonne": ("mass", 1000.0),
    "tonnes": ("mass", 1000.0), "ton": ("mass", 1000.0), "tons": ("mass", 1000.0), "t": ("mass", 1000.0),
    "quintal": ("mass", 100.0), "lb": ("mass", 0.453592), "lbs": ("mass", 0.453592),
    "ml": ("volume", 1e-3), "l": ("volume", 1.0), "ltr": ("volume", 1.0), "litre": ("volume", 1.0),
    "liter": ("volume", 1.0), "litres": ("volume", 1.0), "liters": ("volume", 1.0), "kl": ("volume", 1000.0),
    "%": ("percent", 1.0), "percent": ("percent", 1.0), "ppm": ("ppm", 1.0),
    "micron": ("length", 1e-6), "microns": ("length", 1e-6), "um": ("length", 1e-6),
    "µm": ("length", 1e-6), "mm": ("length", 1e-3),
}
_CURRENCIES = {"rs": "INR", "rs.": "INR", "inr": "INR", "₹": "INR", "rupees": "INR", "rupee": "INR",
               "usd": "USD", "$": "USD", "us$": "USD", "eur": "EUR", "€": "EUR", "euro": "EUR"}


def _key(u) -> str:
    return str(u).strip().lower().rstrip(".") if u else ""


def same_unit(a, b) -> bool:
    if _key(a) == _key(b):
        return True
    ia, ib = _UNITS.get(_key(a)), _UNITS.get(_key(b))
    return bool(ia and ib and ia == ib)


def convert(value, from_unit, to_unit) -> Optional[float]:
    """Convert between compatible units; None if incompatible or unknown."""
    if value is None:
        return None
    if same_unit(from_unit, to_unit):
        return float(value)
    a, b = _UNITS.get(_key(from_unit)), _UNITS.get(_key(to_unit))
    if not a or not b or a[0] != b[0]:
        return None
    return float(value) * a[1] / b[1]


def normalize_currency(c) -> Optional[str]:
    if not c:
        return None
    return _CURRENCIES.get(_key(c), str(c).strip().upper())


@dataclass
class NormalizedPrice:
    unit_price: Optional[float]   # RFQ currency, per RFQ unit, excluding tax
    total_cost: Optional[float]
    comparable: bool
    notes: list = field(default_factory=list)    # how the number was derived
    issues: list = field(default_factory=list)   # why it is not comparable


def normalize_price(q: SupplierQuotation, rfq: RFQRequirements,
                    exchange_rates: Optional[dict] = None) -> NormalizedPrice:
    """exchange_rates: {"USD": (83.2, "RBI reference rate 2026-11-18")} - only explicit, sourced rates."""
    notes, issues = [], []
    if q.unit_price is None:
        return NormalizedPrice(None, None, False, notes, ["Unit price not stated"])
    price, blocked = float(q.unit_price), False

    src = normalize_currency(q.currency)
    target = normalize_currency(rfq.currency) or src
    if src is None:
        issues.append("Currency not stated")
    elif src != target:
        rate = (exchange_rates or {}).get(src)
        if rate is None:
            issues.append(f"Quoted in {src}, RFQ asks for {target}; no approved exchange rate provided")
            blocked = True
        else:
            price *= rate[0]
            notes.append(f"Converted {src}->{target} at {rate[0]} ({rate[1]})")

    per = q.price_per or q.unit
    if rfq.unit and per and not same_unit(rfq.unit, per):
        factor = convert(1, rfq.unit, per)
        if factor is None:
            issues.append(f"Price is per '{per}' but RFQ unit is '{rfq.unit}' - not convertible")
            blocked = True
        else:
            price *= factor
            notes.append(f"Price per {per} x {factor:g} = price per {rfq.unit}")

    if q.tax_status == "inclusive":
        if q.tax_rate_percent is not None:
            price /= 1 + q.tax_rate_percent / 100
            notes.append(f"Removed {q.tax_rate_percent:g}% tax from tax-inclusive price")
        else:
            issues.append("Price includes tax but the tax rate is not stated")
    elif q.tax_status == "unknown":
        issues.append("Tax treatment (GST inclusive/exclusive) not stated")

    if blocked:
        return NormalizedPrice(None, None, False, notes, issues)
    total = None
    if rfq.required_quantity:
        total = price * rfq.required_quantity + (q.freight_cost or 0)
        if q.freight_cost:
            notes.append(f"Added separately charged freight {q.freight_cost:g}")
    return NormalizedPrice(round(price, 4), round(total, 2) if total is not None else None,
                           not issues, notes, issues)
