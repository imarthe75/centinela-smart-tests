"""WCAG 2.1 A/AA with axe-core on screens BEHIND the login (decision 2 of ADR-0002: done here, so the authenticated session never
leaves this container; Centinela's own `wcag-render` only reaches public entry pages).

Spec per screen, in CHECKS["a11y"]:
  {"id": "UNIDADES", "profile": "<stored test profile>", "url": "https://app/unidades-admon"}   # or "open": f(ctx, page)

One case per screen and WCAG-failing axe rule: A11Y-<screen>-<RULE> FAILED with `meta.rule = WCAG-<criterion>-AXE-<RULE>` (the same
id Centinela's wcag-render uses), and one A11Y-<screen> PASSED when no A/AA rule fails. Read-only: navigation and DOM inspection.
A screen that did not render (little text/elements) is BLOCKED: an empty page passing axe is not evidence of accessibility.
"""
import logging
import re
from typing import Any, Dict, List

from centinela_core.results import Status

from smart_tests.checks import common
from smart_tests.session import LoginError

logger = logging.getLogger(__name__)

LEVEL_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
_IMPACT_SEVERITY = {"critical": "HIGH", "serious": "MEDIUM", "moderate": "LOW", "minor": "LOW"}
MIN_ELEMENTS = 50


def criterion(tags: List[str]) -> str:
    """axe tag 'wcag143' -> '1.4.3'; '' when the rule carries no success-criterion tag."""
    for t in tags or []:
        m = re.fullmatch(r"wcag(\d)(\d)(\d+)", t)
        if m:
            return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return ""


def violations_to_results(screen_id: str, violations: List[Dict[str, Any]], shot) -> List[common.CaseResult]:
    sid = common.safe_id(screen_id)
    out = []
    for v in violations:
        crit = criterion(v.get("tags", []))
        if not crit:
            continue
        nodes = v.get("nodes", [])
        sample = "; ".join(str((n.get("target") or ["?"])[-1]) for n in nodes[:5])
        rule = f"WCAG-{crit}-AXE-{v['id'].upper()}"
        out.append(common.result(
            f"A11Y-{sid}-{common.safe_id(v['id'])}", Status.FAILED, f"WCAG {crit}: {v.get('help', v['id'])}",
            f"{len(nodes)} elemento(s) incumplen «{v.get('help')}» en la pantalla autenticada, p. ej. {sample}. Referencia: {v.get('helpUrl')}",
            [shot, common.text(sample, f"axe-core, regla {v['id']}, impacto {v.get('impact')}")],
            category="accessibility", rule=rule, severity=_IMPACT_SEVERITY.get((v.get("impact") or "").lower(), "LOW")))
    return out


def check_screen(ctx, spec: Dict[str, Any]) -> List[common.CaseResult]:
    from axe_playwright_python.sync_playwright import Axe
    sid = common.safe_id(spec["id"])
    crit = "La pantalla autenticada cumple WCAG 2.1 A/AA verificable con axe-core"
    try:
        sess = ctx.session(spec["profile"])
    except LoginError as e:
        return [common.blocked(f"A11Y-{sid}", crit, f"inicio de sesión: {e}")]
    page = sess.page
    if spec.get("open"):
        spec["open"](ctx, page)
    else:
        page.goto(spec["url"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    elements = page.evaluate("() => document.querySelectorAll('*').length")
    shot = sess.shot(f"a11y_{spec['id']}", f"pantalla auditada con axe-core ({elements} elementos)")
    if elements < MIN_ELEMENTS:
        return [common.blocked(f"A11Y-{sid}", crit, f"la pantalla no terminó de renderizar ({elements} elementos)", [shot])]
    resp = Axe().run(page, options={"runOnly": {"type": "tag", "values": LEVEL_TAGS}}).response
    failed = violations_to_results(spec["id"], resp.get("violations", []), shot)
    if failed:
        return failed
    return [common.result(f"A11Y-{sid}", Status.PASSED, crit, f"0 reglas WCAG A/AA incumplidas ({len(resp.get('passes', []))} reglas aprobadas, "
                          f"{len(resp.get('incomplete', []))} requieren revisión humana).", [shot])]


def run(ctx, specs: List[Dict[str, Any]]) -> List[common.CaseResult]:
    out = []
    for s in specs:
        try:
            out += check_screen(ctx, s)
        except Exception as e:
            logger.error("auditoría de accesibilidad de %s interrumpida", s.get("id"), exc_info=True)
            out.append(common.blocked(f"A11Y-{common.safe_id(s.get('id', ''))}", "WCAG 2.1 A/AA", f"error durante la auditoría: {str(e)[:250]}"))
    return out
