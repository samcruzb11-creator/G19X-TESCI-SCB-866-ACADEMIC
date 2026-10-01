<?php
declare(strict_types=1);

/** Decode only supported filename forms; never forward upstream headers verbatim. */
function download_metadata(array $headers, array $metadata): array
{
    $filename = is_string($metadata['nombre_original'] ?? null) ? $metadata['nombre_original'] : 'archivo';
    $disposition = $headers['content-disposition'] ?? '';
    if (is_string($disposition)) {
        if (preg_match("~filename\\*=UTF-8''([^;]+)~i", $disposition, $match)) $filename = rawurldecode(trim($match[1]));
        elseif (preg_match('~filename="([^"\r\n]*)"~i', $disposition, $match)) $filename = $match[1];
    }
    $filename = basename(str_replace('\\', '/', $filename));
    $filename = preg_replace('/[\x00-\x1F\x7F]/', '', $filename) ?: 'archivo';
    if (!mb_check_encoding($filename, 'UTF-8') || in_array($filename, ['.', '..'], true)) $filename = 'archivo';
    $mime = $headers['content-type'] ?? $metadata['mime_type'] ?? '';
    if (!is_string($mime) || !preg_match('~\A[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+(?:;\s*charset=[a-zA-Z0-9._-]+)?\z~', $mime)) $mime = 'application/octet-stream';
    return ['filename' => $filename, 'mime' => $mime];
}

/** Deliver only the temporary stream returned by FastAPI; never resolve a storage path. */
function send_api_download(array $download, array $metadata): never
{
    try {
        $safe = download_metadata($download['headers'] ?? [], $metadata);
        if (session_status() === PHP_SESSION_ACTIVE) session_write_close();
        // PHP output buffers may copy the entire fpassthru block before flushing.
        // Controllers have not rendered anything: discard buffers before streaming.
        while (ob_get_level() > 0) ob_end_clean();
        header('Content-Type: ' . $safe['mime']);
        header("Content-Disposition: attachment; filename=\"archivo\"; filename*=UTF-8''" . rawurlencode($safe['filename']));
        header('Content-Length: ' . fstat($download['stream'])['size']);
        fpassthru($download['stream']);
    } finally {
        fclose($download['stream']);
    }
    exit;
}
