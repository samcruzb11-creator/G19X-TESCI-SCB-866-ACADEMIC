"""Explicit private Markdown contract. Never import this from application startup."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from dataclasses import dataclass, field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROLE_NAMES = {
    'ADMIN': 'Administrador Demo',
    'RESPONSABLE_AREA': 'Responsable Demo',
    'AUDITOR_INTERNO': 'Auditor Demo',
    'APROBADOR': 'Aprobador Demo',
}
PERMISSIONS = {
    'ADMIN': 'Visibilidad global y administración; sin reescritura de eventos históricos.',
    'RESPONSABLE_AREA': 'Documentos propios; sin administración ni auditorías globales.',
    'AUDITOR_INTERNO': 'Auditorías y hallazgos dentro de su alcance asignado.',
    'APROBADOR': 'Consulta y decisión de las rondas asignadas a su identidad.',
}
FENCE = 'evaluation-credentials-v1'


class CredentialsError(ValueError):
    """Messages must never include input, paths, identities or parser diagnostics."""


@dataclass(frozen=True)
class Account:
    email: str = field(repr=False)
    role: str
    password: str = field(repr=False)

    @property
    def name(self):
        return ROLE_NAMES[self.role]


def outside_repository(path):
    resolved = Path(path).expanduser().resolve()
    if (resolved.is_relative_to(PROJECT_ROOT) or resolved == PROJECT_ROOT
            or any((parent / '.git').exists() for parent in (resolved.parent, *resolved.parents))):
        raise CredentialsError('El archivo privado debe estar fuera del repositorio.')
    return resolved


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CredentialsError('Claves duplicadas en el contrato privado.')
        result[key] = value
    return result


def load_credentials(path, *, allow_legacy=False):
    if not path:
        raise CredentialsError('Se requiere un archivo privado externo de credenciales.')
    try:
        source = outside_repository(path)
        if not source.is_file() or source.stat().st_size > 65536:
            raise CredentialsError('Archivo privado ausente o demasiado grande.')
        raw = source.read_text(encoding='utf-8-sig')
        blocks = re.findall(r'^```' + FENCE + r'\r?\n(.*?)\r?\n```[ \t]*$', raw, re.M | re.S)
        if len(blocks) != 1:
            raise CredentialsError('Se requiere exactamente un bloque de contrato privado v1.')
        obj = json.loads(blocks[0], object_pairs_hook=_unique_object)
        if (not isinstance(obj, dict) or set(obj) != {'schema_version', 'accounts'}
                or type(obj['schema_version']) is not int or obj['schema_version'] != 1
                or not isinstance(obj['accounts'], list) or len(obj['accounts']) != 4):
            raise CredentialsError('Contrato privado v1 inválido.')
        accounts = {}
        for item in obj['accounts']:
            if not isinstance(item, dict) or set(item) != {'role', 'email', 'password'}:
                raise CredentialsError('Campos de cuenta inesperados.')
            role, email, password = item['role'], item['email'], item['password']
            email_pattern = r'eval-[a-z0-9-]{3,64}@example\.invalid'
            if allow_legacy:
                email_pattern = r'(?:eval-[a-z0-9-]{3,64}@example\.invalid|[a-z0-9.-]{3,80}@trazabilidad\.local)'
            password_pattern = r'[\x21-\x7e]{12,128}' if allow_legacy else r'[A-Za-z0-9_-]{32,128}'
            if (not isinstance(role, str) or role not in ROLE_NAMES or role in accounts
                    or not isinstance(email, str)
                    or not re.fullmatch(email_pattern, email)
                    or not isinstance(password, str)
                    or not re.fullmatch(password_pattern, password)):
                raise CredentialsError('Identidad, rol o contraseña fuera del contrato de evaluación.')
            accounts[role] = Account(email, role, password)
        if (set(accounts) != set(ROLE_NAMES)
                or len({a.email for a in accounts.values()}) != 4
                or len({a.password for a in accounts.values()}) != 4):
            raise CredentialsError('Se requieren cuatro identidades y contraseñas diferentes.')
        return tuple(accounts[role] for role in ROLE_NAMES)
    except CredentialsError:
        raise
    except Exception:
        raise CredentialsError('No se pudo leer el contrato privado v1.') from None


def generate_accounts():
    accounts = []
    emails, passwords = set(), set()
    for role in ROLE_NAMES:
        while True:
            email = 'eval-' + role.lower().replace('_', '-') + '-' + secrets.token_hex(6) + '@example.invalid'
            password = secrets.token_urlsafe(32)  # 256 bits before encoding
            if email not in emails and password not in passwords:
                break
        emails.add(email)
        passwords.add(password)
        accounts.append(Account(email, role, password))
    return tuple(accounts)


def markdown_document(accounts):
    data = {'schema_version': 1, 'accounts': [
        {'role': a.role, 'email': a.email, 'password': a.password} for a in accounts]}
    roles = '\n'.join(f'- **{a.role}**: {PERMISSIONS[a.role]}' for a in accounts)
    return ('# Accesos de prueba — entrega privada TODO Academy\n\n'
            'Compartir exclusivamente con Edgar mediante Accesos de prueba de TODO Academy. '
            'Uso exclusivamente local; identidades ficticias, sin correo saliente. '
            'No subir este documento a GitHub ni copiarlo al repositorio, PDF, DOCX o capturas.\n\n'
            'Los correos y las contraseñas individuales están en el bloque siguiente. '
            'Conservar el bloque sin editar: el seed lo interpreta como contrato v1.\n\n'
            f'```{FENCE}\n' + json.dumps(data, indent=2, ensure_ascii=False) + '\n```\n\n'
            '## Permisos\n\n' + roles + '\n\n'
            '## Evaluación desde cero\n\n'
            'Seguir README público: clone, venv, dependencias, MySQL 8 local, .env privado '
            'y Alembic 005. Guardar este archivo en %USERPROFILE%\\Downloads\\'
            'SistemaTrazabilidad_Entregables\\01_ACCESOS_PRUEBA.md, fuera del clone. '
            'Desde api, con el venv activado, ejecutar:\n\n```bat\n'
            'python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset '
            '--credentials-file "%USERPROFILE%\\Downloads\\SistemaTrazabilidad_Entregables\\01_ACCESOS_PRUEBA.md"\n'
            '```\n\nIniciar FastAPI y PHP según README. Abrir el login local y usar los datos '
            'del bloque para el rol elegido. Una repetición del seed conserva IDs, hashes y eventos. '
            'No volver a generar este archivo: produciría credenciales diferentes. '
            'La rotación es una operación administrativa separada, nunca automática.\n')


def restrict_permissions(path):
    if os.name == 'nt':
        who = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True,
                             text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        sid = next(csv.reader(who.stdout.strip().splitlines()))[-1]
        if not re.fullmatch(r'S-1-[0-9-]+', sid):
            raise CredentialsError('No se pudo resolver el propietario para ACL privada.')
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', '*' + sid + ':(F)'],
                       capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.chmod(path, 0o600)


def generate_file(path):
    if os.path.lexists(Path(path).expanduser()):
        raise CredentialsError('El archivo privado ya existe; no se sobrescribe ni se sigue un enlace.')
    output = outside_repository(path)
    # Exclusive creation; no existing file (including a link) is overwritten.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        restrict_permissions(output)  # ACL applies while the file is still empty.
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            fd = None
            stream.write(markdown_document(generate_accounts()))
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd is not None:
            os.close(fd)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generación opt-in de accesos privados, sin altas MySQL')
    parser.add_argument('--output', required=True)
    parser.add_argument('--confirm-generate', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_generate:
        print('Sin cambios. Se requiere --confirm-generate; salida externa y archivo inexistente.')
        return 0
    try:
        generate_file(args.output)
        print('Documento privado generado con permisos restringidos. Ninguna cuenta creada.')
        return 0
    except Exception:
        print('Generación rechazada. Revise ruta externa, directorio, ACL y ausencia de archivo previo.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
