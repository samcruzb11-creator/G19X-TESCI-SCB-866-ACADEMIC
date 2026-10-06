import re
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from app.core.security import normalize_email

Role = Literal['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO', 'RESPONSABLE_AREA', 'APROBADOR']


def valid_address(value: str) -> str:
    value = normalize_email(value)
    if len(value) > 320 or not re.fullmatch(r'[^\s@<>(),;:\\[\]"]+@[^\s@<>(),;:\\[\]"]+\.[^\s@<>(),;:\\[\]"]+', value):
        raise ValueError('Correo invalido')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Correo invalido')
    local, domain = value.rsplit('@', 1)
    if len(local.encode('utf-8')) > 64 or local.startswith('.') or local.endswith('.') or '..' in local:
        raise ValueError('Correo invalido')
    try:
        labels = domain.encode('idna').decode('ascii').split('.')
    except UnicodeError:
        raise ValueError('Correo invalido') from None
    if len(domain) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels):
        raise ValueError('Correo invalido')
    return value


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    correo: str = Field(min_length=3, max_length=320)
    turnstile_token: SecretStr | None = Field(default=None, max_length=2048)
    normalize = field_validator('correo')(valid_address)


class AccessRequestCreate(EmailRequest):
    nombre: str = Field(min_length=2, max_length=160)
    motivo: str = Field(min_length=5, max_length=2000)

    @field_validator('nombre', 'motivo')
    @classmethod
    def clean(cls, value, info):
        value = value.strip()
        minimum = 2 if info.field_name == 'nombre' else 5
        if len(value) < minimum or any((ord(c) < 32 and c not in '\n\t') or ord(c) == 127 for c in value):
            raise ValueError('Texto invalido')
        return value


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rol: Role


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    motivo: str = Field(default='', max_length=1000)

    @field_validator('motivo')
    @classmethod
    def clean(cls, value):
        return ''.join(c for c in value if ord(c) >= 32).strip()


class ResendRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PasswordConfirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: SecretStr = Field(min_length=1, max_length=256)
    password: SecretStr = Field(min_length=12, max_length=1024)


class AccessRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    identifier: str
    nombre: str
    motivo: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None
    approved_role: str | None
    admin_reason: str | None
    usuario_id: int | None
