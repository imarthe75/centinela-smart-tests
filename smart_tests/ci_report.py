"""Reads a project's CI test reports (read-only; ADR-0002 §5): JUnit XML (Surefire/Gradle/Karma/Playwright junit reporter) and JaCoCo XML.

`summarize_dir(path)` returns what Centinela shows next to the functional cases: totals, failed tests, line/branch coverage, and
whether the suite contains the API tests the skills require (401, 403, 409) — detected by test/class NAME, which is a heuristic:
a test called `deberiaRechazar` that checks a 403 is not detected; the result says so instead of claiming absence as fact.

XML safety: files over 25 MB are refused; a document that declares an ENTITY is refused; a DOCTYPE without entities (JaCoCo
declares one) is dropped before parsing.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_BYTES = 25_000_000
PATTERNS = {
    "has_401_tests": re.compile(r"401|unauthori[sz]ed|sin[_ ]?token|no[_ ]?autenticad|unauthenticated", re.I),
    "has_403_tests": re.compile(r"403|forbidden|sin[_ ]?permiso|access[_ ]?denied|acceso[_ ]?denegado|no[_ ]?autorizad", re.I),
    "has_409_tests": re.compile(r"409|conflict|conflicto|optimistic|version[_ ]?(desactualizada|obsoleta|stale)|stale", re.I),
}


class CIReportError(ValueError):
    pass


def _parse(path: Path) -> ET.Element:
    if path.stat().st_size > MAX_BYTES:
        raise CIReportError(f"{path.name}: supera {MAX_BYTES // 1_000_000} MB")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"<!ENTITY", raw, re.I):
        raise CIReportError(f"{path.name}: declara entidades XML (rechazado)")
    raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, count=1, flags=re.I)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as e:
        raise CIReportError(f"{path.name}: XML inválido ({e})") from e


def _junit(root: ET.Element, acc: Dict[str, Any], source: str) -> None:
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    for s in suites:
        acc["suites"] += 1
        for tc in s.findall("testcase"):
            acc["tests"] += 1
            name = f"{tc.get('classname', '')}.{tc.get('name', '')}"
            acc["_names"].append(name)
            try:
                acc["duration_s"] += float(tc.get("time") or 0)
            except ValueError:                        # a non-numeric time attribute: the duration total just omits it
                acc["duration_unparsed"] = acc.get("duration_unparsed", 0) + 1
            if tc.find("failure") is not None:
                acc["failures"] += 1
                acc["failed_tests"].append({"test": name[:200], "kind": "failure", "source": source})
            elif tc.find("error") is not None:
                acc["errors"] += 1
                acc["failed_tests"].append({"test": name[:200], "kind": "error", "source": source})
            elif tc.find("skipped") is not None:
                acc["skipped"] += 1


def _jacoco(root: ET.Element) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {"coverage_line_pct": None, "coverage_branch_pct": None}
    for c in root.findall("counter"):                     # report-level counters only (direct children of <report>)
        missed, covered = int(c.get("missed", 0)), int(c.get("covered", 0))
        total = missed + covered
        pct = round(100.0 * covered / total, 1) if total else None
        if c.get("type") == "LINE":
            out["coverage_line_pct"] = pct
        elif c.get("type") == "BRANCH":
            out["coverage_branch_pct"] = pct
    return out


def summarize_dir(path: str) -> Dict[str, Any]:
    base = Path(path)
    if not base.exists():
        raise CIReportError(f"no existe: {path}")
    files = [base] if base.is_file() else sorted(p for p in base.rglob("*.xml") if p.is_file())
    acc: Dict[str, Any] = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "suites": 0, "duration_s": 0.0, "failed_tests": [],
                           "coverage_line_pct": None, "coverage_branch_pct": None, "_names": [], "files": [], "rejected": []}
    for f in files:
        try:
            root = _parse(f)
        except CIReportError as e:
            acc["rejected"].append(str(e))
            continue
        if root.tag in ("testsuite", "testsuites"):
            _junit(root, acc, f.name)
            acc["files"].append({"file": f.name, "kind": "junit"})
        elif root.tag == "report" and root.find("counter") is not None:
            cov = _jacoco(root)
            for k, v in cov.items():
                if v is not None:
                    acc[k] = v
            acc["files"].append({"file": f.name, "kind": "jacoco"})
    if not acc["files"]:
        raise CIReportError("no se encontró ningún reporte JUnit ni JaCoCo válido" + (f" (rechazados: {acc['rejected']})" if acc["rejected"] else ""))
    names = acc.pop("_names")
    for key, rx in PATTERNS.items():
        acc[key] = any(rx.search(n) for n in names) if names else None
    acc["duration_s"] = round(acc["duration_s"], 1)
    acc["failed_tests"] = acc["failed_tests"][:100]
    acc["detection_note"] = ("Las pruebas de 401/403/409 se detectan por el NOMBRE de la prueba o clase; una prueba con otro nombre no se "
                             "detecta. «false» significa «no encontrada por nombre», no «inexistente».")
    return acc
