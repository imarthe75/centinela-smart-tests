"""A small real web application used to exercise the generic checks end to end with a real Chromium (tests only).

Two modes, one server each:
  * good: guards the admin screen and API (403), rejects duplicates (409 + message), optimistic locking (409), confirm before
          delete, Save disabled while in flight, per-field errors, no stack traces.
  * bad:  the opposite on purpose (screen and API open to the viewer, duplicates accepted, last write wins, delete without
          confirmation and with a native confirm, Save stays enabled, a 500 with a Java stack trace).
Users: admin/admin-pass (role admin), viewer/viewer-pass (role viewer). Tokens are random per login; state is in memory.
"""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USERS = {"admin": ("admin-pass", "admin"), "viewer": ("viewer-pass", "viewer")}

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{title}</title></head><body>
<main><h1>{title}</h1>{body}</main>
<script>
const MODE = "{mode}";
function token(){{ return sessionStorage.getItem("t"); }}
async function api(method, url, body){{
  const r = await fetch(url, {{method, headers: {{"Authorization": "Bearer " + token(), "Content-Type": "application/json"}},
                               body: body ? JSON.stringify(body) : undefined}});
  let data = null; try {{ data = await r.json(); }} catch(e) {{}}
  return {{status: r.status, data}};
}}
function toast(msg){{ const d = document.getElementById("toast"); d.textContent = msg; d.className = "p-toast-message"; }}
{script}
</script></body></html>"""

LOGIN = """<form id="f"><label for="email">Correo</label><input id="email" type="text" name="user">
<label for="pw">Contraseña</label><input id="pw" type="password"><button type="submit">Entrar</button></form>""", """
document.getElementById("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await fetch("/api/auth", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({u: document.getElementById("email").value, p: document.getElementById("pw").value})});
  if (r.status === 200) { const d = await r.json(); sessionStorage.setItem("t", d.access_token); location = "/home"; }
});"""

HOME = "<p>Inicio</p>" + "".join(f"<div>bloque {i}</div>" for i in range(60)), "api('GET','/api/me');"

ADMIN = "<div id='content'>Cargando</div>" + "".join(f"<span>x{i}</span>" for i in range(5)), """
(async () => {
  const me = await api("GET", "/api/me");
  if (MODE === "good" && me.data.role !== "admin") { location = "/denied"; return; }
  document.getElementById("content").textContent = "Panel de administración";
})();"""

DENIED = "<p>Acceso denegado: no tiene permiso para esta pantalla.</p>", ""

ITEMS = """<button id="nuevo">Nuevo</button><div id="toast"></div>
<table><tbody id="rows"></tbody></table><span class="p-paginator-current" id="pag"></span>
<div id="dlg" class="p-dialog" style="display:none" role="dialog">
  <label for="codigo">Código</label><input id="codigo" formcontrolname="codigo">
  <label for="nombre">Nombre</label><input id="nombre" formcontrolname="nombre">
  <small class="p-error" id="err" style="display:none">El nombre es obligatorio</small>
  <button id="guardar">Guardar</button><button id="cancelar">Cancelar</button>
</div>
<div id="cf" class="p-confirm-dialog" style="display:none" role="alertdialog"><p>¿Eliminar?</p>
  <button id="si">Sí</button><button id="no">No</button></div>""" + "".join(f"<i>{i}</i>" for i in range(40)), """
let editing = null, pendingDelete = null;
async function load(){
  const r = await api("GET", "/api/items?page=0");
  document.getElementById("rows").innerHTML = r.data.content.map(it =>
    `<tr data-codigo="${it.codigo}"><td>${it.codigo}</td><td class="nombre">${it.nombre}</td>
      <td><button class="edit" data-id="${it.id}">Editar</button><button class="del" data-id="${it.id}" aria-label="Eliminar">Eliminar</button></td></tr>`).join("");
  document.getElementById("pag").textContent = `Mostrando 1 a ${r.data.content.length} de ${r.data.totalElements}`;
}
function openDialog(item){
  editing = item; const c = document.getElementById("codigo");
  c.value = item ? item.codigo : ""; document.getElementById("nombre").value = item ? item.nombre : "";
  c.disabled = !!item && MODE === "good"; document.getElementById("err").style.display = "none";
  document.getElementById("dlg").style.display = "block";
}
document.getElementById("nuevo").onclick = () => openDialog(null);
document.getElementById("cancelar").onclick = () => { document.getElementById("dlg").style.display = "none"; };
document.getElementById("guardar").onclick = async () => {
  const btn = document.getElementById("guardar");
  const nombre = document.getElementById("nombre").value.trim();
  if (!nombre && MODE === "good") { document.getElementById("err").style.display = "block"; return; }
  if (MODE === "good") btn.disabled = true;
  const body = {codigo: document.getElementById("codigo").value, nombre};
  let r;
  if (editing) { body.version = editing.version; r = await api("PUT", "/api/items/" + editing.id, body); }
  else r = await api("POST", "/api/items", body);
  btn.disabled = false;
  toast(r.status < 300 ? "Guardado" : (r.data && r.data.message) || ("Error " + r.status));
  if (r.status < 300) { document.getElementById("dlg").style.display = "none"; await load(); }
};
document.getElementById("rows").addEventListener("click", async (e) => {
  const id = e.target.dataset.id; if (!id) return;
  if (e.target.classList.contains("edit")) { const r = await api("GET", "/api/items/" + id); openDialog(r.data); return; }
  if (MODE === "good") { pendingDelete = id; document.getElementById("cf").style.display = "block"; return; }
  if (confirm("¿Eliminar?")) {}            // bad: native dialog, and deletes regardless of the answer
  await api("DELETE", "/api/items/" + id); await load();
});
document.getElementById("no").onclick = () => { pendingDelete = null; document.getElementById("cf").style.display = "none"; };
document.getElementById("si").onclick = async () => { await api("DELETE", "/api/items/" + pendingDelete);
  document.getElementById("cf").style.display = "none"; await load(); };
load();"""

TRACE = ("java.lang.NullPointerException: x\n\tat mx.gob.app.Servicio.guardar(Servicio.java:42)\n"
         "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)")


class App:
    def __init__(self, mode: str):
        self.mode = mode
        self.tokens = {}
        self.items = {}
        self.seq = 0
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def active(self):
        return [i for i in self.items.values() if not i["deleted"]]

    def _handler(self):
        app = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _page(self, title, pair):
                body, script = pair
                self._send(200, PAGE.format(title=title, body=body, mode=app.mode, script=script), "text/html")

            def _user(self):
                auth = self.headers.get("Authorization", "")
                return app.tokens.get(auth[7:]) if auth.startswith("Bearer ") else None

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                u = urlparse(self.path)
                pages = {"/login": ("Acceso", LOGIN), "/home": ("Inicio", HOME), "/admin": ("Administración", ADMIN),
                         "/denied": ("Acceso denegado", DENIED), "/items": ("Elementos", ITEMS)}
                if u.path in pages:
                    return self._page(*pages[u.path])
                user = self._user()
                if not user:
                    return self._send(401, {"message": "sin token"})
                if u.path == "/api/me":
                    return self._send(200, {"user": user[0], "role": user[1]})
                if u.path == "/api/admin/data":
                    if user[1] != "admin" and app.mode == "good":
                        return self._send(403, {"message": "prohibido"})
                    return self._send(200, {"secret": "datos de administración"})
                if u.path == "/api/items":
                    act = app.active()
                    return self._send(200, {"content": act[:10], "totalElements": len(act)})
                if u.path.startswith("/api/items/"):
                    it = app.items.get(int(u.path.rsplit("/", 1)[1]))
                    return self._send(200, it) if it else self._send(404, {"message": "no existe"})
                return self._send(404, {"message": "no existe"})

            def do_POST(self):
                if self.path == "/api/auth":
                    b = self._body()
                    if USERS.get(b.get("u"), (None,))[0] == b.get("p"):
                        t = secrets.token_hex(16)
                        app.tokens[t] = (b["u"], USERS[b["u"]][1])
                        return self._send(200, {"access_token": t})
                    return self._send(401, {"message": "credenciales inválidas"})
                if not self._user():
                    return self._send(401, {"message": "sin token"})
                if self.path == "/api/items":
                    b = self._body()
                    if not b.get("nombre"):
                        if app.mode == "bad":
                            return self._send(500, {"message": "error", "trace": TRACE})
                        return self._send(400, {"message": "nombre obligatorio"})
                    with app.lock:
                        if app.mode == "good" and any(i["codigo"] == b["codigo"] for i in app.active()):
                            return self._send(409, {"message": "El código ya existe"})
                        app.seq += 1
                        app.items[app.seq] = {"id": app.seq, "codigo": b["codigo"], "nombre": b["nombre"], "version": 0, "deleted": False}
                    return self._send(201, app.items[app.seq])
                return self._send(404, {"message": "no existe"})

            def do_PUT(self):
                if not self._user():
                    return self._send(401, {"message": "sin token"})
                it = app.items.get(int(self.path.rsplit("/", 1)[1]))
                if not it:
                    return self._send(404, {"message": "no existe"})
                b = self._body()
                with app.lock:
                    if app.mode == "good" and b.get("version") != it["version"]:
                        return self._send(409, {"message": "El registro cambió; recargue"})
                    it["nombre"], it["version"] = b.get("nombre", it["nombre"]), it["version"] + 1
                    if app.mode == "bad":
                        it["codigo"] = b.get("codigo", it["codigo"])
                return self._send(200, it)

            def do_DELETE(self):
                if not self._user():
                    return self._send(401, {"message": "sin token"})
                it = app.items.get(int(self.path.rsplit("/", 1)[1]))
                if not it:
                    return self._send(404, {"message": "no existe"})
                it["deleted"] = app.mode == "good" or it["deleted"]      # bad: "deletes" but the row stays listed
                return self._send(200, {"ok": True})

        return H
