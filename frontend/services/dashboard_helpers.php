<?php
declare(strict_types=1);

function dashboard_offset(mixed $value): int
{
    if (!is_string($value) || !preg_match('/\A[0-9]{1,5}\z/', $value) || (int) $value > 10000) {
        throw new ApiPageError(422, 'Página inválida.');
    }
    return (int) $value;
}

function dashboard_destination(mixed $destination): ?string
{
    if (!is_array($destination) || !is_string($destination['pagina'] ?? null)) return null;
    $module = ['auditoria'=>'auditorias', 'hallazgo'=>'hallazgos', 'aprobacion'=>'aprobaciones', 'documento'=>'documentos'];
    $target = $destination['pagina'];
    $id = positive_id($destination['id'] ?? null);
    return $id !== null && isset($module[$target]) && can_show_action($module[$target])
        ? page_url($target, ['id'=>$id]) : null;
}

function dashboard_alert_types(): array
{
    return ['AUDITORIA_ACTIVA'=>'Auditoría en curso', 'AUDITORIA_REVISION'=>'Auditoría en revisión',
        'HALLAZGO_PENDIENTE'=>'Hallazgo sin resolver', 'RONDA_PENDIENTE'=>'Ronda pendiente registrada',
        'DECISION_PROPIA_PENDIENTE'=>'Mi decisión pendiente registrada', 'DOCUMENTO_SIN_VERSION'=>'Documento sin versión'];
}

function dashboard_state_label(string $state): string
{
    return ['PLANNED'=>'Planificadas', 'IN_PROGRESS'=>'En curso', 'IN_REVIEW'=>'En revisión',
        'COMPLETED'=>'Completadas', 'CANCELLED'=>'Canceladas', 'OPEN'=>'Abiertos',
        'PENDING_VERIFICATION'=>'Pendientes de verificación', 'CLOSED'=>'Cerrados',
        'ACCEPTED_RISK'=>'Riesgo aceptado', 'PENDING'=>'Pendientes', 'APPROVED'=>'Aprobadas',
        'REJECTED'=>'Rechazadas', 'CHANGES_REQUESTED'=>'Cambios solicitados',
        'FILE'=>'Archivos', 'REFERENCE'=>'Referencias', 'NOTE'=>'Notas', 'OTHER'=>'Otros',
        'DESCONOCIDO'=>'Estado no reconocido'][$state] ?? 'Estado no reconocido';
}
