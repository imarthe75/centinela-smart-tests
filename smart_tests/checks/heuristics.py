"""Usability heuristics observed on the running screen (ADR-0002 §3, from frontend-heuristicas-usabilidad), with network evidence.

Spec per screen, in CHECKS["heuristics"]:
  {"id": "UNIDADES-ALTA", "profile": "<stored test profile>",
   "write_url_contains": "/api/unidades",                    # what counts as a write request of this screen
   "submit": {"open_form": f(ctx, page, tag),                # leaves a VALID form open, ready to save
              "save_selector": "button:has-text('Guardar')",
              "cleanup": f(ctx, page, tag)},
   "invalid": {"open_form": f(ctx, page),                    # leaves the form with a required field empty
               "save_selector": "...", "field_error_selector": "app-error-input, small.p-error, .p-invalid", "close": f(page)},
   "delete": {"prepare": f(ctx, page, tag),                  # creates a record and leaves its row on screen
              "delete_selector": "css of the delete action of that row" | f(tag) -> css, "cleanup": f(ctx, page, tag)}}

Cases (HEUR-<rule>-<screen>):
  * DOUBLE-SUBMIT  double click on Save -> exactly one write request (rule ANGULAR-SUBMIT-NO-BUSY-GUARD).
  * BUSY-STATE     while the write is in flight the Save button is disabled or shows loading. The write is held in the browser
                   until the button state was read, then continues to the REAL server (latency only; the response is the real one) so the state is visible.
  * FIELD-ERROR    saving an invalid form shows a message per field or keeps Save disabled, and sends nothing.
  * DELETE-CONFIRM deleting asks for confirmation before any write (rule DESTRUCTIVE-ACTION-NO-CONFIRM); the confirmation is
                   then cancelled and the record must still be there.
  * NATIVE-DIALOG  no alert()/confirm()/prompt() during any of the flows above (rule NATIVE-BROWSER-DIALOG).
  * ERROR-TRACE    no stack trace in any server error response or on screen during the flows (rule STACK-TRACE-EXPOSURE, a
                   security finding: sensitive_data_exposure).
"""
import logging
import re
from typing import Any, Dict, List

from centinela_core.results import Status

from smart_tests.checks import common
from smart_tests.session import LoginError

logger = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
TRACE_RE = re.compile(r"(\bat [\w$.]+\([\w$]+\.java:\d+\)|Traceback \(most recent call last\)|\bjava\.lang\.\w+(Exception|Error)\b|"
                      r"org\.springframework\.[\w.]+Exception|SQLSTATE\[|\bException in thread\b|\.java:\d+\))")
CONFIRM_SEL = ".p-confirm-dialog:visible, .p-confirmdialog:visible, [role=alertdialog]:visible, .p-dialog:visible"
CRITERIA = {
    "DOUBLE-SUBMIT": "Doble clic en Guardar envía una sola petición de escritura",
    "BUSY-STATE": "Mientras la petición está en curso, Guardar está deshabilitado o muestra carga",
    "FIELD-ERROR": "Un formulario inválido muestra el error por campo (o no deja guardar) y no envía nada",
    "DELETE-CONFIRM": "Eliminar pide confirmación antes de escribir y cancelar no elimina",
    "NATIVE-DIALOG": "Sin diálogos nativos del navegador (alert/confirm/prompt)",
    "ERROR-TRACE": "Los errores del servidor no exponen trazas internas",
}
RULES = {"DOUBLE-SUBMIT": "ANGULAR-SUBMIT-NO-BUSY-GUARD", "BUSY-STATE": "ANGULAR-SUBMIT-NO-BUSY-GUARD",
         "DELETE-CONFIRM": "DESTRUCTIVE-ACTION-NO-CONFIRM", "NATIVE-DIALOG": "NATIVE-BROWSER-DIALOG"}


class _Observer:
    """Records write requests, server errors and native dialogs on a page while flows run."""

    def __init__(self, page, write_url: str):
        self.page, self.write_url = page, write_url
        self.writes: List[str] = []
        self.write_statuses: List[int] = []
        self.dialogs: List[str] = []
        self.error_traces: List[str] = []
        self.server_errors = 0
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("dialog", self._on_dialog)

    def detach(self):
        for ev, fn in (("request", self._on_request), ("response", self._on_response), ("dialog", self._on_dialog)):
            try:
                self.page.remove_listener(ev, fn)
            except Exception:
                logger.error("no se pudo quitar el listener %s", ev, exc_info=True)

    def _on_request(self, req):
        if req.method in WRITE_METHODS and self.write_url in req.url:
            self.writes.append(f"{req.method} {req.url.split('?')[0]}")

    def _on_response(self, resp):
        if resp.request.method in WRITE_METHODS and self.write_url in resp.url:
            self.write_statuses.append(resp.status)
        if resp.status < 500:
            return
        self.server_errors += 1
        try:
            body = resp.text() or ""
        except Exception:
            body = ""
        m = TRACE_RE.search(body)
        if m:
            self.error_traces.append(f"{resp.request.method} {resp.url.split('?')[0]} -> {resp.status}: «{m.group(0)[:120]}»")

    def _on_dialog(self, dialog):
        self.dialogs.append(f"{dialog.type}: «{(dialog.message or '')[:120]}»")
        try:
            dialog.dismiss()          # dismiss = cancel: a native confirm never authorises a destructive action during the check
        except Exception:
            logger.error("no se pudo cerrar el diálogo nativo", exc_info=True)


def _busy(btn) -> bool:
    try:
        if btn.is_disabled():
            return True
        cls = (btn.get_attribute("class") or "") + " " + (btn.get_attribute("aria-busy") or "")
        return "loading" in cls or "true" in cls or btn.locator(".p-button-loading-icon, .pi-spin").count() > 0
    except Exception:
        return False


def _submit(ctx, sess, spec, obs, tag) -> List[common.CaseResult]:
    s, page, sid = spec["submit"], sess.page, common.safe_id(spec["id"])
    c_dbl, c_busy = f"HEUR-DOUBLE-SUBMIT-{sid}", f"HEUR-BUSY-STATE-{sid}"
    s["open_form"](ctx, page, tag)
    btn = page.locator(s["save_selector"]).first
    if not btn.count():
        r = f"el botón «{s['save_selector']}» no está en el formulario"
        return [common.blocked(c_dbl, CRITERIA["DOUBLE-SUBMIT"], r), common.blocked(c_busy, CRITERIA["BUSY-STATE"], r)]

    held: List = []

    def hold(route):
        # Keep the write pending (no sleep: a blocking handler would freeze Playwright's own loop); released below, after the state
        # of the button was observed. Latency only — the request then goes to the real server and the response is the real one.
        if route.request.method in WRITE_METHODS:
            held.append(route)
        else:
            route.continue_()

    pattern = re.compile(re.escape(spec["write_url_contains"]))
    page.route(pattern, hold)
    before, before_st = len(obs.writes), len(obs.write_statuses)
    try:
        btn.dblclick()
        page.wait_for_timeout(500)
        busy = _busy(btn)
        shot = sess.shot(f"heur_{spec['id']}_ocupado", f"botón durante la petición: {'ocupado' if busy else 'disponible'}")
        try:
            btn.click(timeout=800, force=True)        # a third click while in flight
        except Exception as e:                        # expected when the button is disabled: that is the behaviour being checked
            logger.info("tercer clic no aceptado mientras la petición estaba en curso: %s", str(e)[:120])
        page.wait_for_timeout(500)
    finally:
        for r in held:
            try:
                r.continue_()
            except Exception:
                logger.error("no se pudo liberar una petición retenida", exc_info=True)
        page.wait_for_timeout(3000)
        page.unroute(pattern, hold)
    writes = obs.writes[before:]
    statuses = obs.write_statuses[before_st:]
    accepted = sum(1 for s_ in statuses if s_ < 300)
    ev = [common.text("; ".join(writes) or "ninguna", f"peticiones de escritura tras doble clic + clic adicional: {len(writes)}; "
                                                       f"respuestas: {statuses or 'ninguna'}"), shot]
    if not writes:
        r = "el guardado no envió ninguna petición de escritura (formulario inválido o URL de escritura mal declarada)"
        return [common.blocked(c_dbl, CRITERIA["DOUBLE-SUBMIT"], r, ev), common.blocked(c_busy, CRITERIA["BUSY-STATE"], r, ev)]
    out = []
    if len(writes) == 1:
        out.append(common.result(c_dbl, Status.PASSED, CRITERIA["DOUBLE-SUBMIT"], "Una sola petición de escritura.", ev))
    elif accepted > 1:
        # The server ACCEPTED more than one: concurrent requests got past its duplicate check (check-then-insert without a unique
        # constraint). That is a data-integrity failure, not just a usability one.
        out.append(common.result(c_dbl, Status.FAILED, CRITERIA["DOUBLE-SUBMIT"],
                                 f"{len(writes)} peticiones por un solo guardado y el servidor ACEPTÓ {accepted} (respuestas {statuses}): se crearon "
                                 "registros duplicados. Las peticiones simultáneas pasan la validación de duplicado (falta restricción única en la "
                                 "base de datos) y el botón no se bloquea.", ev, category="data_integrity", severity="MEDIUM"))
    else:
        out.append(common.result(c_dbl, Status.FAILED, CRITERIA["DOUBLE-SUBMIT"], f"{len(writes)} peticiones de escritura por un solo guardado "
                                 f"(respuestas {statuses}); el servidor rechazó las repetidas.", ev, category="usability",
                                 rule=RULES["DOUBLE-SUBMIT"], severity="LOW"))
    note = "(la petición se retuvo en el navegador hasta leer el estado del botón y después siguió al servidor real)"
    if busy:
        out.append(common.result(c_busy, Status.PASSED, CRITERIA["BUSY-STATE"], f"Guardar se deshabilitó o mostró carga {note}.", ev))
    else:
        out.append(common.result(c_busy, Status.FAILED, CRITERIA["BUSY-STATE"], f"Guardar siguió disponible sin indicador de carga {note}.", ev,
                                 category="usability", rule=RULES["BUSY-STATE"], severity="LOW"))
    return out


def _invalid(ctx, sess, spec, obs) -> common.CaseResult:
    s, page = spec["invalid"], sess.page
    cid = f"HEUR-FIELD-ERROR-{common.safe_id(spec['id'])}"
    s["open_form"](ctx, page)
    btn = page.locator(s["save_selector"]).first
    if not btn.count():
        return common.blocked(cid, CRITERIA["FIELD-ERROR"], f"el botón «{s['save_selector']}» no está en el formulario")
    before = len(obs.writes)
    disabled = btn.is_disabled()
    if not disabled:
        btn.click()
        page.wait_for_timeout(2000)
    errs = page.locator(s.get("field_error_selector") or "app-error-input, small.p-error, .p-invalid, .ng-invalid.ng-touched")
    shown = sum(1 for i in range(min(errs.count(), 30)) if errs.nth(i).is_visible())
    sent = obs.writes[before:]
    ev = [sess.shot(f"heur_{spec['id']}_invalido", f"Guardar {'deshabilitado' if disabled else 'habilitado'}; mensajes por campo: {shown}"),
          common.text("; ".join(sent) or "ninguna", "peticiones de escritura enviadas con el formulario inválido")]
    if s.get("close"):
        s["close"](page)
    if sent:
        return common.result(cid, Status.FAILED, CRITERIA["FIELD-ERROR"], f"El formulario inválido se envió al servidor ({len(sent)} petición(es)).",
                             ev, category="usability", rule="SMART-TESTS-FORM-INVALID-SUBMITTED", severity="LOW")
    if disabled or shown:
        return common.result(cid, Status.PASSED, CRITERIA["FIELD-ERROR"],
                             f"Guardar {'deshabilitado' if disabled else 'bloqueado'}; {shown} mensaje(s) por campo visibles.", ev)
    return common.result(cid, Status.FAILED, CRITERIA["FIELD-ERROR"], "No se envió nada, pero tampoco se mostró ningún mensaje por campo.", ev,
                         category="usability", rule="SMART-TESTS-FORM-NO-FIELD-ERROR", severity="LOW")


def _delete(ctx, sess, spec, obs, tag) -> common.CaseResult:
    d, page = spec["delete"], sess.page
    cid = f"HEUR-DELETE-CONFIRM-{common.safe_id(spec['id'])}"
    d["prepare"](ctx, page, tag)
    sel = d["delete_selector"](tag) if callable(d["delete_selector"]) else d["delete_selector"]
    target = page.locator(sel).first
    if not target.count():
        return common.blocked(cid, CRITERIA["DELETE-CONFIRM"], f"la acción de eliminar «{sel}» no está en pantalla")
    before_w, before_d = len(obs.writes), len(obs.dialogs)
    target.click()
    page.wait_for_timeout(1500)
    confirm = page.locator(CONFIRM_SEL)
    asked = confirm.count() > 0 or len(obs.dialogs) > before_d
    ev = [sess.shot(f"heur_{spec['id']}_eliminar", f"confirmación {'mostrada' if asked else 'NO mostrada'}")]
    if confirm.count():
        dlg = confirm.last
        for sel in ("button:has-text('No')", "button:has-text('Cancelar')", "[data-pc-section=closebutton]", ".p-confirm-dialog-reject"):
            b = dlg.locator(sel)
            if b.count():
                b.first.click()
                break
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1500)
    writes = obs.writes[before_w:]
    ev.append(common.text("; ".join(writes) or "ninguna", "peticiones de escritura tras pulsar eliminar (y cancelar)"))
    if writes:
        return common.result(cid, Status.FAILED, CRITERIA["DELETE-CONFIRM"],
                             f"Se envió la eliminación {'sin pedir confirmación' if not asked else 'aunque se canceló la confirmación'}: {writes}.",
                             ev, category="usability", rule=RULES["DELETE-CONFIRM"], severity="MEDIUM")
    if not asked:
        return common.blocked(cid, CRITERIA["DELETE-CONFIRM"], "pulsar eliminar no mostró confirmación ni envió nada (selector de la acción incorrecto)", ev)
    return common.result(cid, Status.PASSED, CRITERIA["DELETE-CONFIRM"], "Pidió confirmación y, al cancelar, no se envió nada.", ev)


def check_screen(ctx, spec: Dict[str, Any]) -> List[common.CaseResult]:
    sid = common.safe_id(spec["id"])
    try:
        sess = ctx.session(spec["profile"])
    except LoginError as e:
        return [common.blocked(f"HEUR-{k}-{sid}", c, f"inicio de sesión: {e}") for k, c in CRITERIA.items()]
    obs = _Observer(sess.page, spec["write_url_contains"])
    out: List[common.CaseResult] = []
    flows = []
    try:
        for key, label in (("submit", "guardar"), ("invalid", "formulario inválido"), ("delete", "eliminar")):
            if key not in spec:
                names = ["DOUBLE-SUBMIT", "BUSY-STATE"] if key == "submit" else (["FIELD-ERROR"] if key == "invalid" else ["DELETE-CONFIRM"])
                out += [common.not_executed(f"HEUR-{n}-{sid}", CRITERIA[n], f"el mapa de «{spec['id']}» no declara el flujo «{label}»") for n in names]
                continue
            tag = common.new_tag(ctx.cycle)
            try:
                if key == "submit":
                    out += _submit(ctx, sess, spec, obs, tag)
                elif key == "invalid":
                    out.append(_invalid(ctx, sess, spec, obs))
                else:
                    out.append(_delete(ctx, sess, spec, obs, tag))
                flows.append(label)
            except Exception as e:
                logger.error("flujo %s de %s interrumpido", key, spec["id"], exc_info=True)
                names = ["DOUBLE-SUBMIT", "BUSY-STATE"] if key == "submit" else (["FIELD-ERROR"] if key == "invalid" else ["DELETE-CONFIRM"])
                out += [common.blocked(f"HEUR-{n}-{sid}", CRITERIA[n], f"error durante el flujo: {str(e)[:250]}") for n in names]
            finally:
                fn = spec[key].get("cleanup")
                if fn:
                    try:
                        fn(ctx, sess.page, tag)
                    except Exception as e:
                        logger.error("limpieza del flujo %s fallida", key, exc_info=True)
                        if out:
                            out[-1].detail = (out[-1].detail or "") + f" Limpieza fallida para «{tag}»: {str(e)[:150]} (borrar a mano)."
        page_text = ""
        try:
            page_text = sess.page.inner_text("body")[:50000]
        except Exception:
            logger.error("no se pudo leer el texto de la pantalla", exc_info=True)
    finally:
        obs.detach()
    cid_nd, cid_tr = f"HEUR-NATIVE-DIALOG-{sid}", f"HEUR-ERROR-TRACE-{sid}"
    if not flows:
        out.append(common.blocked(cid_nd, CRITERIA["NATIVE-DIALOG"], "no se completó ningún flujo en el que observar diálogos"))
    elif obs.dialogs:
        out.append(common.result(cid_nd, Status.FAILED, CRITERIA["NATIVE-DIALOG"], f"Diálogos nativos durante {flows}: {obs.dialogs}.",
                                 [common.text("; ".join(obs.dialogs))], category="usability", rule=RULES["NATIVE-DIALOG"], severity="LOW"))
    else:
        out.append(common.result(cid_nd, Status.PASSED, CRITERIA["NATIVE-DIALOG"], f"Ningún diálogo nativo durante {flows}.",
                                 [common.text(", ".join(flows), "flujos observados")]))
    screen_trace = TRACE_RE.search(page_text or "")
    traces = obs.error_traces + ([f"en pantalla: «{screen_trace.group(0)[:120]}»"] if screen_trace else [])
    if traces:
        out.append(common.result(cid_tr, Status.FAILED, CRITERIA["ERROR-TRACE"], f"Trazas internas expuestas: {traces}.", [common.text("; ".join(traces))],
                                 category="sensitive_data_exposure", rule="STACK-TRACE-EXPOSURE", severity="MEDIUM"))
    elif obs.server_errors:
        out.append(common.result(cid_tr, Status.PASSED, CRITERIA["ERROR-TRACE"], f"{obs.server_errors} respuesta(s) 5xx observadas, ninguna con traza.",
                                 [common.text(str(obs.server_errors), "respuestas 5xx revisadas")]))
    else:
        out.append(common.not_executed(cid_tr, CRITERIA["ERROR-TRACE"], "no se observó ninguna respuesta de error del servidor ni traza en pantalla"))
    return out


def run(ctx, specs: List[Dict[str, Any]]) -> List[common.CaseResult]:
    out = []
    for s in specs:
        out += check_screen(ctx, s)
    return out
