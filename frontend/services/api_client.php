<?php
declare(strict_types=1);

require_once __DIR__ . '/../config/config.php';

/** Only known API resources may be addressed; never accept a client-supplied URL. */
function api_url(string $path, array $query = []): ?string
{
    if (!preg_match('~\A/api/v1/(?:areas|usuarios|auditorias|evidencias(?:/(?:archivo|logica|[1-9][0-9]*(?:/descargar)?))?|documentos(?:/[1-9][0-9]*(?:/(?:historial|versiones(?:/[1-9][0-9]*/descargar)?))?)?)\z~', $path)) {
        return null;
    }
    $url = rtrim(API_BASE_URL, '/') . $path;
    if ($query !== []) {
        $url .= '?' . http_build_query($query, '', '&', PHP_QUERY_RFC3986);
    }
    return $url;
}

function api_failure(int $status = 0): array
{
    return ['ok' => false, 'status' => $status, 'data' => [], 'message' => 'No fue posible cargar la información. Intenta nuevamente en unos momentos.'];
}

/** Convert upstream errors to known codes; never render upstream messages verbatim. */
function api_error_response(int $status, string $body): array
{
    $result = api_failure($status);
    $error = json_decode($body, true);
    $detail = is_array($error) ? ($error['detail'] ?? null) : null;
    $result['error_code'] = match ($status) {
        422 => 'validation', 404 => 'not_found', 409 => 'conflict',
        default => $status >= 500 ? 'server' : 'request',
    };
    $result['error_fields'] = [];
    if ($status === 409 && $detail === 'El codigo de auditoria ya existe') {
        $result['error_code'] = 'duplicate_code';
    }
    if (in_array($status, [400, 409], true) && is_string($detail)
        && str_starts_with($detail, 'Ya existe un documento con el código ')) {
        $result['error_code'] = 'duplicate_code';
    }
    if ($status === 400 && is_string($detail) && preg_match('/\AUsuario con ID [0-9]+ no encontrado\z/', $detail)) {
        $result['error_code'] = 'creator_not_found';
    }
    if ($status === 422 && is_array($detail)) {
        foreach ($detail as $item) {
            $location = is_array($item) ? ($item['loc'] ?? []) : [];
            if (!is_array($location)) continue;
            $field = $location[1] ?? null;
            if (in_array($field, ['codigo', 'titulo', 'descripcion', 'tipo', 'estado', 'area_id', 'responsable_id', 'creador_id', 'nombre', 'alcance', 'created_by_id', 'fecha_inicio_prevista', 'fecha_fin_prevista', 'auditoria_id', 'registrada_por_id', 'documento_id', 'version_documento_id', 'referencia_url', 'archivo'], true)) {
                $result['error_fields'][] = $field;
            }
        }
    }
    return $result;
}

/** Shared JSON transport. cURL sets the multipart boundary when fields contain CURLFile. */
function api_request(string $method, string $path, array $query = [], ?array $multipart = null, ?array $json = null): array
{
    $url = api_url($path, $query);
    if (!function_exists('curl_init') || $url === null || !in_array($method, ['GET', 'POST'], true)) {
        return api_failure();
    }
    if ($method === 'POST' && !(
        (in_array($path, ['/api/v1/documentos', '/api/v1/auditorias', '/api/v1/evidencias/logica'], true) && $json !== null && $multipart === null)
        || (($path === '/api/v1/evidencias/archivo' || preg_match('~\A/api/v1/documentos/[1-9][0-9]*/versiones\z~', $path)) && $multipart !== null && $json === null)
    )) {
        return api_failure();
    }
    $handle = curl_init($url);
    if ($handle === false) {
        return api_failure();
    }
    try {
        curl_setopt_array($handle, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => API_CONNECT_TIMEOUT,
            CURLOPT_TIMEOUT => $method === 'POST' ? 120 : API_TIMEOUT,
            CURLOPT_HTTPHEADER => ['Accept: application/json'],
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
        ]);
        if ($method === 'POST') {
            curl_setopt($handle, CURLOPT_POST, true);
            if ($json !== null) {
                curl_setopt($handle, CURLOPT_HTTPHEADER, ['Accept: application/json', 'Content-Type: application/json']);
                curl_setopt($handle, CURLOPT_POSTFIELDS, json_encode($json, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE));
            } else {
                curl_setopt($handle, CURLOPT_POSTFIELDS, $multipart);
            }
        }
        $body = curl_exec($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_HTTP_CODE);
        if ($body === false || $status < 200 || $status >= 300) {
            return $body === false ? api_failure($status) : api_error_response($status, $body);
        }
        $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            return api_failure($status);
        }
        return ['ok' => true, 'status' => $status, 'data' => $data, 'message' => ''];
    } catch (Throwable $exception) {
        return api_failure();
    } finally {
        curl_close($handle);
    }
}

function api_post_json(string $path, array $payload, array $query = []): array
{
    return api_request('POST', $path, $query, null, $payload);
}

function api_get(string $path, array $query = []): array
{
    $result = api_request('GET', $path, $query);
    if (!$result['ok']) return $result;
    if (!array_is_list($result['data'])) return api_failure($result['status']);
    foreach ($result['data'] as $row) {
        if (!is_array($row) || array_is_list($row)) return api_failure($result['status']);
    }
    return $result;
}

function api_get_object(string $path, array $query = []): array
{
    $result = api_request('GET', $path, $query);
    return $result['ok'] && array_is_list($result['data']) ? api_failure($result['status']) : $result;
}

/** Read all pages for small local catalogs; never present a truncated result as complete. */
function api_get_all(string $path): array
{
    if (!in_array($path, ['/api/v1/auditorias', '/api/v1/documentos'], true)) return api_failure();
    $rows = [];
    for ($offset = 0; $offset < 10000; $offset += 200) {
        $result = api_get($path, ['limit' => 200, 'offset' => $offset]);
        if (!$result['ok']) return $result;
        $rows = array_merge($rows, $result['data']);
        if (count($result['data']) < 200) return ['ok' => true, 'status' => 200, 'data' => $rows, 'message' => ''];
    }
    return api_failure();
}

/** Build separately so multipart can be checked without sending a mutation. */
function api_multipart_fields(array $fields, array $files): array
{
    foreach ($files as $field => $file) {
        if (!is_file($file['path']) || !is_readable($file['path'])) {
            throw new InvalidArgumentException('Archivo no disponible');
        }
        $name = basename(str_replace('\\', '/', $file['name']));
        $name = preg_replace('/[\x00-\x1F\x7F]/', '', $name) ?: 'archivo';
        $mime = (new finfo(FILEINFO_MIME_TYPE))->file($file['path']) ?: 'application/octet-stream';
        $fields[$field] = new CURLFile($file['path'], $mime, $name);
    }
    return $fields;
}

function api_post_multipart(string $path, array $fields, array $files): array
{
    try {
        return api_request('POST', $path, [], api_multipart_fields($fields, $files));
    } catch (Throwable $exception) {
        return api_failure();
    }
}

/** Buffer in a PHP temporary file so upstream failures never become partial downloads. */
function api_download(string $path): array
{
    $url = api_url($path);
    if (!function_exists('curl_init') || $url === null || !str_ends_with($path, '/descargar')) return api_failure();
    $stream = tmpfile();
    if ($stream === false) return api_failure();
    $handle = curl_init($url);
    if ($handle === false) { fclose($stream); return api_failure(); }
    $completed = false;
    try {
        curl_setopt_array($handle, [
            CURLOPT_FILE => $stream,
            CURLOPT_CONNECTTIMEOUT => API_CONNECT_TIMEOUT,
            CURLOPT_TIMEOUT => 120,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
        ]);
        $ok = curl_exec($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_HTTP_CODE);
        if ($ok === false || $status !== 200) return api_failure($status);
        rewind($stream);
        $completed = true;
        return ['ok' => true, 'status' => $status, 'stream' => $stream];
    } catch (Throwable $exception) {
        return api_failure();
    } finally {
        curl_close($handle);
        if (!$completed) fclose($stream);
    }
}
