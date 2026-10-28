# ADR-0001 — Arquitectura y alcance de centinela-smart-tests

**Estado:** ACEPTADO (2026-10-15)

## Decisión
Proyecto separado de Centinela-AI (uso interno) para ejecutar pruebas funcionales reales. Razón: escribe datos de negocio en los sistemas
objetivo y su unidad es una ejecución de caso, no un hallazgo de seguridad con huella persistente; mezclarlo con Centinela ampliaría su
superficie y su modelo de confianza. Ver `centinela-ai/DECISIONS/0015`.

## Componentes
- `smart_tests/package.py` — lee el paquete de pruebas (xlsx `Ejecucion` + datos + UAT docx), sustituye el ciclo `{C}`, y escribe de vuelta el
  Estado **solo** de lo ejecutado.
- `smart_tests/session.py` — una sesión de navegador por perfil de prueba (login por UI, con la respuesta HTTP del login como señal).
- `smart_tests/recipes/` — recetas por framework de UI (hoy `primeng.py`).
- `smart_tests/projects/<proyecto>/` — mapeo de pantallas + `HANDLERS`/`ORDER` por aplicación (p. ej. `mi_app`).
- `smart_tests/runner.py` — orquesta; un caso sin handler es `NOT_EXECUTED`; un handler que falla es `BLOCKED`; nada se aprueba sin evidencia.
- `smart_tests/report.py` — HTML + PDF (impreso por el mismo Chromium).
- `smart_tests/ingest.py` — envía a Centinela solo los fallos con impacto de seguridad.

## Reutilización
`centinela-core` (submódulo `libs/centinela-core`): credenciales de prueba en Vault, login por API, ejecutor de navegador aislado, y el
modelo de resultado honesto.

## Límites declarados
- No deduce selectores de UI a partir de los pasos en lenguaje natural: cada pantalla se mapea una vez.
- Casos que dependen de datos o flujos que esta herramienta no crea (firma electrónica de prueba, asuntos turnados del flujo operativo,
  cuentas de servidor público relacionadas) se marcan `BLOCKED` con el motivo, nunca aprobados.
