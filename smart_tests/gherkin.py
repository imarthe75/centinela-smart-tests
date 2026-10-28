"""Reads Gherkin `.feature` files (generated with the BDD skills) as a source of cases, next to or instead of the `Ejecucion` sheet.

Supported: Feature/Característica, Background/Antecedentes, Scenario/Escenario, Scenario Outline/Esquema del escenario + Examples/
Ejemplos, steps Given/When/Then/And/But and Dado/Cuando/Entonces/Y/Pero (also `*`), tags, comments, doc strings and data tables
(kept as text). Each scenario becomes a TestCase of kind "BDD":
  * case_id: a tag that looks like a case id (`@CI-59`, `@UAT-03`, `@TC-12`, or `@id:<x>`); otherwise <FEATURE-SLUG>-<n>.
    An outline expands one case per example row: <id>-<row>.
  * requirement: a tag `@RQ-09`; actor: a tag `@actor:<rol>` / `@rol:<rol>` (tags have no spaces: `_` reads as a space) or the text of the first Given that names one
    ("que soy|como <rol>"); expected: the Then lines; steps: every step line.
The feature supplies the case, actor and expected result; running it still needs a handler in the project map for that case id —
without one the case is NOT_EXECUTED with that reason (never passed).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

KW_FEATURE = ("Feature:", "Característica:", "Caracteristica:", "Funcionalidad:")
KW_BACKGROUND = ("Background:", "Antecedentes:", "Contexto:")
KW_SCENARIO = ("Scenario:", "Example:", "Escenario:", "Ejemplo:")
KW_OUTLINE = ("Scenario Outline:", "Scenario Template:", "Esquema del escenario:", "Esquema de escenario:")
KW_EXAMPLES = ("Examples:", "Scenarios:", "Ejemplos:")
STEP_RE = re.compile(r"^(Given|When|Then|And|But|Dado|Dada|Dados|Dadas|Cuando|Entonces|Y|E|Pero|\*)\s+(.*)$")
THEN_WORDS = {"Then", "Entonces"}
ID_TAG = re.compile(r"^@((?:CI|UAT|TC|CP|CU)-\d+|id:[\w.-]+)$", re.I)
RQ_TAG = re.compile(r"^@(RQ-\d+)$", re.I)
ACTOR_TAG = re.compile(r"^@(?:actor|rol):(.+)$", re.I)
ACTOR_TEXT = re.compile(r"(?:que soy|como|soy un|soy una|as an?|i am an?)\s+(?:el |la |un |una )?([^,.;]+)", re.I)
MAX_FILE_BYTES = 2_000_000


class GherkinError(ValueError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", (text or "").upper()).strip("-")[:30] or "FEATURE"


def _starts(line: str, kws) -> Optional[str]:
    for k in kws:
        if line.startswith(k):
            return line[len(k):].strip()
    return None


def _table_row(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(text: str, source: str = "") -> List[Dict]:
    """Returns one dict per (expanded) scenario: {id, title, tags, steps, then, feature, source}."""
    feature, feature_tags = "", []
    background: List[str] = []
    scenarios: List[Dict] = []
    pending_tags: List[str] = []
    cur: Optional[Dict] = None
    section = None                      # "background" | "scenario" | "examples"
    in_doc = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('"""') or line.startswith("```"):
            in_doc = not in_doc
            continue
        if in_doc or not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            pending_tags += line.split()
            continue
        if (v := _starts(line, KW_FEATURE)) is not None:
            feature, feature_tags, pending_tags = v, pending_tags, []
            continue
        if _starts(line, KW_BACKGROUND) is not None:
            section, cur = "background", None
            continue
        out_title = _starts(line, KW_OUTLINE)
        sc_title = None if out_title is not None else _starts(line, KW_SCENARIO)
        if out_title is not None or sc_title is not None:
            cur = {"title": out_title if out_title is not None else sc_title, "tags": feature_tags + pending_tags, "steps": list(background),
                   "then": [], "outline": out_title is not None, "header": None, "rows": []}
            scenarios.append(cur)
            pending_tags, section = [], "scenario"
            continue
        if _starts(line, KW_EXAMPLES) is not None:
            if cur is None or not cur["outline"]:
                raise GherkinError(f"{source}: «Ejemplos» fuera de un esquema de escenario")
            section, pending_tags = "examples", []
            continue
        if line.startswith("|"):
            if section == "examples" and cur is not None:
                row = _table_row(line)
                if cur["header"] is None:
                    cur["header"] = row
                else:
                    cur["rows"].append(row)
            elif cur is not None and cur["steps"]:
                cur["steps"][-1] += " " + line
            continue
        m = STEP_RE.match(line)
        if m:
            step = f"{m.group(1)} {m.group(2)}"
            if section == "background":
                background.append(step)
            elif cur is not None:
                cur["steps"].append(step)
                if m.group(1) in THEN_WORDS or (m.group(1) in {"And", "Y", "E", "But", "Pero"} and cur.get("_last_then")):
                    cur["then"].append(m.group(2))
                    cur["_last_then"] = True
                else:
                    cur["_last_then"] = m.group(1) in THEN_WORDS
            continue
    out = []
    for n, sc in enumerate(scenarios, 1):
        base = {"title": sc["title"], "tags": sc["tags"], "feature": feature, "source": source, "n": n}
        if sc["outline"]:
            if not sc["rows"]:
                raise GherkinError(f"{source}: el esquema «{sc['title']}» no tiene filas de ejemplos")
            for i, row in enumerate(sc["rows"], 1):
                values = dict(zip(sc["header"], row))
                sub = lambda s: re.sub(r"<([^>]+)>", lambda mm: values.get(mm.group(1), mm.group(0)), s)
                out.append({**base, "title": sub(sc["title"]), "steps": [sub(s) for s in sc["steps"]], "then": [sub(s) for s in sc["then"]],
                            "row": i})
        else:
            out.append({**base, "steps": sc["steps"], "then": sc["then"], "row": None})
    return out


def to_cases(path: Path, cycle: str, case_factory) -> List:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise GherkinError(f"{path.name}: archivo demasiado grande")
    text = path.read_text(encoding="utf-8").replace("{C}", cycle)
    scenarios = parse(text, path.name)
    feature_slug = _slug(path.stem)
    cases = []
    for sc in scenarios:
        n = sc["n"]
        cid = next((ID_TAG.match(t).group(1) for t in sc["tags"] if ID_TAG.match(t)), "")
        cid = cid[3:] if cid.lower().startswith("id:") else cid
        cid = cid.upper() if cid else f"{feature_slug}-{n}"
        if sc["row"] is not None:
            cid = f"{cid}-{sc['row']}"
        rq = next((RQ_TAG.match(t).group(1).upper() for t in sc["tags"] if RQ_TAG.match(t)), "")
        actor = next((ACTOR_TAG.match(t).group(1).replace("_", " ") for t in sc["tags"] if ACTOR_TAG.match(t)), "")
        if not actor:
            for s in sc["steps"]:
                if s.split(" ", 1)[0] in {"Given", "Dado", "Dada"} and (m := ACTOR_TEXT.search(s)):
                    actor = m.group(1).strip()
                    break
        cases.append(case_factory(case_id=cid, kind="BDD", requirement=rq, origin=f"{path.name}: {sc['feature']}", criterion=sc["title"],
                                  actor=actor, steps="\n".join(sc["steps"]), expected="\n".join(sc["then"]), title=sc["title"]))
    return cases
