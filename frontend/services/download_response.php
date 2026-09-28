<?php
declare(strict_types=1);

/** Deliver only the temporary stream returned by FastAPI; never resolve a storage path. */
function send_api_download(array $download, array $metadata): never
{
    $filename = is_string($metadata['nombre_original'] ?? null) ? $metadata['nombre_original'] : 'archivo';
    $filename = basename(str_replace('\\', '/', $filename));
    $filename = preg_replace('/[\x00-\x1F\x7F]/', '', $filename) ?: 'archivo';
    $mime = is_string($metadata['mime_type'] ?? null) ? $metadata['mime_type'] : '';
    if (!preg_match('~\A[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+\z~', $mime)) $mime = 'application/octet-stream';
    if (session_status() === PHP_SESSION_ACTIVE) session_write_close();
    header('Content-Type: ' . $mime);
    header("Content-Disposition: attachment; filename=\"archivo\"; filename*=UTF-8''" . rawurlencode($filename));
    header('Content-Length: ' . fstat($download['stream'])['size']);
    fpassthru($download['stream']);
    fclose($download['stream']);
    exit;
}
