from pathlib import Path

import pytest

from smart_tests import ci_report, gherkin, package
from smart_tests.package import TestCase

FEATURE = """# language: es
@RQ-09
Característica: Alta de unidades administrativas

  Antecedentes:
    Dado que soy Administrador de Unidad Administrativa

  @CI-59
  Escenario: Alta de una unidad hija
    Cuando doy de alta la unidad "Dirección {C}"
    Entonces la unidad aparece en el árbol
    Y queda registrada en la bitácora

  @actor:Administrador_general
  Esquema del escenario: Código duplicado
    Cuando doy de alta el código <codigo>
    Entonces veo el mensaje "<mensaje>"

    Ejemplos:
      | codigo | mensaje          |
      | A1     | El código existe |
      | B2     | El código existe |
"""


def test_feature_parsing(tmp_path):
    f = tmp_path / "alta.feature"
    f.write_text(FEATURE, encoding="utf-8")
    cases = gherkin.to_cases(f, "c9", TestCase)
    ids = [c.case_id for c in cases]
    assert ids == ["CI-59", "ALTA-2-1", "ALTA-2-2"]
    c0 = cases[0]
    assert c0.kind == "BDD" and c0.requirement == "RQ-09" and c0.actor == "Administrador de Unidad Administrativa"
    assert "Dirección c9" in c0.steps and c0.expected.splitlines() == ["la unidad aparece en el árbol", "queda registrada en la bitácora"]
    assert cases[1].actor == "Administrador general" and "A1" in cases[1].steps and cases[2].expected == 'veo el mensaje "El código existe"'


def test_package_from_features_only(tmp_path):
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "alta.feature").write_text(FEATURE, encoding="utf-8")
    pkg = package.load(str(tmp_path), "c1")
    assert pkg.xlsx is None and len(pkg.cases) == 3 and {c.kind for c in pkg.cases} == {"BDD"}


def test_outline_without_examples_is_rejected(tmp_path):
    f = tmp_path / "x.feature"
    f.write_text("Feature: x\n  Scenario Outline: y\n    Given a <b>\n", encoding="utf-8")
    with pytest.raises(gherkin.GherkinError):
        gherkin.to_cases(f, "c1", TestCase)


JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="UsuarioControllerTest" tests="4">
  <testcase classname="mx.app.UsuarioControllerTest" name="crear_conRolSinPermiso_responde403" time="0.2"/>
  <testcase classname="mx.app.UsuarioControllerTest" name="crear_sinToken_responde401" time="0.1"/>
  <testcase classname="mx.app.UsuarioServiceTest" name="actualizar_versionObsoleta_lanzaConflict" time="0.1"><failure message="x"/></testcase>
  <testcase classname="mx.app.UsuarioServiceTest" name="ignorada" time="0"><skipped/></testcase>
</testsuite></testsuites>"""
JACOCO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.1//EN" "report.dtd">
<report name="app"><package name="mx/app"><counter type="LINE" missed="99" covered="1"/></package>
<counter type="INSTRUCTION" missed="10" covered="90"/><counter type="BRANCH" missed="3" covered="1"/><counter type="LINE" missed="20" covered="80"/></report>"""


def test_ci_summary(tmp_path):
    (tmp_path / "TEST-a.xml").write_text(JUNIT)
    (tmp_path / "jacoco.xml").write_text(JACOCO)
    (tmp_path / "evil.xml").write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite>&a;</testsuite>')
    s = ci_report.summarize_dir(str(tmp_path))
    assert (s["tests"], s["failures"], s["skipped"]) == (4, 1, 1)
    assert s["has_401_tests"] and s["has_403_tests"] and s["has_409_tests"]
    assert s["coverage_line_pct"] == 80.0 and s["coverage_branch_pct"] == 25.0      # report-level counters, not the package's
    assert any("entidades" in r for r in s["rejected"])
    assert s["failed_tests"][0]["test"].endswith("actualizar_versionObsoleta_lanzaConflict")


def test_ci_summary_without_reports(tmp_path):
    (tmp_path / "otra.xml").write_text("<config/>")
    with pytest.raises(ci_report.CIReportError):
        ci_report.summarize_dir(str(tmp_path))


def test_ci_names_not_found_is_false_not_absent(tmp_path):
    (tmp_path / "TEST-b.xml").write_text('<testsuite><testcase classname="A" name="suma"/></testsuite>')
    s = ci_report.summarize_dir(str(tmp_path))
    assert s["has_403_tests"] is False and "nombre" in s["detection_note"].lower()
