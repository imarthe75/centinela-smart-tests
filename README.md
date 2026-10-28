# centinela-smart-tests

Ejecutor de **pruebas funcionales** reales sobre aplicaciones web, con evidencia y estado honesto por caso. Uso interno. Parte del
ecosistema Centinela; reutiliza `centinela-core` (submódulo) y, para los fallos con impacto de seguridad, se integra con `centinela-ai`
por API. Ver `docs/PLAN.md` y `DECISIONS/`.

## Qué hace
Dado un **paquete de pruebas** (formato de la metodología: hoja `Ejecucion` del `Juego_datos_pruebas_*.xlsx` + hojas de datos, y opcionalmente los
UAT de `ART-F4-03_*.docx`) y **credenciales de prueba por perfil** (en Vault, vía `centinela-core`), ejecuta cada caso en un navegador
real (Playwright/Chromium) y produce:
- `results.json` — resultado por caso (`centinela_core.results`: `PASSED`/`FAILED` exigen evidencia; `BLOCKED`/`NOT_EXECUTED` exigen motivo).
- `<libro>_ejecutado.xlsx` — copia del libro con Estado/Bloqueado por/Evidencia/Hallazgo llenados **solo** para lo ejecutado.
- `reporte.html` / `reporte.pdf` — reporte legible.
- `evidencia/` — capturas de pantalla.
- envío a `centinela-ai` de **solo** los fallos con impacto de control de acceso (si está configurado el token de ingesta).

Nada que no se ejecutó se reporta como aprobado.

## Uso
```bash
scripts/smart-tests.sh inspect args.json --env-file /ruta/.env --package /ruta/paquete.zip --out ./out
scripts/smart-tests.sh run     args.json --env-file /ruta/.env --package /ruta/paquete.zip --out ./out
```
`args.json` (para `run`): `{"project":"mi_app","package":"/pkg/package.zip","cycle":"c1","asset":"<nombre del activo>","cases":["CI-59",...]}`
(`cases` es opcional; sin él se intentan todos los del paquete). Los secretos (Vault, token de ingesta) se leen del `--env-file` y viajan
al contenedor por **stdin**, nunca en argv ni variables de entorno. `--dev` monta el código sin reconstruir la imagen.

Variables del `.env`: `VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_NAMESPACE`, y opcionalmente `SMART_TESTS_INGEST_URL` / `SMART_TESTS_INGEST_TOKEN`.

## Comprobaciones genéricas (ADR-0002)
Además de los casos del paquete, una corrida puede pedir comprobaciones que no dependen del dominio, con `"checks": [...]` en `args.json`:
| Comprobación | Qué verifica | Requiere en el proyecto |
|---|---|---|
| `authz_negative` | Un perfil **sin** el permiso no abre la pantalla, no ve la acción y la API le responde 401/403 | `CHECKS["authz_negative"]` |
| `business_rules` | Unicidad (409 con mensaje), identificadores inmutables, borrado lógico, concurrencia (409), total del paginador = API | `CHECKS["business_rules"]` |
| `heuristics` | Doble clic = 1 petición, botón ocupado, errores por campo, confirmación al eliminar, sin diálogos nativos, sin trazas | `CHECKS["heuristics"]` |
| `a11y` | WCAG 2.1 A/AA con axe-core en pantallas **detrás del login** | `CHECKS["a11y"]` |
Nada corre por omisión. Lo que crean llevan el ciclo como sufijo y se eliminan al terminar (si la limpieza falla, se dice en el detalle).
Una corrida puede ser solo de comprobaciones (sin `package`). Los fallos de usabilidad y accesibilidad llegan a Centinela como hallazgos
informativos/WCAG; los de seguridad, como hallazgos `SMART-TESTS-*`.

## Gherkin y CI
- El paquete puede traer archivos `.feature` (con o sin el libro xlsx): cada escenario es un caso `BDD` (`@CI-59`/`@id:x` = id, `@RQ-09`,
  `@actor:Rol_con_guiones_bajos`). Sin handler, el caso queda `NOT_EXECUTED`.
- `scripts/smart-tests.sh ci-report args.json --ci /ruta/reportes --env-file .env` lee JUnit XML y JaCoCo, y envía el resumen a Centinela
  (`args.json`: `{"asset": ..., "project": ..., "ref": ..., "commit": ..., "pipeline": ...}`). No ejecuta las pruebas del proyecto.

## Proyectos
Cada aplicación objetivo es un paquete en `smart_tests/projects/<nombre>/` que mapea sus pantallas (selectores reales) y define un
`HANDLERS` {id de caso -> función} y un `ORDER`. La copia pública no incluye proyectos de aplicaciones reales: cada equipo agrega el suyo, con su mapa de
comprobaciones genéricas en `projects/<proyecto>/checks_map.py`.

Las **recetas por framework de UI** viven en `smart_tests/recipes/` (hoy `primeng.py`): cómo clicar un radio de PrimeNG (es su `<label>`),
expandir un `p-treetable`, leer un diálogo. Un proyecto nuevo con otro framework añade su receta.

## Credenciales y datos de prueba
- Los perfiles (usuario/contraseña por rol) se guardan en Vault con `centinela-core` (mismo secreto que usa `centinela-ai`).
- Un caso que pide una persona del juego de datos que no existe en el ambiente se ejecuta con el perfil equivalente disponible y lo
  **declara** como sustitución en el resultado; nunca se inventa el dato.
- Los registros que el ejecutor crea en el ambiente llevan el ciclo como sufijo para no confundirse con la ejecución oficial del equipo.

## Pruebas
```bash
scripts/run_tests.sh          # unitarias + comprobaciones con Chromium real contra una app local de prueba; no requieren la app objetivo
```

## Reglas
Sigue el marco `resident-agent-os` (ver `.agent/`, `rules/`, `verifiers/`).
