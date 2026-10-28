"""Generic business-rule checks against the deployed application (ADR-0002 §2, from the bdd-spec-driven-development checklist).

The engine knows the RULE; the project knows its SCREEN. A spec, one per screen in CHECKS["business_rules"], gives the callables
that touch the screen (each receives the run context, a page and a unique `tag` the project uses to build its own test data):

  {"id": "UNIDADES", "profile": "<stored test profile>",
   "uniqueness":  {"create": f(ctx, page, tag) -> (resp|None, toast), "cleanup": f(ctx, page, tag),
                   "duplicate_markers": ["ya existe", ...]},
   "immutability": {"open_edit": f(ctx, page, tag), "fields": ["css of an identifier field", ...], "close": f(page),
                    "create": f(...) optional, "cleanup": f(...) optional},
   "soft_delete": {"create": f, "delete": f(ctx, page, tag) -> (resp|None, toast), "listed": f(ctx, page, tag) -> bool,
                   "cleanup": f optional},
   "concurrency": {"create": f, "open_edit": f(ctx, page, tag), "set_and_save": f(page, value) -> (resp|None, toast),
                   "read_value": f(ctx, page, tag) -> str, "cleanup": f},
   "pagination":  {"url": "https://app/listado", "api_contains": "/api/listado", "api_method": "GET",
                   "total_json_path": "totalElements",            # a number, or a list (client-side paging: its length is the total)
                   "paginator_selector": ".p-paginator-current"}}

Only the rules a spec declares run (a screen where uniqueness does not apply simply does not declare it); a spec that declares none
yields one NOT_EXECUTED saying so. Every record a check creates carries the tag (cycle + random) and is
removed by `cleanup` after the check, whatever its verdict; a cleanup that fails is written in the detail, never hidden.
"""
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from centinela_core.results import Status

from smart_tests.checks import common
from smart_tests.session import LoginError, http_evidence

logger = logging.getLogger(__name__)

RULES = ("uniqueness", "immutability", "soft_delete", "concurrency", "pagination")
DEFAULT_DUPLICATE_MARKERS = ("ya existe", "existe", "duplic", "registrad", "already exists", "conflict")
CRITERIA = {
    "uniqueness": "Dar de alta dos veces el mismo registro: el segundo se rechaza con mensaje de duplicado (HTTP 409), no un error genérico",
    "immutability": "En edición, los campos identificadores están deshabilitados",
    "soft_delete": "Lo eliminado deja de aparecer en el listado",
    "concurrency": "Dos sesiones guardan el mismo registro: la segunda recibe conflicto (409) y no pisa a la primera",
    "pagination": "El total del paginador coincide con el total que devuelve la API",
}


def _cleanup(spec_rule: Dict[str, Any], ctx, page, tag: str) -> str:
    fn = spec_rule.get("cleanup")
    if not fn:
        return ""
    try:
        fn(ctx, page, tag)
        return ""
    except Exception as e:
        logger.error("limpieza fallida (%s)", tag, exc_info=True)
        return f" Limpieza fallida para «{tag}»: {str(e)[:150]} (borrar a mano)."


def _write_ok(resp) -> bool:
    return resp is not None and resp.status < 300


def _resp_text(resp) -> str:
    try:
        return (resp.text() or "")[:600] if resp is not None else ""
    except Exception:
        return ""


def uniqueness(ctx, sess, spec, cid, tag) -> common.CaseResult:
    r, page = spec["uniqueness"], sess.page
    ev, crit = [], CRITERIA["uniqueness"]
    resp1, toast1 = r["create"](ctx, page, tag)
    if not _write_ok(resp1):
        return common.blocked(cid, crit, f"no se pudo crear el registro base: {'sin petición' if resp1 is None else resp1.status} {toast1}")
    ev.append(http_evidence(resp1, "primera alta"))
    resp2, toast2 = r["create"](ctx, page, tag)
    if resp2 is not None:
        ev.append(http_evidence(resp2, "segunda alta con los mismos datos"))
    ev.append(sess.shot(f"br_{spec['id']}_unicidad", toast2 or "segunda alta"))
    markers = [m.lower() for m in (r.get("duplicate_markers") or DEFAULT_DUPLICATE_MARKERS)]
    said_dup = any(m in f"{toast2} {_resp_text(resp2)}".lower() for m in markers)
    if resp2 is None:
        status, detail, cat = Status.PASSED if said_dup else Status.FAILED, \
            f"La segunda alta no llegó al servidor; mensaje: «{toast2 or '—'}».", ""
        if not said_dup:
            detail += " El mensaje no indica que el registro ya existe."
    elif resp2.status < 300:
        status, detail, cat = Status.FAILED, f"La segunda alta con los mismos datos se ACEPTÓ (HTTP {resp2.status}): hay duplicado.", "data_integrity"
    elif resp2.status >= 500:
        status, detail, cat = Status.FAILED, (f"El duplicado se rechazó con un error genérico del servidor (HTTP {resp2.status}); "
                                              f"debería ser 409 con mensaje de duplicado. Mensaje: «{toast2 or '—'}»."), ""
    elif said_dup:
        status, detail, cat = Status.PASSED, f"Rechazado (HTTP {resp2.status}) con mensaje de duplicado: «{toast2 or '—'}».", ""
    else:
        status, detail, cat = Status.FAILED, (f"Rechazado (HTTP {resp2.status}) pero el mensaje no indica duplicado: «{toast2 or '—'}»."), ""
    return common.result(cid, status, crit, detail, ev, category=cat)


def immutability(ctx, sess, spec, cid, tag) -> common.CaseResult:
    r, page = spec["immutability"], sess.page
    crit = CRITERIA["immutability"]
    if r.get("create"):
        resp, toast = r["create"](ctx, page, tag)
        if not _write_ok(resp):
            return common.blocked(cid, crit, f"no se pudo crear el registro a editar: {'sin petición' if resp is None else resp.status} {toast}")
    r["open_edit"](ctx, page, tag)
    editable = []
    for sel in r["fields"]:
        loc = page.locator(sel).first
        if not loc.count():
            return common.blocked(cid, crit, f"el campo identificador «{sel}» no está en el formulario de edición")
        if loc.is_editable():
            editable.append(sel)
    ev = [sess.shot(f"br_{spec['id']}_inmutable", f"campos editables: {editable or 'ninguno'}")]
    if r.get("close"):
        r["close"](page)
    if editable:
        return common.result(cid, Status.FAILED, crit, f"Campos identificadores editables en la edición: {editable}.", ev, category="data_integrity",
                             severity="MEDIUM")
    return common.result(cid, Status.PASSED, crit, f"Los {len(r['fields'])} campo(s) identificador(es) están deshabilitados.", ev)


def soft_delete(ctx, sess, spec, cid, tag) -> common.CaseResult:
    r, page = spec["soft_delete"], sess.page
    crit = CRITERIA["soft_delete"]
    resp, toast = r["create"](ctx, page, tag)
    if not _write_ok(resp):
        return common.blocked(cid, crit, f"no se pudo crear el registro a eliminar: {'sin petición' if resp is None else resp.status} {toast}")
    if not r["listed"](ctx, page, tag):
        return common.blocked(cid, crit, "el registro recién creado no aparece en el listado: no se puede comprobar el borrado")
    dresp, dtoast = r["delete"](ctx, page, tag)
    ev = [http_evidence(dresp, "eliminación")] if dresp is not None else []
    if not _write_ok(dresp):
        return common.blocked(cid, crit, f"la eliminación no se completó: {'sin petición' if dresp is None else dresp.status} {dtoast}", ev)
    still = r["listed"](ctx, page, tag)
    ev.append(sess.shot(f"br_{spec['id']}_borrado", f"tras eliminar, sigue en el listado: {still}"))
    if still:
        return common.result(cid, Status.FAILED, crit, "Tras eliminarlo, el registro sigue apareciendo en el listado de activos.", ev,
                             category="data_integrity", severity="MEDIUM")
    return common.result(cid, Status.PASSED, crit, "Tras eliminarlo, el registro ya no aparece en el listado.", ev)


def concurrency(ctx, sess, spec, cid, tag) -> common.CaseResult:
    r = spec["concurrency"]
    crit = CRITERIA["concurrency"]
    page_a = sess.page
    # Second, independent browser session of the same profile (its own login): a new tab would not inherit a token kept in
    # sessionStorage (angular-oauth2-oidc's default), and two real users editing at once have two sessions anyway.
    from smart_tests.session import Session
    other = Session(ctx.browser, sess.profile, sess.evidence_dir, f"{sess.label}-2")
    other.login()
    page_b = other.page
    try:
        resp, toast = r["create"](ctx, page_a, tag)
        if not _write_ok(resp):
            return common.blocked(cid, crit, f"no se pudo crear el registro base: {'sin petición' if resp is None else resp.status} {toast}")
        r["open_edit"](ctx, page_a, tag)
        r["open_edit"](ctx, page_b, tag)
        va, vb = "A" + tag[-6:], "B" + tag[-6:]           # short: fits identifier-like fields (siglas, códigos cortos)
        ra, ta = r["set_and_save"](page_a, va)
        rb, tb = r["set_and_save"](page_b, vb)
        ev = [http_evidence(x, n) for x, n in ((ra, "guardado de la sesión A"), (rb, "guardado de la sesión B")) if x is not None]
        final = r["read_value"](ctx, page_a, tag)
        ev.append(sess.shot(f"br_{spec['id']}_concurrencia", f"valor final: {final}"))
        if not _write_ok(ra):
            return common.blocked(cid, crit, f"el primer guardado no se completó: {'sin petición' if ra is None else ra.status} {ta}", ev)
        if rb is not None and rb.status == 409 and final == va:
            return common.result(cid, Status.PASSED, crit, f"La segunda sesión recibió 409 y el valor de la primera se conservó ({va}).", ev)
        if rb is not None and rb.status < 300 and final == vb:
            return common.result(cid, Status.FAILED, crit, (f"La segunda sesión guardó sobre un registro desactualizado (HTTP {rb.status}) y pisó el "
                                                            f"valor de la primera: final «{final}». Falta control de versión (@Version / 409)."),
                                 ev, category="data_integrity", severity="MEDIUM")
        return common.result(cid, Status.FAILED, crit, (f"Resultado no esperado: segunda sesión {'sin petición' if rb is None else f'HTTP {rb.status}'} "
                                                        f"«{tb}»; valor final «{final}» (esperado 409 y «{va}»)."), ev)
    finally:
        other.close()


def pagination(ctx, sess, spec, cid, tag) -> common.CaseResult:
    r, page = spec["pagination"], sess.page
    crit = CRITERIA["pagination"]
    method = (r.get("api_method") or "GET").upper()
    with page.expect_response(lambda x: r["api_contains"] in x.url and x.request.method == method, timeout=30000) as ri:
        page.goto(r["url"], wait_until="domcontentloaded", timeout=45000)
    resp = ri.value
    page.wait_for_timeout(1500)
    try:
        val = common.json_path(json.loads(resp.text()), r["total_json_path"])
        api_total = len(val) if isinstance(val, list) else int(val)
    except Exception as e:
        return common.blocked(cid, crit, f"no se pudo leer el total de la API en «{r['total_json_path']}»: {str(e)[:150]}", [http_evidence(resp, "listado")])
    loc = page.locator(r.get("paginator_selector") or ".p-paginator-current").first
    if not loc.count():
        return common.blocked(cid, crit, "la pantalla no muestra el texto del paginador", [http_evidence(resp, "listado")])
    ptxt = loc.inner_text()
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", ptxt)]
    ui_total = nums[-1] if nums else None
    ev = [http_evidence(resp, f"total de la API: {api_total}"), sess.shot(f"br_{spec['id']}_paginacion", f"paginador: «{ptxt}»")]
    if ui_total == api_total:
        return common.result(cid, Status.PASSED, crit, f"Paginador «{ptxt}» = total de la API ({api_total}).", ev)
    return common.result(cid, Status.FAILED, crit, f"El paginador dice «{ptxt}» (total {ui_total}) y la API devolvió {api_total}.", ev)


CHECKS: Dict[str, Callable] = {"uniqueness": uniqueness, "immutability": immutability, "soft_delete": soft_delete,
                               "concurrency": concurrency, "pagination": pagination}


def run(ctx, specs: List[Dict[str, Any]]) -> List[common.CaseResult]:
    out = []
    for spec in specs:
        if not any(rule in spec for rule in RULES):
            out.append(common.not_executed(f"BR-{common.safe_id(spec['id'])}", "Reglas de negocio genéricas",
                                           f"el mapa de «{spec['id']}» no declara ninguna regla"))
            continue
        for rule in RULES:
            cid = f"BR-{rule.upper().replace('_', '-')}-{common.safe_id(spec['id'])}"
            if rule not in spec:
                continue
            try:
                sess = ctx.session(spec["profile"])
            except LoginError as e:
                out.append(common.blocked(cid, CRITERIA[rule], f"inicio de sesión: {e}"))
                continue
            tag = common.new_tag(ctx.cycle)
            try:
                res = CHECKS[rule](ctx, sess, spec, cid, tag)
            except Exception as e:
                logger.error("regla %s de %s interrumpida", rule, spec["id"], exc_info=True)
                res = common.blocked(cid, CRITERIA[rule], f"error durante la comprobación: {str(e)[:300]}")
            # Records created by the check (tagged) are removed here, whatever the verdict; a failed cleanup is written in the result.
            if rule != "pagination" and (rule != "immutability" or spec[rule].get("create")):
                warn = _cleanup(spec[rule], ctx, sess.page, tag)
                if warn:
                    res.detail = (res.detail or "") + warn
            out.append(res)
    return out
