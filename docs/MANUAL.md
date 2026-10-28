# Manual — centinela-smart-tests (módulo de pruebas funcionales)

> Ejecutor de **pruebas funcionales** (end-to-end, navegador real con Playwright) para los
> aplicativos de la organización. Produce un resultado **honesto** (nada se marca como «pasó» sin
> evidencia) y envía a Centinela-AI **solo los fallos con impacto de seguridad**. El resto del
> resultado (pases, bloqueados, no ejecutados, hallazgos funcionales no-seguridad) se queda en
> este módulo, en su reporte propio.

Versión del documento: 2026-10-19 · Mantener junto al código, no en una ruta pública.

---

## 1. Qué es y qué NO es

- **Es** un corredor de pruebas funcionales por caso: cada caso del paquete de pruebas
  tiene un *handler* que maneja el navegador, verifica el criterio de aceptación y devuelve un
  resultado con evidencia (captura o respuesta HTTP real).
- **No es** un escáner de vulnerabilidades. Eso lo hace Centinela-AI. Este módulo solo
  **alimenta** a Centinela con los fallos funcionales que además son un problema de seguridad
  (p. ej. un duplicado aceptado, una acción destructiva disponible donde no debe).
- **No inventa resultados.** Un caso sin automatización se reporta `NOT_EXECUTED`; uno que no se
  pudo correr (sin datos, sin cuenta, dependencia caída) se reporta `BLOCKED` con el motivo. Solo
  `PASSED`/`FAILED` cuentan como ejecutados, y ambos exigen evidencia.

## 2. Arquitectura

| Pieza | Rol |
|---|---|
| **centinela-core** (librería pip, repo aparte) | Modelo de resultado honesto (`results`), credenciales de prueba desde Vault (`test_credentials`), login por API (`api_login`), ejecutor de navegador en contenedor aislado (`browser`). |
| **centinela-smart-tests** (este repo) | Lector del paquete de pruebas, recetas por framework de UI (`recipes/`), proyectos con los handlers por caso (`projects/<proj>/`), runner, reporte e ingesta. |
| **centinela-ai** | Recibe la corrida completa por `POST /api/ingest/smart-tests/run` (pestaña «Pruebas funcionales») y los fallos de seguridad por `POST /api/ingest/smart-tests` (hallazgos). Ambos con el mismo token, fail-closed. |

El runner corre **dentro de un contenedor hermano aislado** (`centinela-smart-tests:dev`) en la
red `aura-network`, con Playwright en proceso. Los **secretos** (Vault, token de ingesta) se
pasan por **STDIN**, nunca por `argv` ni variables de entorno, y **jamás** se escriben en logs,
`results.json` ni evidencias (el runner aborta si un secreto llegara a aparecer en la salida).

## 3. Cómo se ejecuta

Envoltura de host (lee los secretos del `--env-file` y los pasa por STDIN):

```bash
scripts/smart-tests.sh <comando> <args.json> --env-file /ruta/.env [--package /ruta/paquete.zip] [--out /ruta/salida] [--dev]
```

Comandos:
- `inspect` — valida/lee el paquete de pruebas (xlsx) sin tocar el navegador.
- `explore` — abre una sesión y ejecuta pasos de exploración (para mapear selectores de una pantalla nueva).
- `run` — ejecuta los casos y produce resultados + reporte + ingesta.

`--dev` monta el árbol de trabajo (sin reconstruir la imagen). El `.env` aporta
`VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_NAMESPACE`, `SMART_TESTS_INGEST_URL`, `SMART_TESTS_INGEST_TOKEN`.

### `args.json` para `run`

```json
{
  "project": "mi_app",
  "package": "/pkg/package.zip",
  "cycle": "cen1015b",
  "asset": "Mi-App-Frontend",
  "cases": ["CI-59", "CI-147"]
}
```


- `project` — carpeta en `smart_tests/projects/` (p. ej. `mi_app`).
- `package` — paquete de pruebas (xlsx `Ejecucion` + datos + UAT docx), montado por `--package`.
- `cycle` — sufijo de ciclo; los registros que el runner crea lo llevan para distinguirlos de los del equipo.
- `asset` — **nombre exacto del activo en Centinela** al que se atribuirán los hallazgos de seguridad (debe existir en el inventario).
- `cases` — opcional; si se omite, corre todos los casos del paquete.
- `checks` — opcional: comprobaciones genéricas (`authz_negative`, `business_rules`, `heuristics`, `a11y`); ver §5b. Con `checks`, el
  `package` es opcional.

### Otros comandos
- `ci-report` (con `--ci /ruta/reportes`): lee JUnit XML y JaCoCo del CI del proyecto y envía el resumen a Centinela. `args.json`:
  `{"asset": "<activo>", "project": "...", "ref": "<rama>", "commit": "<sha>", "pipeline": "<id>"}`. Salida: `ci_report.json`.
- El paquete puede traer archivos `.feature` de Gherkin (con o sin xlsx): cada escenario es un caso `BDD`; id por etiqueta `@CI-59` o
  `@id:x`, requisito `@RQ-09`, actor `@actor:Rol_con_guiones_bajos` o el primer «Dado que soy …». Sin handler queda `NOT_EXECUTED`.

### Salidas (en `--out`)
- `results.json` — resultado completo por caso (estado, detalle, evidencia, sustituciones).
- `<paquete>_ejecutado.xlsx` — la hoja `Ejecucion` rellenada.
- `report.html` — reporte legible del ciclo.
- Ingesta: los fallos de seguridad se envían a Centinela (ver §5).

## 4. Modelo de resultado honesto (regla de oro)

- `PASSED` / `FAILED` → **exigen evidencia** (captura, respuesta HTTP o extracto verificable).
- `BLOCKED` / `NOT_EXECUTED` → **exigen motivo**.
- Toda **sustitución** (p. ej. el caso pide el perfil «SP-01» y se corrió con un perfil
  equivalente existente) se **declara**, no se oculta.
- El resumen (`summarize`) nunca infla: el % de éxito es sobre lo realmente ejecutado.

## 5. Ingesta a Centinela-AI (qué llega y qué no)

Solo se envía un hallazgo cuando un caso es `FAILED`, `security_relevant=True` y lleva una
`meta.category` **soportada**. Cada categoría mapea a una regla y una severidad por defecto:

| Categoría (`meta.category`) | Regla en Centinela | Severidad def. |
|---|---|---|
| `access_control` | `SMART-TESTS-ACCESS-CONTROL-FAILURE` | HIGH |
| `authentication` | `SMART-TESTS-AUTHENTICATION-FAILURE` | HIGH |
| `session_management` | `SMART-TESTS-SESSION-MANAGEMENT-FAILURE` | HIGH |
| `sensitive_data_exposure` | `SMART-TESTS-SENSITIVE-DATA-EXPOSURE` | HIGH |
| `input_validation` | `SMART-TESTS-INPUT-VALIDATION-FAILURE` | MEDIUM |
| `data_integrity` | `SMART-TESTS-DATA-INTEGRITY-FAILURE` | MEDIUM |
| `audit_logging` | `SMART-TESTS-AUDIT-LOGGING-GAP` | MEDIUM |

- `meta.severity` (CRITICAL/HIGH/MEDIUM/LOW) sobreescribe el default; una severidad inválida cae
  al default de la categoría.
- Hay alias tolerados (`authz`/`rbac`→access_control, `bitacora`/`audit`→audit_logging,
  `data_exposure`/`pii`→sensitive_data_exposure, etc.). **Una categoría no listada se rechaza**,
  no se adivina.
- La ubicación del hallazgo es `smart-tests:<project>:<case_id>`, así que **reejecutar el mismo
  caso actualiza el mismo hallazgo** (dedup por huella), no crea filas nuevas.
- El endpoint es **fail-closed**: sin `SMART_TESTS_INGEST_TOKEN` configurado → 503; token
  equivocado o ausente → 401. El activo debe existir en el inventario (si no → 404).

### Hallazgos de observación (usabilidad y accesibilidad)
Las comprobaciones genéricas también envían fallos que **no** son de seguridad, con `meta.category` = `usability` o `accessibility` y
`meta.rule` = el id de la regla estática equivalente. Centinela solo acepta: usabilidad → `ANGULAR-SUBMIT-NO-BUSY-GUARD`,
`DESTRUCTIVE-ACTION-NO-CONFIRM`, `NATIVE-BROWSER-DIALOG`, `SMART-TESTS-FORM-INVALID-SUBMITTED`, `SMART-TESTS-FORM-NO-FIELD-ERROR`
(informativos); accesibilidad → `WCAG-<criterio>-AXE-<regla>` con un criterio WCAG 2.1 A/AA. Cualquier otra regla se rechaza.

## 5b. Comprobaciones genéricas (ADR-0002)
El proyecto declara en `CHECKS` (p. ej. `projects/<proyecto>/checks_map.py`) qué necesita cada comprobación; el motor sabe la regla y el
proyecto sabe su pantalla (funciones que reciben `ctx`, `page` y un `tag` único para sus datos).
| Comprobación | Casos que produce | Pasa si… |
|---|---|---|
| `authz_negative` | `AUTHZ-NEG-<id>` | la navegación directa termina denegada, la acción no se ve y la API responde 401/403 al perfil sin permiso. Una sonda que no es GET exige `write_probe: true` |
| `business_rules` | `BR-<regla>-<id>` | unicidad: 2.º alta rechazada con mensaje de duplicado (409); inmutabilidad: identificadores deshabilitados; borrado lógico: deja de listarse; concurrencia: la 2.ª sesión recibe 409; paginación: total del paginador = API |
| `heuristics` | `HEUR-<regla>-<id>` | doble clic = 1 escritura; botón ocupado durante la petición; formulario inválido no se envía y muestra error; eliminar pide confirmación; sin diálogos nativos; sin trazas en errores 5xx |
| `a11y` | `A11Y-<id>[-<regla>]` | 0 reglas WCAG 2.1 A/AA incumplidas por axe-core en la pantalla autenticada |
- Una regla que el mapa no declara queda `NOT_EXECUTED` con el motivo; una pantalla que no renderiza queda `BLOCKED`.
- La retención de la petición en «botón ocupado» solo agrega latencia en el navegador; la respuesta es la del servidor real.
- Los registros creados llevan `<ciclo><4 hex>` y se eliminan al terminar; una limpieza fallida se escribe en el detalle del caso.

## 6. Cómo etiquetar un caso con categoría (para que su fallo llegue a Centinela)

En los proyectos, los handlers usan los helpers `result()`/`_result()`. Basta pasar `category=`:

```python
return k.result(case, Status.PASSED if rejected else Status.FAILED,
                "Correo duplicado: ...", ev, category="data_integrity")
```

La categoría y la marca de seguridad se adjuntan **solo cuando el caso FALLA** (el modelo
prohíbe marcar seguridad en un no-FAILED), así que el mismo handler queda como un `PASSED` limpio
cuando la verificación pasa. Si el fallo **no** tiene impacto de seguridad (p. ej. una etiqueta
de UI incorrecta), **no** se pone categoría.

## 7. Cómo agregar una pantalla / un caso

1. Mapea los selectores con `explore` (o reutiliza `recipes/<framework>.py`; hoy `primeng.py`).
2. Escribe un handler `def ci_XX(ctx, case): ...` en `smart_tests/projects/<proj>/<pantalla>.py`
   que maneje el navegador (`s, page = ...`), verifique el criterio y devuelva `k.result(...)`
   con evidencia. Usa `ctx.session("<perfil>")` para una sesión ya autenticada del perfil.
3. Regístralo en `HANDLERS`/`ORDER` del proyecto.
4. Si su fallo tiene impacto de seguridad, etiquétalo con `category=` (§6).

## 8. Cómo agregar un proyecto (aplicativo) nuevo

1. Crea `smart_tests/projects/<nuevo>/` con `HANDLERS` (y opcional `ORDER`, `SUBSTITUTION_NOTICE`).
2. Carga las credenciales de los perfiles en **Vault** (ver la plantilla de requisitos).
3. Registra el aplicativo como **activo** en Centinela (para la atribución de hallazgos).
4. Entrega el paquete de pruebas (xlsx + datos + UAT).
5. Llena la **plantilla de requisitos** (`docs/PLANTILLA_REQUISITOS_PRUEBAS.md`).

## 9. Credenciales de prueba (Vault)

Un juego por perfil (rol), **solo** en Vault (KV v2), en `<namespace>/authz/<asset>`:
- `base_url`, `app_login` (login por API, compartido), `login_ui` (pantalla de login del navegador),
  y `roles` (nombre, usuario, contraseña por rol).
- Los secretos **nunca** se devuelven en texto (solo usuario y `has_password`) ni se escriben en
  resultados/evidencias. No se envían por chat ni correo: los carga quien tenga acceso a Vault.

## 10. Pruebas del propio módulo
`tests/test_checks_live_browser.py` corre cada comprobación con Chromium real contra `tests/fixtures/fixture_app.py` (aplicación web real
en memoria, variantes «correcta» y «defectuosa»). No hay respuestas simuladas.

```bash
scripts/run_tests.sh          # corre la suite unitaria dentro del contenedor
```

## 11. Gotchas

- La imagen corre como `pwuser`; los contenedores de prueba necesitan `--user root` + workdir `/tmp`
  (ya lo maneja la envoltura).
- `set_app_config()` de `test_credentials` es **reemplazo completo** (borra login_ui/app_login si
  van en None); para cambiar solo endpoints usa `update_authz()` (parcial).
- Un caso **BLOCKED** no puede marcarse como relevante para seguridad (el modelo lo prohíbe): un
  fallo que solo se puede dejar como bloqueado no llega a Centinela hasta que se desbloquee y
  realmente falle.

---

Ver también: `docs/PLANTILLA_REQUISITOS_PRUEBAS.md` (qué hace falta para probar un aplicativo) y
`docs/PLAN.md` (fases y decisiones del módulo).
