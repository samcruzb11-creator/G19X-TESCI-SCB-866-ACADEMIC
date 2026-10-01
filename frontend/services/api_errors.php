<?php
declare(strict_types=1);

final class AuthenticationRequired extends RuntimeException
{
    public function __construct(public readonly bool $expired = true) { parent::__construct('Authentication required'); }
}

final class ApiPageError extends RuntimeException
{
    public function __construct(public readonly int $status, string $message) { parent::__construct($message); }
}

function api_failure(int $status = 0): array
{
    return ['ok' => false, 'status' => $status, 'data' => [], 'message' => 'No fue posible cargar la información. Intenta nuevamente en unos momentos.'];
}

/** Known messages and fields only. Never return raw upstream details. */
function api_error_response(int $status, string $body): array
{
    $result = api_failure($status);
    $error = json_decode($body, true);
    $detail = is_array($error) ? ($error['detail'] ?? null) : null;
    $result['error_code'] = match ($status) {
        401 => 'unauthenticated', 403 => 'forbidden', 404 => 'not_found',
        422 => 'validation', 409 => 'conflict', 429 => 'rate_limited', default => $status >= 500 ? 'server' : 'request',
    };
    $result['message'] = match ($status) {
        401 => 'Credenciales inválidas.',
        403 => 'No tiene permiso para realizar esta operación.',
        404 => 'El recurso solicitado no está disponible.',
        429 => 'Demasiados intentos. Intente nuevamente más tarde.',
        default => $result['message'],
    };
    $result['error_fields'] = [];
    if (($status === 409 && $detail === 'El codigo de auditoria ya existe')
        || (in_array($status, [400, 409], true) && is_string($detail) && str_starts_with($detail, 'Ya existe un documento con el código '))) {
        $result['error_code'] = 'duplicate_code';
    }
    if ($status === 422 && is_array($detail)) {
        foreach ($detail as $item) {
            $location = is_array($item) ? ($item['loc'] ?? []) : [];
            $field = is_array($location) ? ($location[1] ?? null) : null;
            if (in_array($field, ['codigo', 'titulo', 'descripcion', 'tipo', 'estado', 'area_id', 'responsable_id', 'nombre', 'alcance', 'fecha_inicio_prevista', 'fecha_fin_prevista', 'auditoria_id', 'documento_id', 'version_documento_id', 'referencia_url', 'archivo', 'comentario_cambio'], true)) {
                $result['error_fields'][] = $field;
            }
        }
    }
    return $result;
}

function api_http_status(array $result): int
{
    $status = $result['status'] ?? 0;
    return $status >= 400 && $status <= 599 ? $status : 502;
}

/** Executed outside transport catch/finally, so auth failures cannot be swallowed. */
function api_finish(array $result, string $path): array
{
    if (!$result['ok']) {
        if (($result['status'] ?? 0) === 0 || ($result['status'] ?? 0) >= 500) {
            error_log('Frontend API unavailable: status=' . (int) ($result['status'] ?? 0));
        }
        if (!in_array($path, ['/api/v1/auth/login', '/api/v1/auth/logout'], true)) {
            if ($result['status'] === 401) throw new AuthenticationRequired();
            if ($result['status'] === 403) throw new ApiPageError(403, $result['message']);
        }
    }
    return $result;
}
