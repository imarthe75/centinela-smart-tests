"""Generic checks run against the deployed application, on top of the package's own cases (ADR-0002).

A project declares what each check needs in `CHECKS = {"authz_negative": [...], "business_rules": [...], "heuristics": [...],
"a11y": [...]}` (see each module's docstring). The run selects them explicitly with `args["checks"]`; nothing runs by default,
because business rules and heuristics create (tagged, cleaned-up) records in the environment.
A requested check the project does not declare yields one NOT_EXECUTED result saying so — never a silent omission.
"""
import importlib
import logging
from typing import Any, Dict, List

from smart_tests.checks import common

logger = logging.getLogger(__name__)

KINDS = ("authz_negative", "business_rules", "heuristics", "a11y")


def run(ctx, kinds: List[str]) -> List[common.CaseResult]:
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        raise SystemExit(f"comprobaciones desconocidas: {unknown}; disponibles: {list(KINDS)}")
    declared: Dict[str, List[Dict[str, Any]]] = getattr(ctx.project, "CHECKS", {}) if ctx.project else {}
    out: List[common.CaseResult] = []
    for kind in kinds:
        specs = declared.get(kind) or []
        if not specs:
            out.append(common.not_executed(f"CHECK-{kind.upper().replace('_', '-')}", f"Comprobación genérica «{kind}»",
                                           "el proyecto no declara esta comprobación en su mapa (CHECKS)"))
            continue
        module = importlib.import_module(f"smart_tests.checks.{kind}")
        logger.info("comprobación %s: %d especificación(es)", kind, len(specs))
        out += module.run(ctx, specs)
    return out
