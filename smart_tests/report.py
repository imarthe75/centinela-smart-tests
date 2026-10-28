"""HTML report + PDF printed by Chromium (no extra PDF dependency). States are shown as they are: nothing not executed is shown as passed."""
import html
import logging
from pathlib import Path
from typing import Any, Dict, List

from centinela_core.results import CaseResult, Status

logger = logging.getLogger(__name__)
LABEL = {Status.PASSED: ("Pasó", "#15803d"), Status.FAILED: ("Falló", "#b91c1c"), Status.BLOCKED: ("Bloqueado", "#a16207"),
         Status.NOT_EXECUTED: ("No ejecutado", "#6b7280")}


def _e(s) -> str:
    return html.escape(str(s or ""))


def _row(r: CaseResult, case) -> str:
    lab, color = LABEL[r.status]
    ev = []
    for e in r.evidence:
        if e.kind == "screenshot":
            ev.append(f'<div><img src="evidencia/{_e(e.value)}" style="max-width:420px;border:1px solid #ccd"><br><small>{_e(e.note)}</small></div>')
        else:
            ev.append(f"<div><code>{_e(e.value)}</code> <small>{_e(e.note)}</small></div>")
    extra = ""
    if r.substitution:
        extra += f"<div class='sub'>Sustitución declarada: {_e(r.substitution)}</div>"
    if not r.status.executed:
        extra += f"<div class='why'>Motivo: {_e(r.reason)}</div>"
    if r.security_relevant:
        extra += "<div class='sec'>Relevante para seguridad: enviado a Centinela-AI</div>"
    elif r.status is Status.FAILED and (r.meta or {}).get("category") in ("usability", "accessibility"):
        kind = "usabilidad" if r.meta["category"] == "usability" else "accesibilidad"
        extra += f"<div class='sub'>Hallazgo de {kind} (regla {_e(r.meta.get('rule', ''))}): enviado a Centinela-AI</div>"
    return (f"<tr><td><b>{_e(r.case_id)}</b><br><small>{_e(case.requirement if case else '')}</small></td>"
            f"<td>{_e(r.criterion)}</td><td style='color:{color};font-weight:700'>{lab}</td>"
            f"<td>{_e(case.expected if case else '')}<hr>{_e(r.detail)}{extra}</td><td>{''.join(ev)}</td></tr>")


def write(out_dir: Path, meta: Dict[str, Any], summary: Dict[str, Any], results: List[CaseResult], pkg) -> Path:
    by_id = {c.case_id: c for c in pkg.cases}
    c = summary["counts"]
    rows = "".join(_row(r, by_id.get(r.case_id)) for r in results)
    pr = summary["pass_rate_over_executed_pct"]
    doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Pruebas funcionales · {_e(meta['project'])}</title>
<style>body{{font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#1a1a2e;margin:24px}}h1{{color:#0f1b3d}}
table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ccd3e0;padding:6px;vertical-align:top}}th{{background:#eef1f8}}
.kpi{{display:inline-block;background:#f4f6fb;border:1px solid #d8dde8;border-radius:6px;padding:8px 14px;margin:4px}}.kpi b{{display:block;font-size:20px}}
.sub{{color:#7c3aed}}.why{{color:#a16207}}.sec{{color:#b91c1c;font-weight:700}}.note{{border-left:4px solid #a16207;background:#fffbeb;padding:8px 12px}}</style></head><body>
<h1>Pruebas funcionales ejecutadas · {_e(meta['project'])}</h1>
<p>Activo: <code>{_e(meta['asset'])}</code> · Paquete: {_e(meta['package'])} · Ciclo: <b>{_e(meta['cycle'])}</b> · {_e(meta['started'])} → {_e(meta['finished'])}</p>
<div><span class="kpi">Casos en el paquete<b>{summary['planned']}</b></span><span class="kpi">Ejecutados<b>{summary['executed']} ({summary['executed_pct']} %)</b></span>
<span class="kpi">Pasaron<b>{c['PASSED']}</b></span><span class="kpi">Fallaron<b>{c['FAILED']}</b></span><span class="kpi">Bloqueados<b>{c['BLOCKED']}</b></span>
<span class="kpi">No ejecutados<b>{c['NOT_EXECUTED'] + summary['not_reported']}</b></span>
<span class="kpi">Éxito sobre lo ejecutado<b>{'—' if pr is None else f'{pr} %'}</b></span></div>
<p class="note">El porcentaje de éxito se calcula solo sobre los casos que se ejecutaron. Un caso bloqueado o no ejecutado nunca cuenta como
aprobado. {_e(meta.get('substitution_notice'))}</p>
<table><tr><th>Caso</th><th>Criterio</th><th>Estado</th><th>Esperado / observado</th><th>Evidencia</th></tr>{rows}</table>
</body></html>"""
    path = out_dir / "reporte.html"
    path.write_text(doc, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            pg = b.new_page()
            pg.goto(path.resolve().as_uri(), wait_until="load")
            pg.pdf(path=str(out_dir / "reporte.pdf"), format="A4", landscape=True, print_background=True,
                   margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
            b.close()
    except Exception:
        logger.error("no se pudo generar el PDF del reporte", exc_info=True)
    return path
