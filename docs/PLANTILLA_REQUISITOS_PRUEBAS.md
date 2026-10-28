# Plantilla de requisitos para pruebas funcionales — centinela-smart-tests

> Llena esta plantilla por **cada aplicativo/módulo** que se quiera probar. Sin estos datos, las
> pruebas quedan **BLOQUEADAS** (y así se reportan, no se inventan). No escribas contraseñas en
> este documento: las credenciales van a **Vault** (ver §4). Entrega el documento lleno al
> responsable de centinela-smart-tests.

Fecha: __________  ·  Llenado por: __________  ·  Ciclo/propósito: __________

---

## 1. Identificación del aplicativo
- Nombre del aplicativo/módulo: __________
- Área / dueño del producto: __________
- Contacto técnico (nombre y medio): __________
- Repositorio (GitLab, instancia y ruta) y rama: __________

## 2. Activo en Centinela (para atribuir los hallazgos)
- Nombre EXACTO del activo (`asset_name`) tal como existe en el inventario: __________
  - *Si no existe aún, indícalo; debe registrarse antes de correr.*
- Tipo de activo: ☐ URL ☐ GitLab-Repo ☐ otro: __________

## 3. Entornos y URLs (debe ser NO productivo)
- Frontend (URL de QA/pruebas): __________
- Backend / API (URL base): __________
- ¿Es un ambiente de pruebas aislado (sin datos reales de producción)? ☐ Sí ☐ No → explicar: __________
- Restricciones de red / VPN para alcanzar el ambiente: __________

## 4. Perfiles (roles) y cuentas de prueba
Lista cada rol que las pruebas deben ejercer. **Las contraseñas van a Vault, no aquí.**

| Rol / perfil | Usuario | ¿Cuenta ya existe? | Cómo se activa (p. ej. correo yopmail) | Quién la provee |
|---|---|---|---|---|
| __________ | __________ | ☐ Sí ☐ No | __________ | __________ |
| __________ | __________ | ☐ Sí ☐ No | __________ | __________ |
| __________ | __________ | ☐ Sí ☐ No | __________ | __________ |

- ¿Hay cuentas que requieran activación por correo (yopmail u otro)? ☐ Sí ☐ No → cuáles: __________
- Si un rol no se puede crear, ¿hay un perfil equivalente aceptable? (se declarará como sustitución): __________

## 5. Carga de credenciales en Vault
Las credenciales de cada perfil se guardan en Vault (KV v2) en `<namespace>/authz/<asset>`.
- ¿Quién tiene acceso para cargarlas en Vault?: __________
- Namespace de Vault a usar (si no es el default): __________
- Confirmar: ☐ las contraseñas se entregarán SOLO por Vault (no por chat/correo/este documento).

## 6. Configuración de inicio de sesión
Login por navegador (`login_ui`):
- URL de la pantalla de login: __________
- Selectores de usuario / contraseña / botón (si no son estándar): __________ / __________ / __________

Login por API (`app_login`, opcional, si aplica):
- Endpoint de autenticación (método y URL): __________
- Campos de usuario / contraseña en el cuerpo: __________ / __________
- Dónde viene el token en la respuesta y en qué cabecera se envía: __________

## 7. Paquete de pruebas
- ¿Se entrega el paquete (xlsx con hoja `Ejecucion` + datos + UAT docx)? ☐ Sí ☐ No
- Ruta / quién lo entrega: __________
- Nombre del módulo/artefacto que cubre: __________

## 8. Datos de prueba requeridos
- Catálogos / registros base que deben existir antes de correr: __________
- Dependencias entre casos (qué debe crearse primero): __________
- Archivos de ejemplo necesarios (PDF, adjuntos, etc.): __________

## 9. Alcance y criterios
- Pantallas / requerimientos (RQ) a cubrir en este ciclo: __________
- Casos prioritarios: __________
- Criterios de aceptación especiales o fuera de lo documentado: __________

## 10. Restricciones y autorizaciones
- Acciones destructivas permitidas en el ambiente (borrar, desactivar): ☐ Sí ☐ No → cuáles: __________
- ¿Prohibido tocar ciertos datos/registros? → cuáles: __________
- Ventana de ejecución autorizada (fechas/horario): __________
- Si se requiere análisis activo (DAST/escaneo) además de funcional: ☐ autorizado ☐ no → por quién: __________

## 11. Entrega de resultados
- A quién se entregan el reporte y los hallazgos: __________
- ¿Los fallos con impacto de seguridad deben ingresar a Centinela? ☐ Sí ☐ No
  - *(Si sí: confirmar el `asset_name` de §2 y que exista en el inventario.)*

---

### Checklist mínimo para poder EJECUTAR (todo lo marcado debe estar listo)
- ☐ Activo registrado en Centinela (§2)
- ☐ URL de QA alcanzable y no productiva (§3)
- ☐ Al menos un perfil con cuenta activable (§4) y credenciales en Vault (§5)
- ☐ Configuración de login conocida (§6)
- ☐ Paquete de pruebas entregado (§7)
- ☐ Datos base y dependencias disponibles (§8)
- ☐ Ventana y autorizaciones confirmadas (§10)

*Lo que no esté listo se reportará como BLOQUEADO con su motivo; nunca como «pasó».*
