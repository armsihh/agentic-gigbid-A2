"""PII masking for logs, traces and audit records (R9 / E4). Never used to alter what is sent."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),                       # card-like digit runs
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[IBAN]"),
    (re.compile(r"\b\d{5}-\d{7}-\d\b"), "[NATIONAL_ID]"),                    # PK CNIC
    (re.compile(r"(?<![\w])\+?\d[\d\s().-]{7,}\d(?![\w])"), "[PHONE]"),
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password)\b(\s*[:=]\s*|\s+)\S+"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b0x[a-f0-9]{40}\b"), "[WALLET]"),
]


def mask_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def mask(obj: Any) -> Any:
    """Recursively mask strings inside dicts / lists. Keys named like secrets are fully redacted."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if re.search(r"(?i)token|secret|password|authorization", str(k)) else mask(v))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask(v) for v in obj]
    return obj
