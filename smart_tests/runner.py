"""Runs the selected cases of a package against the real application and writes, under out_dir:
  results.json          every result (centinela_core.results), plus the summary
  <xlsx>_ejecutado.xlsx copy of the package workbook with Estado/Bloqueado por/Evidencia/Hallazgo filled ONLY for what ran
  reporte.html / .pdf   human report (PDF printed by the same Chromium)
  evidencia/            screenshots

`args["checks"]` (optional) adds the generic checks of ADR-0002 (smart_tests/checks): negative authorization, business rules,
heuristics and accessibility behind the login. A run may consist only of checks (no "package" in args).

A case without an implemented handler is NOT_EXECUTED with that reason. A handler that raises is BLOCKED with the error as reason
(and the traceback in the log). Nothing is reported as passed without evidence (the result model refuses it).
"""
import importlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

from playwright.sync_api import sync_playwright

from centinela_core import test_credentials as tc
from centinela_core.results import CaseResult, Evidence, Status, summarize

from smart_tests import ingest, package, report
from smart_tests.session import LoginError, Session, screenshot_dir

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    browser: Any
    pkg: package.TestPackage
    asset: str
    out_dir: Path
    project: Any
    sessions: Dict[str, Session] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, CaseResult] = field(default_factory=dict)

    @property
    def evidence_dir(self) -> Path:
        return screenshot_dir(self.out_dir)

    @property
    def cycle(self) -> str:
        return self.pkg.cycle

    def session(self, profile_name: str) -> Session:
        """A logged-in session for a stored test profile (one per profile, reused)."""
        if profile_name not in self.sessions:
            prof = tc.get_profile(self.asset, profile_name)
            s = Session(self.browser, prof, self.evidence_dir, profile_name)
            s.login()
            self.sessions[profile_name] = s
        return self.sessions[profile_name]

    def secrets(self) -> List[str]:
        return [s.profile.get("password", "") for s in self.sessions.values()]


def _ordered(project, selected: List[str]) -> List[str]:
    order = getattr(project, "ORDER", [])
    first = [c for c in order if c in selected]
    return first + [c for c in selected if c not in first]


def run(args: Dict[str, Any], secrets: Dict[str, str], out_dir: Path) -> Dict[str, Any]:
    project = importlib.import_module(f"smart_tests.projects.{args['project']}")
    kinds = list(args.get("checks") or [])
    if not args.get("package") and not kinds:
        raise SystemExit("se necesita un paquete de pruebas o al menos una comprobación genérica (checks)")
    pkg = package.load(args["package"], args["cycle"]) if args.get("package") else package.empty(args["cycle"])
    selected = args.get("cases") or [c.case_id for c in pkg.cases]
    unknown = [c for c in selected if c not in {x.case_id for x in pkg.cases}]
    if unknown:
        raise SystemExit(f"casos que no están en el paquete: {unknown}")
    started = datetime.now().isoformat(timespec="seconds")
    handlers: Dict[str, Callable] = project.HANDLERS
    results: List[CaseResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = RunContext(browser, pkg, args["asset"], out_dir, project)
        try:
            for cid in _ordered(project, selected):
                case = pkg.case(cid)
                h = handlers.get(cid)
                if h is None:
                    r = CaseResult(cid, Status.NOT_EXECUTED, criterion=case.criterion, reason="sin automatización en esta versión (no hay handler para este caso)")
                else:
                    logger.info("caso %s", cid)
                    try:
                        r = h(ctx, case)
                    except LoginError as e:
                        logger.error("caso %s bloqueado por inicio de sesión", cid, exc_info=True)
                        r = CaseResult(cid, Status.BLOCKED, criterion=case.criterion, reason=f"inicio de sesión: {e}")
                    except Exception as e:
                        logger.error("caso %s interrumpido", cid, exc_info=True)
                        r = CaseResult(cid, Status.BLOCKED, criterion=case.criterion, reason=f"error durante la ejecución: {str(e)[:300]}")
                results.append(r)
                ctx.results[cid] = r
            if kinds:
                from smart_tests import checks
                for r in checks.run(ctx, kinds):
                    results.append(r)
                    ctx.results[r.case_id] = r
        finally:
            for s in ctx.sessions.values():
                s.close()
            secret_values = ctx.secrets()
            browser.close()
    check_count = sum(1 for r in results if r.case_id not in {c.case_id for c in pkg.cases})
    summary = summarize(results, total_planned=len(pkg.cases) + check_count)
    finished = datetime.now().isoformat(timespec="seconds")
    meta = {"project": args["project"], "asset": args["asset"], "cycle": pkg.cycle,
            "package": Path(args["package"]).name if args.get("package") else "(solo comprobaciones genéricas)",
            "started": started, "finished": finished, "selected": len(selected), "planned_in_package": len(pkg.cases),
            "checks": kinds, "check_results": check_count, "planned_total": len(pkg.cases) + check_count,
            "substitution_notice": getattr(project, "SUBSTITUTION_NOTICE", "")}
    doc = {"meta": meta, "summary": summary, "results": [r.to_dict() for r in results]}
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    for sv in secret_values:          # defensive: a secret must never reach an output file
        if sv and sv in text:
            raise RuntimeError("un secreto apareció en los resultados; no se escriben")
    (out_dir / "results.json").write_text(text, encoding="utf-8")
    if pkg.xlsx:
        xlsx_out = out_dir / (Path(pkg.xlsx).stem + "_ejecutado.xlsx")
        written = package.write_execution_sheet(pkg, results, str(xlsx_out))
    else:
        xlsx_out, written = Path("(sin libro de ejecución)"), {"filas_escritas": 0}
    html_path = report.write(out_dir, meta, summary, results, pkg)
    ingest_out = {"run": ingest.send_run(results, args["asset"], secrets, meta),
                  "security_failures": ingest.send_security_failures(results, args["asset"], secrets, meta)}
    return {"summary": summary, "xlsx": xlsx_out.name, "xlsx_written": written, "report": html_path.name, "ingest": ingest_out}
