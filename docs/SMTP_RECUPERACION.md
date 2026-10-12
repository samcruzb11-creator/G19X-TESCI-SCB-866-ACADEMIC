# SMTP, recuperación de contraseña y solicitudes de acceso

## Estado de entrega

**SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS**. La configuración local inspeccionada no contiene host, usuario, contraseña ni remitente SMTP. No hubo envío de Internet ni confirmación de llegada a un buzón. Los contratos de cola, envío TLS con dobles, single-use, expiración, replay, anti-enumeración y carreras se prueban automáticamente.

La ausencia de credenciales externas no impide evaluar login y los módulos documentales. Sí impide completar por correo una solicitud de acceso o recuperación. No sustituya el envío por mostrar tokens en pantalla/logs.

## Configuración genérica

En `api/.env` privado:

```env
SMTP_HOST=<HOST_DEL_SERVIDOR>
SMTP_PORT=587
SMTP_USERNAME=<USUARIO_AUTORIZADO>
SMTP_PASSWORD=<SECRETO_PRIVADO_DEL_PROVEEDOR>
SMTP_SECURITY=starttls
SMTP_FROM_ADDRESS=<REMITENTE_AUTORIZADO>
SMTP_FROM_NAME="Sistema de Trazabilidad"
SMTP_TIMEOUT_SECONDS=5
PUBLIC_FRONTEND_URL=http://127.0.0.1:8080
PASSWORD_RESET_TTL_SECONDS=1800
```

Los marcadores deben sustituirse localmente. Para TLS implícito utilice `SMTP_SECURITY=ssl` y el puerto que indique el servidor, habitualmente 465. Para STARTTLS utilice el puerto que indique el servidor, habitualmente 587. No se admite envío en claro. La conexión valida certificados con el contexto SSL estándar. No hay proveedor fijo ni secretos predeterminados. Si el servidor requiere password de aplicación, obténgalo mediante su proceso externo autorizado; no registre cuentas desde este proyecto.

No existen `SMTP_ENABLED`, `SMTP_USER`, `SMTP_FROM` ni `SMTP_USE_TLS`: los nombres anteriores son los del código real. El servicio valida host, remitente y URL antes de admitir operaciones que dependen de correo. Usuario vacío permite la configuración de un relay autorizado sin autenticación; eso no equivale a verificar que el relay funciona. La URL debe ser fija, sin query, fragmento ni userinfo; HTTPS salvo loopback en development. Reinicie backend tras editar configuración.

## Ejecutar el worker

Desde raíz, con la BD correcta en `.env`:

```bat
api\venv\Scripts\python.exe scripts/procesar_correo_auth.py --max-jobs 20
```

Procese después de solicitar recuperación o aprobar acceso. Es un lote de 1–100 trabajos, no un proceso permanente. Para operación continua configure su planificador local para repetirlo periódicamente, usando el directorio raíz y el ejecutable del venv. No se instala una tarea programada en Fase 9. Hasta ejecutar el worker, los mensajes permanecen en cola.

El worker resuelve el destinatario desde sujetos autorizados, no desde correo arbitrario del request; libera la transacción antes de SMTP. Usa lease, hasta tres intentos y backoff. Un retry sustituye el token anterior, conserva la expiración original y puede originar correos duplicados; SMTP no garantiza exactly-once. `Trabajos procesados` no significa entrega confirmada. El CLI evita imprimir tokens, passwords, destinatarios y excepciones del driver. No active `smtplib.set_debuglevel` ni logging de cuerpos de autenticación.

## Prueba real posterior, con buzón autorizado

Use una instalación temporal y un buzón suyo autorizado. Las identidades ficticias de evaluación no tienen buzón y no reciben correo de Internet, incluso si configura SMTP. Para preparar una cuenta sintética con dirección entregable, complete el flujo de solicitud de acceso; no cambie usuarios personales ni filas manualmente.

1. Configure SMTP privado y reinicie backend. Inicie ADMIN demo.
2. Desde Solicitar acceso, envíe una solicitud con nombre sintético y el buzón autorizado. La respuesta pública es genérica.
3. ADMIN revisa la solicitud y aprueba `RESPONSABLE_AREA` o rechaza otra solicitud de control. Aprobar genera el job de contraseña inicial; la cuenta todavía no está creada.
4. Ejecute el worker. Verifique el mensaje en el buzón, sin copiar el enlace a documentos ni consolas.
5. Abra el enlace y establezca una contraseña exclusiva de prueba. La confirmación válida crea la cuenta activa, marca la solicitud `FULFILLED` y consume el token. Inicie sesión.
6. En Recuperar contraseña solicite reset de esa cuenta. Verifique respuesta genérica; ejecute el worker y confirme llegada del correo.
7. Abra el vínculo, establezca otra contraseña de prueba y entre con la nueva. Compruebe que las sesiones anteriores fueron revocadas y que la contraseña anterior falla.
8. Intente reutilizar el vínculo: debe fallar. Compruebe el aviso de contraseña cambiada después de procesar nuevamente la cola.
9. Registre sólo fecha, status HTTP y resultado de llegada/consumo, sin token, password SMTP ni dirección personal en la evidencia pública.

## Casos negativos y concurrencia

La suite `api/tests_auth_mysql/test_account_access_mysql.py` prueba HTTP sobre schema efímero; `test_auth_mail_mysql.py` prueba leases/retries con sender sustituido. Cubren inexistente/inactivo, expirado, alterado, propósito incorrecto, replay y doble consumo concurrente. Una sola confirmación concurrente puede completar el cambio; la otra debe fallar. Los requests públicos válidos de cuentas existentes/inexistentes/inactivas mantienen el mismo cuerpo/status genérico, sujeto a límites de admisión.

Para una expiración real posterior use una instalación desechable y espere el TTL sin editar tokens persistidos; para demostrar doble confirmación use el test automatizado, no capture el token en consola. No desactive límites para el buzón real. El estado de cola puede consultarse sólo por tipo/status/conteo, sin leer destinatarios, fingerprints ni tokens.

## Solicitud de acceso

`PENDING → APPROVED → FULFILLED` tras contraseña inicial, o `PENDING → REJECTED`. ADMIN revisa/resuelve mediante la interfaz. El reenvío está acotado. El solicitante no decide rol ni se registra automáticamente; ADMIN fija el rol aprobado. El rechazo no inventa una notificación: sólo se documenta el comportamiento implementado. La infraestructura SMTP de contraseña inicial y reset es la misma.

## Impacto pendiente

Falta exclusivamente la credencial/configuración externa y un buzón autorizado para acreditar envío real y recuperación por Internet. Acción necesaria: completar los campos privados y ejecutar el procedimiento anterior. El estado actual no puede denominarse «correo real verificado».
