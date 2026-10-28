"""Negative authorization per role (ADR-0002 §1): a profile WITHOUT a permission must not reach what the permission protects.

Spec (one per protected capability, declared by the project in CHECKS["authz_negative"]):
  {"id": "BANDEJA-AG",                        # becomes case AUTHZ-NEG-<id>
   "permission": "Administrador general",     # what is protected (text for the report)
   "denied_profile": "<stored test profile without that permission>",
   "screen_url": "https://app/ruta-protegida",        # optional: direct navigation must end denied
   "denied_markers": ["acceso denegado", ...],         # optional extra texts that mean "denied" on screen
   "action_screen_url": "https://app/ruta-que-si-ve",  # optional, with action_selector: the action must not be visible there
   "action_selector": "button:has-text('Eliminar')",
   "api": {"method": "GET", "url": "https://api/...", "body": null, "write_probe": false}}   # optional: must answer 401/403

Verdict per part: denied -> pass; reachable -> fail; anything that does not decide (404, 400 before the permission check, ...) ->
inconclusive. FAILED if any part fails; PASSED if at least one part passed and none failed; BLOCKED if nothing was conclusive.
Only an API that EXECUTES for the denied profile (2xx) is a security failure (access_control); a screen that opens while the API
denies is reported as a failed check without the security mark (the interface does not guard, the server does).
A non-read method is probed only with `write_probe: true` (a probe must not change data on a shared environment by accident).
"""
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

from centinela_core.results import Status

from smart_tests.checks import common
from smart_tests.session import LoginError

logger = logging.getLogger(__name__)

DEFAULT_DENIED_MARKERS = ("acceso denegado", "no autorizado", "sin permiso", "no tiene permiso", "forbidden", "403", "unauthorized",
                          "no cuenta con permisos")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def _screen_part(sess, spec, ev) -> Dict[str, str]:
    url = spec["screen_url"]
    page = sess.page
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    final = urlparse(page.url).path.rstrip("/")
    wanted = urlparse(url).path.rstrip("/")
    body = (page.inner_text("body") or "").lower()[:20000]
    markers = [m.lower() for m in (spec.get("denied_markers") or [])] + list(DEFAULT_DENIED_MARKERS)
    hit = next((m for m in markers if m in body), "")
    ev.append(sess.shot(f"authzneg_{spec['id']}_pantalla", f"navegación directa a {wanted}: terminó en {final or '/'}"))
    if final != wanted:
        return {"verdict": "pass", "note": f"la navegación directa a {wanted} terminó en {final or '/'} (redirigida)"}
    if hit:
        return {"verdict": "pass", "note": f"la pantalla muestra «{hit}»"}
    return {"verdict": "fail", "note": f"la ruta {wanted} se abrió sin redirección ni mensaje de acceso denegado"}


def _action_part(sess, spec, ev) -> Dict[str, str]:
    page = sess.page
    page.goto(spec["action_screen_url"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    loc = page.locator(spec["action_selector"])
    visible = sum(1 for i in range(min(loc.count(), 50)) if loc.nth(i).is_visible())
    ev.append(sess.shot(f"authzneg_{spec['id']}_accion", f"acción «{spec['action_selector']}»: {visible} visible(s)"))
    if visible:
        return {"verdict": "fail", "note": f"la acción protegida está visible ({visible} elemento(s))"}
    return {"verdict": "pass", "note": "la acción protegida no está visible"}


def _api_part(sess, spec, ev) -> Dict[str, str]:
    api = spec["api"]
    method = (api.get("method") or "GET").upper()
    if method not in READ_METHODS and not api.get("write_probe"):
        return {"verdict": "skip", "note": f"sonda {method} no ejecutada: requiere write_probe=true en el mapa del proyecto"}
    resp = sess.api(method, api["url"], api.get("body"))
    status = resp.status
    path = urlparse(api["url"]).path
    try:
        excerpt = (resp.text() or "")[:200]
    except Exception:
        excerpt = "(cuerpo no legible)"
    ev.append(common.Evidence("http", f"{method} {path} -> {status}",
                              f"como «{spec['denied_profile']}» ({'con' if sess.has_bearer else 'sin'} token de la app) {excerpt}"))
    if status in (401, 403):
        return {"verdict": "pass", "note": f"la API respondió {status}"}
    if 200 <= status < 300:
        return {"verdict": "fail_security", "note": f"la API ejecutó la operación para un perfil sin permiso (HTTP {status})"}
    return {"verdict": "inconclusive", "note": f"la API respondió {status}, que no decide si el permiso se evaluó"}


def check(ctx, spec: Dict[str, Any]) -> common.CaseResult:
    cid = f"AUTHZ-NEG-{common.safe_id(spec['id'])}"
    criterion = f"Un perfil sin el permiso «{spec.get('permission', spec['id'])}» no puede usarlo (interfaz y API)"
    try:
        sess = ctx.session(spec["denied_profile"])
    except LoginError as e:
        return common.blocked(cid, criterion, f"inicio de sesión del perfil sin permiso: {e}")
    ev: List = []
    parts: List[Dict[str, str]] = []
    if spec.get("screen_url"):
        parts.append(_screen_part(sess, spec, ev))
    if spec.get("action_selector") and spec.get("action_screen_url"):
        parts.append(_action_part(sess, spec, ev))
    if spec.get("api"):
        parts.append(_api_part(sess, spec, ev))
    if not parts:
        return common.not_executed(cid, criterion, "el mapa no declara pantalla, acción ni API para este permiso")
    detail = f"Perfil sin permiso: «{spec['denied_profile']}». " + "; ".join(p["note"] for p in parts) + "."
    verdicts = {p["verdict"] for p in parts}
    if "fail_security" in verdicts:
        return common.result(cid, Status.FAILED, criterion, detail, ev, category="access_control", severity="HIGH")
    if "fail" in verdicts:
        return common.result(cid, Status.FAILED, criterion, detail, ev)
    if "pass" in verdicts:
        return common.result(cid, Status.PASSED, criterion, detail, ev)
    return common.blocked(cid, criterion, "ninguna comprobación fue concluyente: " + "; ".join(p["note"] for p in parts), ev)


def run(ctx, specs: List[Dict[str, Any]]) -> List[common.CaseResult]:
    return [check(ctx, s) for s in specs]
