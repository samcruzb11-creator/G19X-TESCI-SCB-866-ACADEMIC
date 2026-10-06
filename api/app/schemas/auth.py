from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)
    turnstile_token: SecretStr | None = Field(default=None, max_length=2048)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class CurrentUserResponse(BaseModel):
    id: int
    nombre: str
    correo: str
    rol: str
