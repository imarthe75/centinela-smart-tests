"""One logged-in browser context per test profile. Runs INSIDE the smart-tests container (Playwright in-process).

Secrets: the profile (username/password) comes from Vault through centinela_core; it is never written to logs, results or evidence.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from centinela_core.results import Evidence

logger = logging.getLogger(__name__)

_USER_SEL = "input#email, input[type=email], input[name*=user i], input[name*=correo i], input[formcontrolname*=email i], input[type=text]"
_PASS_SEL = "input[type=password]"
_SUBMIT_SEL = "button[type=submit], button:has-text('Iniciar'), button:has-text('Entrar'), input[type=submit]"


class LoginError(RuntimeError):
    pass


class Session:
    def __init__(self, browser, profile: Dict[str, Any], evidence_dir: Path, label: str):
        self.profile = profile
        self.label = label
        self.evidence_dir = evidence_dir
        self.ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 950}, locale="es-MX")
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self._shots = 0
        # Bearer token the APP itself sends to its API, kept in memory only (never logged or written). It lets a check call the
        # API as this profile (e.g. the negative-authorization probe) exactly as the browser would.
        self._bearer: Optional[str] = None
        self.ctx.on("request", self._capture_bearer)

    def _capture_bearer(self, request) -> None:
        try:
            auth = request.headers.get("authorization", "")
        except Exception:
            return
        if auth.lower().startswith("bearer "):
            self._bearer = auth[7:].strip()

    @property
    def has_bearer(self) -> bool:
        return bool(self._bearer)

    def api(self, method: str, url: str, body: Optional[Any] = None, timeout: int = 20000):
        """Call the application's API as this profile: the browser context's cookies plus the bearer the app was seen sending."""
        headers = {"Authorization": f"Bearer {self._bearer}"} if self._bearer else {}
        kw: Dict[str, Any] = {"method": method.upper(), "headers": headers, "timeout": timeout, "fail_on_status_code": False}
        if body is not None:
            kw["data"] = body
        return self.ctx.request.fetch(url, **kw)

    # ------------------------------------------------------------------ login
    def login(self) -> None:
        ui = self.profile.get("login_ui") or {}
        app = self.profile.get("app_login") or {}
        if not ui.get("url"):
            raise LoginError(f"el perfil «{self.profile['name']}» no tiene URL de inicio de sesión en navegador (login_ui)")
        p = self.page
        # `domcontentloaded` en vez de `networkidle`: algunas apps (p. ej. con notificaciones en vivo) abren un websocket STOMP que mantiene
        # la red activa y haría que networkidle nunca se cumpla. El .fill() siguiente espera por sí mismo al campo.
        p.goto(ui["url"], wait_until="domcontentloaded", timeout=45000)
        p.locator(ui.get("user_selector") or _USER_SEL).first.fill(self.profile["username"])
        p.locator(ui.get("pass_selector") or _PASS_SEL).first.fill(self.profile["password"])
        api_path = urlparse(app.get("url", "")).path or "auth"
        try:
            with p.expect_response(lambda r: api_path in r.url, timeout=25000) as ri:
                p.locator(ui.get("submit_selector") or _SUBMIT_SEL).first.click()
            status = ri.value.status
        except Exception as e:
            raise LoginError(f"no hubo respuesta del inicio de sesión de «{self.profile['name']}»: {e}") from e
        if status >= 400:
            raise LoginError(f"el inicio de sesión de «{self.profile['name']}» respondió HTTP {status}")
        # La app navega del lado del cliente (SPA) tras el login; esperamos a dejar la pantalla de login en vez de
        # `networkidle` (que un websocket persistente impediría). El check de abajo confirma que realmente se salió.
        login_path = urlparse(ui["url"]).path.rstrip("/")
        try:
            p.wait_for_url(lambda u: urlparse(u).path.rstrip("/") != login_path, timeout=30000)
        except Exception:
            pass
        p.wait_for_timeout(1200)
        if urlparse(p.url).path.rstrip("/") == login_path:
            raise LoginError(f"tras iniciar sesión como «{self.profile['name']}» la página sigue en la pantalla de inicio de sesión")

    # ------------------------------------------------------------------ evidence
    def shot(self, name: str, note: str = "") -> Evidence:
        self._shots += 1
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]
        path = self.evidence_dir / f"{safe}_{self._shots:02d}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception:
            logger.error("no se pudo tomar la captura %s", path, exc_info=True)
            return Evidence("text", f"captura fallida: {name}", note)
        return Evidence("screenshot", path.name, note)

    def close(self) -> None:
        try:
            self.ctx.close()
        except Exception:
            logger.error("error al cerrar el contexto del navegador", exc_info=True)


def http_evidence(resp, note: str = "") -> Evidence:
    req = resp.request
    body = ""
    try:
        body = (resp.text() or "")[:240]
    except Exception:
        body = "(cuerpo no legible)"
    return Evidence("http", f"{req.method} {urlparse(resp.url).path} -> {resp.status}", (note + " " + body).strip())


def mask(text: str, secrets) -> str:
    out = text or ""
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


def screenshot_dir(out_dir: Path) -> Path:
    d = out_dir / "evidencia"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_profile_label(actors: Dict[str, str], actor_key: str) -> Optional[str]:
    return actors.get(actor_key)
