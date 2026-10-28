# ADR-0002 — Integración de las skills de pruebas al ejecutor

**Estado:** IMPLEMENTADO (2026-10-28) · **Fecha:** 2026-10-27

## Contexto
El paquete de skills compartido (`centinela-ai/skills/`, versión 1.0 del 2026-10-27) consolidó las skills de pruebas que existían en los
repositorios del grupo `starters/` y en `centinela-core`:

| Skill | Nivel | Qué prueba |
|---|---|---|
| `test-driven-development` | unitario | ciclo rojo-verde; caso que pasa y caso que falla |
| `backend-pruebas-unitarias` | unitario / integración | servicios (JUnit 5 + Mockito), slices con seguridad (401/403 por rol), repositorios con Testcontainers, conflicto de versión (409) |
| `generacion-pruebas-servicios` | unitario | servicios Angular con `HttpTestingController` (Karma/Jasmine) |
| `bdd-spec-driven-development` | integración | reglas de negocio → Gherkin → pruebas Spring (`MockMvc`) |
| `bdd-frontend-playwright` | interfaz con API simulada | componentes Angular reales con la red simulada (`page.route`) |
| `frontend-heuristicas-usabilidad` | funcional / usabilidad | heurísticas de Nielsen verificables (carga visible, doble envío, confirmación, errores por campo, accesibilidad) |

`centinela-smart-tests` ejecuta casos funcionales **contra el ambiente desplegado** (backend y base reales, perfiles por rol en Vault), con
estado honesto (`centinela_core.results`). Las pruebas unitarias y de interfaz con API simulada pertenecen al CI de cada proyecto; lo que
sí aporta el ejecutor es lo que solo se puede comprobar con la aplicación real.

## Decisión propuesta
Incorporar, en este orden, cinco capacidades. Ninguna duplica un motor de Centinela.

### 1. Caso negativo de autorización por rol (prioridad alta)
Por cada caso que modifica datos, ejecutar además el mismo paso con un perfil **sin** el permiso y esperar que la acción no aparezca, que la
navegación directa termine en «acceso denegado» y que la API responda 403. Es la versión real de los escenarios 403 que piden
`backend-pruebas-unitarias` y `bdd-frontend-playwright`. Un fallo es un fallo de control de acceso y ya tiene canal de ingesta
(`POST /api/ingest/smart-tests`). Requiere: un mapa permiso → perfil sin permiso en `projects/<n>/`.

### 2. Comprobaciones de reglas de negocio genéricas (prioridad alta)
De la lista de verificación de `bdd-spec-driven-development`, las que el ejecutor puede probar sin conocer el dominio:
- **Unicidad:** dar de alta dos veces el mismo registro → el segundo muestra el mensaje de duplicado (HTTP 409), no un error genérico.
- **Inmutabilidad:** en edición, los campos identificadores están deshabilitados.
- **Borrado lógico:** lo eliminado deja de aparecer en el listado.
- **Concurrencia:** dos sesiones abren el mismo registro, ambas guardan → la segunda recibe el conflicto (409) y no pisa a la primera.
- **Paginación:** el total del paginador coincide con la respuesta de la API.
Cada comprobación se declara por pantalla en el mapa del proyecto; las que no aplican quedan `NOT_EXECUTED` con motivo.

### 3. Pasada de heurísticas por pantalla (prioridad media)
Del checklist de `frontend-heuristicas-usabilidad`, con evidencia de red y captura:
- doble clic en Guardar → contar las peticiones de escritura (debe ser 1);
- botón deshabilitado o `[loading]` mientras la petición está en curso;
- eliminar sin confirmación → falla; diálogo nativo (`page.on("dialog")`) → falla;
- error de validación con mensaje por campo; error del servidor sin traza en pantalla.
Se ingesta como hallazgos informativos con los mismos identificadores que los detectores estáticos (`ANGULAR-SUBMIT-NO-BUSY-GUARD`,
`DESTRUCTIVE-ACTION-NO-CONFIRM`, `NATIVE-BROWSER-DIALOG`) más la marca de que se observó en ejecución.
**No incluye accesibilidad con axe-core:** Centinela ya la cubre con `auditor_a11y_render.py` (`wcag-render`); el ejecutor solo aporta las
pantallas detrás del login si se decide compartir la sesión con ese motor (decisión pendiente 2).

### 4. Lectura de especificaciones Gherkin (prioridad media)
Aceptar, además de la hoja `Ejecucion` del paquete de pruebas, archivos `.feature` generados con las skills BDD (`e2e/features/**`,
`src/test/resources/features/**`) como fuente de casos. Los pasos siguen necesitando el mapa de pantallas; el `.feature` aporta el caso, el
actor y el resultado esperado.

### 5. Ingesta de resultados de CI (prioridad baja)
Recibir los reportes JUnit XML / JaCoCo del CI del proyecto para mostrar en Centinela, junto a los casos funcionales, si existen las pruebas
de 403 y 409 que exigen las skills. Solo lectura: no ejecuta las pruebas del proyecto.

## Reglas que se mantienen
- Ningún resultado simulado se reporta como aprobado; las comprobaciones contra el ambiente real nunca usan `page.route`.
- Los datos creados llevan el sufijo del ciclo; las comprobaciones de unicidad y concurrencia limpian lo que crean.
- Los secretos siguen viajando por stdin.

## Decisiones tomadas (2026-10-28)
1. **Las comprobaciones son opt-in por corrida:** `args["checks"]` (`authz_negative`, `business_rules`, `heuristics`, `a11y`). Nada corre por
   omisión, porque reglas de negocio y heurísticas crean registros (con sufijo del ciclo, eliminados al terminar). Una comprobación pedida que
   el proyecto no declara da un `NOT_EXECUTED` con el motivo. Una corrida puede ser solo de comprobaciones (sin paquete).
2. **Accesibilidad detrás del login se hace aquí** (`checks/a11y.py`, axe-core 4 vía `axe-playwright-python==0.1.8`, la misma versión que
   `wcag-render`), no compartiendo la sesión con Centinela: la sesión autenticada nunca sale del contenedor. El hallazgo usa el mismo id
   `WCAG-<criterio>-AXE-<regla>`.
3. **La ingesta de CI vive en los dos lados:** el lector (`ci_report.py`, comando `ci-report`) aquí; el almacenamiento y la vista en Centinela
   (`POST /api/ingest/smart-tests/ci`, tabla `ci_test_reports`, sección «Reportes de CI» de la pestaña Pruebas funcionales).

## Implementación
| Capacidad | Módulo | Resultado en Centinela |
|---|---|---|
| 1. Autorización negativa | `checks/authz_negative.py` | API que ejecuta para un perfil sin permiso → `SMART-TESTS-ACCESS-CONTROL-FAILURE`; pantalla abierta con API que niega → falla sin marca de seguridad |
| 2. Reglas de negocio | `checks/business_rules.py` | unicidad/inmutabilidad/borrado lógico/concurrencia → `SMART-TESTS-DATA-INTEGRITY-FAILURE` cuando aplica; paginación → falla funcional |
| 3. Heurísticas | `checks/heuristics.py` | `ANGULAR-SUBMIT-NO-BUSY-GUARD`, `DESTRUCTIVE-ACTION-NO-CONFIRM`, `NATIVE-BROWSER-DIALOG`, `SMART-TESTS-FORM-*` (informativos); traza en un error → `SMART-TESTS-SENSITIVE-DATA-EXPOSURE` |
| 3b. Accesibilidad autenticada | `checks/a11y.py` | `WCAG-<criterio>-AXE-<regla>` |
| 4. Gherkin | `gherkin.py`, `package.load` | casos `BDD` en la corrida (sin handler → `NOT_EXECUTED`) |
| 5. CI | `ci_report.py`, comando `ci-report` | fila en `ci_test_reports`; pruebas 401/403/409 detectadas por nombre |

Verificación: `tests/test_checks_live_browser.py` ejecuta cada comprobación con Chromium real contra una aplicación web real local
(`tests/fixtures/fixture_app.py`) en dos variantes: la correcta debe aprobar todo y la defectuosa debe fallar cada comprobación por su motivo.
