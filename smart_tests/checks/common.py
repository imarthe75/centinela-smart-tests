"""Shared pieces of the generic checks (ADR-0002): result building with honest states, unique tags for the records a check creates,
JSON-path reading and text evidence.

Category semantics (what Centinela does with a FAILED check):
  * SECURITY categories -> `security_relevant=True`, ingested as a SMART-TESTS-* security finding.
  * OBSERVATION categories (`usability`, `accessibility`) -> NOT security-relevant; ingested as an informational/WCAG finding under the
    static detector's own rule id (`meta.rule`), marked as observed at runtime.
"""
import logging
import secrets
from typing import Any, Dict, List, Optional

from centinela_core.results import CaseResult, Evidence, Status

logger = logging.getLogger(__name__)

SECURITY_CATEGORIES = {"access_control", "authentication", "session_management", "sensitive_data_exposure", "input_validation",
                       "data_integrity", "audit_logging"}
OBSERVATION_CATEGORIES = {"usability", "accessibility"}


def result(case_id: str, status: Status, criterion: str, detail: str = "", evidence: Optional[List[Evidence]] = None,
           reason: str = "", category: str = "", rule: str = "", severity: str = "", substitution: str = "") -> CaseResult:
    """Category/rule/severity are attached ONLY when the check FAILED, so a passing check is a clean PASSED (the result model forbids a
    security mark on anything but FAILED)."""
    if category and category not in SECURITY_CATEGORIES | OBSERVATION_CATEGORIES:
        raise ValueError(f"categoría desconocida: {category}")
    failed = status is Status.FAILED
    meta: Dict[str, Any] = {}
    if failed and category:
        meta["category"] = category
        if rule:
            meta["rule"] = rule
        if severity:
            meta["severity"] = severity
    return CaseResult(case_id, status, criterion=criterion, detail=detail, evidence=list(evidence or []), reason=reason,
                      substitution=substitution, security_relevant=failed and category in SECURITY_CATEGORIES, meta=meta)


def blocked(case_id: str, criterion: str, reason: str, evidence: Optional[List[Evidence]] = None) -> CaseResult:
    return CaseResult(case_id, Status.BLOCKED, criterion=criterion, reason=reason, evidence=list(evidence or []))


def not_executed(case_id: str, criterion: str, reason: str) -> CaseResult:
    return CaseResult(case_id, Status.NOT_EXECUTED, criterion=criterion, reason=reason)


def text(value: str, note: str = "") -> Evidence:
    return Evidence("text", (value or "")[:400], note[:400])


def new_tag(cycle: str) -> str:
    """Suffix for records a check creates: the cycle (so they never mix with the team's official run) plus 4 random hex chars."""
    return f"{cycle}{secrets.token_hex(2)}"


def json_path(obj: Any, path: str) -> Any:
    """'page.totalElements' / 'data.0.id'. Raises KeyError/IndexError/TypeError when the path does not exist."""
    cur = obj
    for part in (path or "").split("."):
        if part == "":
            continue
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (value or "").upper())[:60] or "SIN-ID"
