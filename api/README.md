# API — Sistema de Trazabilidad Documental

## Requisitos

- Python 3.14
- XAMPP con MySQL iniciado y una base de datos llamada `sistema_trazabilidad`

## Preparar el entorno

Desde una terminal PowerShell, entra a la carpeta `api`:

```powershell
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con la configuración local de MySQL. No subas este archivo a Git. En XAMPP, inicia MySQL y crea la base de datos indicada arriba. Las migraciones Alembic versionan el esquema; revisa y aplica las pendientes antes de desplegar una versión nueva.

## Ejecutar

Desde `api` y con el entorno virtual activado:

```powershell
uvicorn app.main:app --reload
```

Hardening local 6B.4A: [operación, límites, migración 003 y pruning](../docs/FASE_6B_4A_AUTH_HARDENING.md).
El presupuesto global requiere **un único proceso FastAPI**. `--reload` es solo desarrollo;
reinicia el estado global en memoria, pero los buckets MySQL persisten. Desplegar 003 antes
del código nuevo.

Fase 6C: [solicitudes de acceso, recuperación y cola de correo](../docs/FASE_6C_ACCESO_RECUPERACION.md).
El código 6C requiere también la revisión **004**, además de 002/003. Las pruebas
crean esquemas temporales aleatorios; no aplican migraciones a la BD de trabajo.
El correo se procesa mediante CLI Python y configuración SMTP privada, sin SMTP en PHP.

Fase 6B.4B: [Turnstile adaptativo, configuración y pruebas](../docs/FASE_6B_4B_TURNSTILE.md).
Con `TURNSTILE_MODE=enabled`, FastAPI decide y verifica los desafíos de login,
solicitud de acceso y solicitud de recuperación. Requiere secreto privado y
allowlist exacta de hostnames; PHP recibe únicamente la sitekey pública.
`disabled` es el valor local inicial explícito de `.env.example`: conserva todos
los límites anteriores pero no ofrece la segunda capa anti-bot. Cambiarlo exige
reiniciar. No hay fallback automático ante caídas de Cloudflare.
No requiere migración 005. Se conserva el requisito de un solo proceso API.
Las pruebas normales usan doubles de Siteverify, nunca Internet ni SMTP real.
Siteverify limita la lectura a 16 KiB, rechaza JSON ambiguo y valida el timestamp
antes de readmitir la operación. Los fixtures bloquean conexiones a la BD de la
aplicación; toda regresión MySQL, incluida 6A, usa un esquema temporal aleatorio.

La ruta `GET /` devuelve el estado básico de la API. La documentación interactiva está en <http://127.0.0.1:8000/docs>.

Para una instalación local en 004 sin ADMIN activo, consulte el
[bootstrap inicial del primer ADMIN](../docs/FASE_6D_1_BOOTSTRAP_ADMIN.md).
La CLI solicita credenciales interactivas ocultas, fija el rol ADMIN y se
deshabilita lógicamente al existir un ADMIN activo; no modifica otros usuarios.

Fase 7A: [ciclo de auditorías, permisos y operación de 005](../docs/FASE_7A_AUDITORIAS.md).
005 agrega únicamente IN_REVIEW al CHECK; no cambia 001–004. En instalaciones
nuevas, provisionar primero el ADMIN en 004 con la herramienta existente.

Fase 7B: [hallazgos y gestión integral de evidencias](../docs/FASE_7B_HALLAZGOS_EVIDENCIAS.md).
Reutiliza el schema **005**; no requiere migración 006.

Fase 7C: [rondas y decisiones de aprobación por versión documental](../docs/FASE_7C_APROBACIONES.md).
Reutiliza RondaAprobacion/DecisionAprobacion en **005**, sin migración adicional.
La identidad del aprobador y el resultado se determinan en backend.

Fase 7D: [dashboard ejecutivo, alertas derivadas e indicadores con scope SQL](../docs/FASE_7D_DASHBOARD_ALERTAS_INDICADORES.md).
Cuatro GET bajo `/api/v1/dashboard`: resumen, indicadores, alertas y actividad.
Usa schema **005**, sin migración 006. Porcentajes separados, null/NO_DATA con
denominador cero y permisos de lectura/historial existentes. Mantener MySQL/InnoDB
REPEATABLE READ para coherencia de la respuesta completa.

Fase 7E: [análisis documental determinista y explicable](../docs/FASE_7E_ANALISIS_INTELIGENTE.md).
Cuatro GET autenticados bajo `/api/v1/analisis`: resumen, anomalías, documentos/{id}
y versiones/{id}. Reutiliza schema **005**, sin migración nueva ni servicios IA.
Scope antes de comparar hashes, explicación por regla y barrera fresca de permisos.
`ANALYSIS_SIMILARITY_THRESHOLD` configura similitud local (0.92 por defecto, 0.8–1).
Storage/similitud acotados se consultan en detalle; 409 por cambio concurrente de
alcance requiere una nueva consulta. Mantener REPEATABLE READ. El análisis devuelve
la conexión de su snapshot antes de abrir la transacción de autorización fresca.

## Verificación Fase 8

Las versiones documentales aplican `MAX_DOCUMENT_FILE_BYTES` (20 MiB por defecto)
en streaming; `MAX_EVIDENCE_FILE_BYTES` conserva el límite de evidencias.
La recepción completa del multipart se limita al máximo del archivo más 128 KiB
para metadatos; JSON y otras solicitudes mutativas admiten hasta 1 MiB. Se cuentan
los bytes recibidos incluso sin `Content-Length`, antes de expandir el contenido.
Los límites PHP pueden ser más restrictivos. La configuración `STORAGE_PATH`
no permite redirigir el storage real; las pruebas inyectan `StorageService`
con una raíz temporal explícita.

La publicación atómica usa enlaces físicos para rechazar colisiones sin sobrescribir
archivos; el filesystem del storage debe admitirlos (NTFS/ext4). La admisión asíncrona
limita el trabajo SQL a la capacidad del pool antes de ocupar workers síncronos.
La admisión SQL ocurre después de leer el cuerpo para que uploads incompletos
no reserven conexiones ni impidan atender otras consultas.
El análisis admite dos consultas simultáneas por proceso para evitar contención
de temporales MySQL; ambas admisiones mantienen una cola acotada.

Las regresiones integrales y el benchmark se documentan en
[FASE_8_QA_SEGURIDAD_RENDIMIENTO.md](../docs/FASE_8_QA_SEGURIDAD_RENDIMIENTO.md).
