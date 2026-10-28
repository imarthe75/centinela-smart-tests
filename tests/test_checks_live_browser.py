"""End-to-end tests of the generic checks (ADR-0002) with a REAL Chromium against a REAL local web app (tests/fixtures/fixture_app.py)
in two modes: `good` must pass every check, `bad` must fail each one for the right reason. No mocked responses: the app is a real HTTP
server and every request goes through the browser."""
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

from centinela_core.results import Status  # noqa: E402

from smart_tests import ingest  # noqa: E402
from smart_tests.checks import a11y, authz_negative, business_rules, heuristics  # noqa: E402
from smart_tests.session import Session  # noqa: E402
from tests.fixtures.fixture_app import App  # noqa: E402


class Ctx:
    """Minimal run context: same contract the checks use from runner.RunContext (session/cycle/project), with profiles built
    from the fixture app instead of Vault."""

    def __init__(self, browser, app, out: Path):
        self.browser, self.app, self.out = browser, app, out
        self.sessions = {}
        self.cycle = "t1"
        self.project = None

    def session(self, name):
        if name not in self.sessions:
            user, pw_ = {"admin": ("admin", "admin-pass"), "viewer": ("viewer", "viewer-pass")}[name]
            prof = {"name": name, "username": user, "password": pw_, "login_ui": {"url": self.app.base + "/login"},
                    "app_login": {"url": self.app.base + "/api/auth"}}
            s = Session(self.browser, prof, self.out, name)
            s.login()
            self.sessions[name] = s
        return self.sessions[name]


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture(params=["good", "bad"])
def env(request, browser, tmp_path):
    app = App(request.param).start()
    ctx = Ctx(browser, app, tmp_path)
    yield request.param, app, ctx
    for s in ctx.sessions.values():
        s.close()
    app.stop()


# ------------------------------------------------------------------ screen callables the project would provide
def _open_items(page, app):
    page.goto(app.base + "/items", wait_until="domcontentloaded")
    page.wait_for_selector("#pag:has-text('Mostrando')")


def _save(page):
    with page.expect_response(lambda r: "/api/items" in r.url and r.request.method in ("POST", "PUT"), timeout=8000) as ri:
        page.click("#guardar")
    page.wait_for_timeout(300)
    return ri.value, page.inner_text("#toast")


def make_screen(app):
    def create(ctx, page, tag):
        _open_items(page, app)
        page.click("#nuevo")
        page.fill("#codigo", tag)
        page.fill("#nombre", "Elemento " + tag)
        return _save(page)

    def open_edit(ctx, page, tag):
        _open_items(page, app)
        page.locator(f"tr[data-codigo='{tag}'] .edit").first.click()
        page.wait_for_selector("#dlg", state="visible")

    def set_and_save(page, value):
        page.fill("#nombre", value)
        return _save(page)

    def read_value(ctx, page, tag):
        _open_items(page, app)
        return page.locator(f"tr[data-codigo='{tag}'] .nombre").first.inner_text()

    def listed(ctx, page, tag):
        _open_items(page, app)
        return page.locator(f"tr[data-codigo='{tag}']").count() > 0

    def delete(ctx, page, tag):
        _open_items(page, app)
        page.on("dialog", lambda d: d.accept())
        with page.expect_response(lambda r: r.request.method == "DELETE", timeout=8000) as ri:
            page.locator(f"tr[data-codigo='{tag}'] .del").first.click()
            if page.locator("#cf").is_visible():
                page.click("#si")
        return ri.value, ""

    def cleanup(ctx, page, tag):
        for it in list(app.items.values()):
            if it["codigo"].startswith(tag):
                it["deleted"] = True

    def open_form(ctx, page, tag):
        _open_items(page, app)
        page.click("#nuevo")
        page.fill("#codigo", tag)
        page.fill("#nombre", "Elemento " + tag)

    def open_invalid(ctx, page):
        _open_items(page, app)
        page.click("#nuevo")
        page.fill("#codigo", "inv")

    def prepare_delete(ctx, page, tag):
        create(ctx, page, tag)
        _open_items(page, app)

    return dict(create=create, open_edit=open_edit, set_and_save=set_and_save, read_value=read_value, listed=listed, delete=delete,
                cleanup=cleanup, open_form=open_form, open_invalid=open_invalid, prepare_delete=prepare_delete)


# ------------------------------------------------------------------ tests
def test_authz_negative(env):
    mode, app, ctx = env
    spec = {"id": "ADMIN", "permission": "administración", "denied_profile": "viewer", "screen_url": app.base + "/admin",
            "api": {"method": "GET", "url": app.base + "/api/admin/data"}}
    r = authz_negative.check(ctx, spec)
    if mode == "good":
        assert r.status is Status.PASSED, r.detail
        assert "403" in r.detail and "redirigida" in r.detail
    else:
        assert r.status is Status.FAILED and r.security_relevant and r.meta["category"] == "access_control", r.detail
        assert ingest.is_finding(r)


def test_authz_negative_write_probe_needs_opt_in(env):
    mode, app, ctx = env
    spec = {"id": "ITEMS-POST", "denied_profile": "viewer", "api": {"method": "POST", "url": app.base + "/api/items", "body": {}}}
    r = authz_negative.check(ctx, spec)
    assert r.status is Status.BLOCKED and "write_probe" in r.reason
    assert not app.items                                     # nothing was written


def test_business_rules(env):
    mode, app, ctx = env
    s = make_screen(app)
    spec = {"id": "ITEMS", "profile": "admin",
            "uniqueness": {"create": s["create"], "cleanup": s["cleanup"]},
            "immutability": {"create": s["create"], "open_edit": s["open_edit"], "fields": ["#codigo"],
                             "close": lambda page: page.click("#cancelar"), "cleanup": s["cleanup"]},
            "soft_delete": {"create": s["create"], "delete": s["delete"], "listed": s["listed"], "cleanup": s["cleanup"]},
            "concurrency": {"create": s["create"], "open_edit": s["open_edit"], "set_and_save": s["set_and_save"],
                            "read_value": s["read_value"], "cleanup": s["cleanup"]},
            "pagination": {"url": app.base + "/items", "api_contains": "/api/items", "total_json_path": "totalElements"}}
    res = {r.case_id.split("-ITEMS")[0]: r for r in business_rules.run(ctx, [spec])}
    assert set(res) == {"BR-UNIQUENESS", "BR-IMMUTABILITY", "BR-SOFT-DELETE", "BR-CONCURRENCY", "BR-PAGINATION"}
    assert res["BR-PAGINATION"].status is Status.PASSED, res["BR-PAGINATION"].detail
    expect = Status.PASSED if mode == "good" else Status.FAILED
    for k in ("BR-UNIQUENESS", "BR-IMMUTABILITY", "BR-SOFT-DELETE", "BR-CONCURRENCY"):
        assert res[k].status is expect, (k, res[k].detail, res[k].reason)
    if mode == "bad":
        assert res["BR-UNIQUENESS"].meta["category"] == "data_integrity" and "ACEPTÓ" in res["BR-UNIQUENESS"].detail
        assert "pisó" in res["BR-CONCURRENCY"].detail
    else:
        assert "409" in res["BR-UNIQUENESS"].detail and "409" in res["BR-CONCURRENCY"].detail
    # Every record the checks created was cleaned up (good mode: deleted; bad mode: the app keeps "deleted" rows listed by design).
    if mode == "good":
        assert not app.active(), app.active()


def test_business_rules_undeclared_rule_is_not_executed(env):
    mode, app, ctx = env
    out = business_rules.run(ctx, [{"id": "X", "profile": "admin"}])
    assert len(out) == 1 and out[0].status is Status.NOT_EXECUTED and "no declara" in out[0].reason
    only = business_rules.run(ctx, [{"id": "P", "profile": "admin", "pagination": {"url": app.base + "/items", "api_contains": "/api/items",
                                                                                   "total_json_path": "content"}}])
    assert [r.case_id for r in only] == ["BR-PAGINATION-P"]          # undeclared rules are not padded in as NOT_EXECUTED


def test_heuristics(env):
    mode, app, ctx = env
    s = make_screen(app)
    spec = {"id": "ITEMS", "profile": "admin", "write_url_contains": "/api/items",
            "submit": {"open_form": s["open_form"], "save_selector": "#guardar", "cleanup": s["cleanup"]},
            "invalid": {"open_form": s["open_invalid"], "save_selector": "#guardar", "field_error_selector": "#err",
                        "close": lambda page: page.click("#cancelar")},
            "delete": {"prepare": s["prepare_delete"], "delete_selector": "tr[data-codigo] .del", "cleanup": s["cleanup"]}}
    res = {r.case_id.rsplit("-ITEMS", 1)[0]: r for r in heuristics.run(ctx, [spec])}
    assert set(res) == {"HEUR-DOUBLE-SUBMIT", "HEUR-BUSY-STATE", "HEUR-FIELD-ERROR", "HEUR-DELETE-CONFIRM", "HEUR-NATIVE-DIALOG",
                        "HEUR-ERROR-TRACE"}
    if mode == "good":
        for k in ("HEUR-DOUBLE-SUBMIT", "HEUR-BUSY-STATE", "HEUR-FIELD-ERROR", "HEUR-DELETE-CONFIRM", "HEUR-NATIVE-DIALOG"):
            assert res[k].status is Status.PASSED, (k, res[k].detail, res[k].reason)
        assert res["HEUR-ERROR-TRACE"].status is Status.NOT_EXECUTED          # the good app never answered 5xx
        assert any(i["codigo"] for i in app.items.values())                   # the delete flow's record exists (cancel kept it)
    else:
        dbl = res["HEUR-DOUBLE-SUBMIT"]
        # the bad app has no unique check: the server accepts every request -> duplicates created -> data integrity
        assert dbl.status is Status.FAILED and dbl.meta["category"] == "data_integrity" and "ACEPTÓ" in dbl.detail, dbl.detail
        assert res["HEUR-BUSY-STATE"].status is Status.FAILED
        assert res["HEUR-FIELD-ERROR"].status is Status.FAILED
        d = res["HEUR-DELETE-CONFIRM"]
        assert d.status is Status.FAILED and d.meta["rule"] == "DESTRUCTIVE-ACTION-NO-CONFIRM", d.detail
        assert res["HEUR-NATIVE-DIALOG"].status is Status.FAILED and "confirm" in res["HEUR-NATIVE-DIALOG"].detail
        t = res["HEUR-ERROR-TRACE"]
        assert t.status is Status.FAILED and t.security_relevant and t.meta["category"] == "sensitive_data_exposure", t.detail
        assert all(not r.security_relevant for k, r in res.items() if k not in ("HEUR-ERROR-TRACE", "HEUR-DOUBLE-SUBMIT"))
        assert all(ingest.is_finding(r) for r in res.values() if r.status is Status.FAILED)


def test_a11y_behind_login(env):
    pytest.importorskip("axe_playwright_python")
    mode, app, ctx = env
    out = a11y.run(ctx, [{"id": "ITEMS", "profile": "admin", "url": app.base + "/items"}])
    # The fixture's table buttons have visible text and the inputs have labels; whatever axe reports must be a real WCAG A/AA rule.
    for r in out:
        if r.status is Status.FAILED:
            assert r.meta["category"] == "accessibility" and r.meta["rule"].startswith("WCAG-") and not r.security_relevant
        else:
            assert r.status is Status.PASSED and "reglas WCAG" in r.detail
    assert out


def test_a11y_criterion_mapping():
    assert a11y.criterion(["cat.color", "wcag2aa", "wcag143"]) == "1.4.3"
    assert a11y.criterion(["wcag2a", "wcag1412"]) == "1.4.12"
    assert a11y.criterion(["best-practice"]) == ""
