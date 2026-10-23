# Sistema de Trazabilidad Documental para Auditorías

Aplicación local que organiza documentos, versiones, evidencias y hallazgos de auditoría, registra quién realiza cada operación y permite revisar aprobaciones, indicadores y anomalías documentales.

## Objetivo

Mantener un expediente verificable durante el ciclo de auditoría: responsables, archivos con SHA-256, versiones históricas, decisiones y eventos.

## Uso de inteligencia artificial durante el desarrollo

Durante el desarrollo de este proyecto utilicé herramientas de inteligencia artificial como apoyo para la programación y revisión del código.

Definí la arquitectura del sistema y los requisitos, elegí las tecnologías y tomé las decisiones sobre su funcionamiento.

Utilicé Codex principalmente para implementar los módulos, corregir código y desarrollar pruebas siguiendo mis indicaciones. Utilicé Antigravity principalmente para revisar y auditar el código, identificar errores, detectar posibles problemas de seguridad y verificar las implementaciones. También utilicé Gemini y ChatGPT como apoyo complementario durante distintas etapas del desarrollo.

Me encargué de planificar y supervisar el desarrollo, establecer las tareas, revisar y validar los resultados y decidir qué cambios se integraban al proyecto. Yo, Samuel Cruz Barrientos, asumo la responsabilidad del software.

Estas herramientas se utilizaron como apoyo durante el desarrollo. El módulo de análisis documental implementado funciona mediante reglas deterministas y comparaciones de datos; actualmente no utiliza LLM, modelos de inteligencia artificial entrenados ni Ollama.

Mantengo el compromiso de atribuir las colaboraciones de IA en los futuros commits cuando corresponda.

## Funcionalidades implementadas

- Autenticación, sesiones revocables, permisos por rol y revisión administrativa de solicitudes de acceso.
- Documentos con versiones, archivos con SHA-256 y registro de operaciones.
- Auditorías, evidencias, hallazgos y aprobaciones por versión.
- Dashboard de indicadores y análisis documental mediante reglas deterministas y heurísticas explicables.

Los permisos dependen del rol y de los recursos asignados. Consulte la [matriz de permisos](docs/MATRIZ_PERMISOS.md).

## Tecnologías y arquitectura

Python 3.14, FastAPI, SQLAlchemy, Alembic y MySQL 8/InnoDB; PHP, HTML, CSS y JavaScript. Argon2id para contraseñas, JWT para autenticación y SHA-256 para integridad de archivos.

```text
Navegador -> PHP (sesión, CSRF, presentación)
                  -> FastAPI (autenticación, permisos, reglas y eventos)
                       -> MySQL 8 (metadatos y trazabilidad)
                       -> storage/ (archivos privados)
Worker Python -> cola MySQL -> SMTP TLS -> correo del destinatario
```

PHP no accede directamente a MySQL y conserva el JWT en la sesión del servidor. `storage/` no se expone como directorio web.

## Requisitos

Git, Python 3.14 de 64 bits, MySQL 8 con InnoDB y PHP 8.1+ con cURL, mbstring, fileinfo, OpenSSL y sesiones. Se necesita acceso a PyPI, permisos para crear un schema vacío y un sistema de archivos que admita hardlinks, como NTFS o ext4. XAMPP puede proporcionar PHP; su MariaDB no sustituye a MySQL 8. Chrome sólo es necesario para las pruebas de navegador.

## Inicio rápido

Ejemplo para una instalación nueva en Windows, con **CMD**. Los comandos parten de la raíz del repositorio salvo donde se indica `cd`. Las variantes de PowerShell y los detalles están en la [guía de instalación completa](docs/GUIA_INSTALACION.md).

1. **Prepare el entorno.** Instale los requisitos anteriores, habilite las extensiones PHP e inicie MySQL 8. Consulte la [comprobación del entorno](docs/GUIA_INSTALACION.md#1-requisitos-previos).

2. **Obtenga el repositorio.**

   ```bat
   git clone https://github.com/samcruzb11-creator/G19X-TESCI-SCB-866-ACADEMIC.git
   cd G19X-TESCI-SCB-866-ACADEMIC
   ```

3. **Cree el entorno virtual.**

   ```bat
   py -3.14 -m venv api\venv
   ```

4. **Instale las dependencias de Python.**

   ```bat
   api\venv\Scripts\python.exe -m pip install -r requirements.txt -c requirements-lock.txt
   api\venv\Scripts\python.exe -m pip check
   ```

5. **Prepare la configuración privada.** En el clone nuevo, copie el ejemplo; conserve cualquier `.env` existente.

   ```bat
   copy api\.env.example api\.env
   ```

6. **Prepare MySQL.** Cree un schema vacío y una cuenta local siguiendo el [SQL de instalación](docs/GUIA_INSTALACION.md#3-mysql-vacío-y-cuenta-local). No importe un dump personal ni reutilice una base operativa.

7. **Complete `api/.env`.** Configure `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`; genere un `JWT_SECRET_KEY` privado. Mantenga `APP_ENV=development`, `TURNSTILE_MODE=disabled` y `PUBLIC_FRONTEND_URL=http://127.0.0.1:8080` para el recorrido local. Siga la [configuración detallada](docs/GUIA_INSTALACION.md#4-configuración-privada); no publique sus valores.

8. **Ejecute las migraciones.** El resultado esperado es `005`.

   ```bat
   cd api
   venv\Scripts\python.exe -m alembic upgrade head
   venv\Scripts\python.exe -m alembic current
   cd ..
   ```

9. **Prepare los datos de evaluación, si corresponde.** Necesita el archivo privado externo `01_ACCESOS_PRUEBA.md`. La guía explica cómo [obtenerlo y cargar las cuentas y el dataset](docs/GUIA_INSTALACION.md#6-usuarios-y-datos-de-evaluación). No hay cuentas públicas predeterminadas ni usuarios creados automáticamente al arrancar.

10. **Inicie FastAPI en la terminal 1.** Mantenga un solo proceso API.

    ```bat
    cd api
    venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    ```

11. **Inicie PHP en la terminal 2**, abierta en la raíz del repositorio. Ajuste la ruta si PHP está instalado en otra ubicación.

    ```bat
    C:\xampp\php\php.exe -S 127.0.0.1:8080 -t frontend
    ```

12. **Acceda desde el navegador.** Abra http://127.0.0.1:8080 e inicie sesión con una cuenta preparada en el paso 9. Compruebe los permisos de cada rol según la [verificación de funcionamiento](docs/GUIA_INSTALACION.md#9-verificar-el-funcionamiento).

13. **Consulte la API.** Swagger está en http://127.0.0.1:8000/docs y el estado básico en http://127.0.0.1:8000. Swagger complementa la interfaz PHP; no publique tokens ni credenciales.

## Limitaciones del MVP

- El sistema se ejecuta localmente; no hay un despliegue de producción ni respaldo automático.
- La recuperación por correo y la activación de cuentas requieren SMTP externo, el worker y un buzón autorizado. No se ha acreditado recepción real; las cuentas ficticias de evaluación no tienen buzón. Véase [servicios externos](docs/GUIA_INSTALACION.md#10-correo-y-servicios-externos).
- No existe registro público automático, CRUD web general de usuarios o áreas, refresh token ni operación HTTP general para asociar documentos con auditorías. El dataset prepara sus propios vínculos.
- El análisis 7E no interpreta semánticamente los documentos ni certifica una auditoría. Sus límites pueden dejar comprobaciones parciales; las coincidencias requieren revisión.
- Una interrupción entre MySQL y el sistema de archivos puede dejar archivos sin referencia. La reconciliación requiere revisión humana; no hay limpieza automática.

## Documentación

- [Instalación completa](docs/GUIA_INSTALACION.md), [configuración](docs/CONFIGURACION.md) y [SMTP y recuperación](docs/SMTP_RECUPERACION.md).
- [Manual de usuario](docs/MANUAL_USUARIO.md), [manual técnico](docs/MANUAL_TECNICO.md), [documento técnico](docs/DOCUMENTO_TECNICO.md) y [alcance del MVP](MVP.md).
- Explicaciones de [autorización](docs/EXPLICACION_AUTHORIZATION_SERVICE.md), [transacciones de archivos](docs/EXPLICACION_FILE_TRANSACTION.md) y [reglas de análisis](docs/EXPLICACION_ANALISIS_RULES.md).
- [Índice documental](docs/README.md), [PRD](docs/PRD.md), [bitácora](docs/BITACORA.md) y [evidencia del proyecto](docs/EVIDENCIA_PROYECTO.md).

El repositorio no incluye una licencia de distribución. La documentación pública no concede por sí misma permisos generales de redistribución.
