"""Send to Centinela-AI's ingestion endpoint (fail-closed on Centinela's side) ONLY the failures that become findings:
  * security-relevant failures (a SMART-TESTS-* security finding per category), and
  * observation failures of the generic checks — `usability` and `accessibility` — which are NOT security but are findings under the
    static detector's own rule id (meta.rule), marked as observed at runtime.
Without an ingest URL/token configured nothing is sent and the result says so (it is not an error of the run)."""
import logging
from typing import Any, Dict, List

import requests

from centinela_core.results import CaseResult, Status

logger = logging.getLogger(__name__)

OBSERVATION_CATEGORIES = {"usability", "accessibility"}


def is_finding(r: CaseResult) -> bool:
    return r.security_relevant or (r.status is Status.FAILED and (r.meta or {}).get("category") in OBSERVATION_CATEGORIES)


def send_security_failures(results: List[CaseResult], asset: str, secrets: Dict[str, str], meta: Dict[str, Any]) -> Dict[str, Any]:
    items = [r for r in results if is_finding(r)]
    url, token = (secrets.get("ingest_url") or "").strip(), (secrets.get("ingest_token") or "").strip()
    if not items:
        return {"sent": 0, "detail": "sin fallos que generen hallazgo (seguridad, usabilidad o accesibilidad)"}
    if not url or not token:
        return {"sent": 0, "pending": len(items), "detail": "ingesta a Centinela no configurada (SMART_TESTS_INGEST_URL/TOKEN)"}
    payload = {"asset_name": asset, "source": "centinela-smart-tests", "run": {k: meta[k] for k in ("project", "cycle", "package", "finished")},
               "results": [r.to_dict() for r in items]}
    try:
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except Exception as e:
        logger.error("ingesta a Centinela fallida", exc_info=True)
        return {"sent": 0, "pending": len(items), "detail": f"error de red: {str(e)[:200]}"}
    if resp.status_code >= 300:
        return {"sent": 0, "pending": len(items), "detail": f"Centinela respondió HTTP {resp.status_code}: {resp.text[:200]}"}
    body = resp.json()
    return {"sent": len(items), "accepted": body.get("accepted"), "findings": body.get("findings"), "detail": "ok"}


def run_url(ingest_url: str) -> str:
    """The whole-run endpoint lives next to the security-failures one: <...>/api/ingest/smart-tests -> <...>/api/ingest/smart-tests/run."""
    u = (ingest_url or "").strip().rstrip("/")
    return f"{u}/run" if u else ""


def send_run(results: List[CaseResult], asset: str, secrets: Dict[str, str], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Send EVERY case (any status) so Centinela's "Pruebas funcionales" tab shows the real run, not only its security failures.
    Centinela recomputes the summary itself and replaces a run it already had (same project/cycle/package/dates/asset)."""
    url, token = run_url(secrets.get("ingest_url") or ""), (secrets.get("ingest_token") or "").strip()
    if not url or not token:
        return {"sent": False, "detail": "ingesta a Centinela no configurada (SMART_TESTS_INGEST_URL/TOKEN)"}
    payload = {"asset_name": asset, "source": "centinela-smart-tests", "run": dict(meta), "results": [r.to_dict() for r in results]}
    try:
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    except Exception as e:
        logger.error("envío de la corrida a Centinela fallido", exc_info=True)
        return {"sent": False, "detail": f"error de red: {str(e)[:200]}"}
    if resp.status_code >= 300:
        return {"sent": False, "detail": f"Centinela respondió HTTP {resp.status_code}: {resp.text[:300]}"}
    body = resp.json()
    return {"sent": True, "run_id": body.get("run_id"), "created": body.get("created"), "detail": "ok"}


def ci_url(ingest_url: str) -> str:
    u = (ingest_url or "").strip().rstrip("/")
    return f"{u}/ci" if u else ""


def send_ci(summary: Dict[str, Any], asset: str, secrets: Dict[str, str], run: Dict[str, Any]) -> Dict[str, Any]:
    """Send a CI report summary (ci_report.summarize_dir) to <...>/api/ingest/smart-tests/ci. Read-only data about the project's own
    pipeline; it never runs the project's tests."""
    url, token = ci_url(secrets.get("ingest_url") or ""), (secrets.get("ingest_token") or "").strip()
    if not url or not token:
        return {"sent": False, "detail": "ingesta a Centinela no configurada (SMART_TESTS_INGEST_URL/TOKEN)"}
    payload = {"asset_name": asset, "source": "centinela-smart-tests", "run": dict(run), "summary": summary}
    try:
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    except Exception as e:
        logger.error("envío del reporte de CI a Centinela fallido", exc_info=True)
        return {"sent": False, "detail": f"error de red: {str(e)[:200]}"}
    if resp.status_code >= 300:
        return {"sent": False, "detail": f"Centinela respondió HTTP {resp.status_code}: {resp.text[:300]}"}
    body = resp.json()
    return {"sent": True, "report_id": body.get("report_id"), "created": body.get("created"), "detail": "ok"}
