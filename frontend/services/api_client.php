<?php
declare(strict_types=1);

require_once __DIR__ . '/../config/config.php';
require_once __DIR__ . '/api_errors.php';

function public_auth_endpoint(string $path): bool
{
    return in_array($path, ['/api/v1/auth/login', '/api/v1/auth/access-requests',
        '/api/v1/auth/password-reset/request', '/api/v1/auth/password-reset/confirm',
        '/api/v1/auth/initial-password/confirm'], true);
}

/** Only known API resources may be addressed; never accept a client-supplied URL. */
function api_url(string $path, array $query = []): ?string
{
    if (!preg_match('~\A/api/v1/(?:auth/(?:login|me|logout|access-requests|password-reset/(?:request|confirm)|initial-password/confirm)|access-requests(?:/[1-9][0-9]*(?:/(?:approve|reject|resend))?)?|areas|usuarios|auditorias(?:/[1-9][0-9]*(?:/(?:estado|historial))?)?|evidencias(?:/(?:archivo|logica|[1-9][0-9]*(?:/descargar)?))?|documentos(?:/[1-9][0-9]*(?:/(?:historial|versiones(?:/[1-9][0-9]*/descargar)?))?)?)\z~', $path)) {
        return null;
    }
    $url = rtrim(API_BASE_URL, '/') . $path;
    if ($query !== []) {
        $url .= '?' . http_build_query($query, '', '&', PHP_QUERY_RFC3986);
    }
    return $url;
}

/** One source of Authorization for JSON, multipart and downloads. */
function api_headers(string $path, bool $json = false): array
{
    $headers = ['Accept: application/json'];
    if (!public_auth_endpoint($path)) {
        $token = $_SESSION['auth']['access_token'] ?? null;
        if (!is_string($token) || $token === '' || preg_match('/[\r\n]/', $token)) throw new AuthenticationRequired();
        $headers[] = 'Authorization: Bearer ' . $token;
    }
    if ($json) $headers[] = 'Content-Type: application/json';
    return $headers;
}

/** Shared JSON transport. cURL sets the multipart boundary when fields contain CURLFile. */
function api_request(string $method, string $path, array $query = [], ?array $multipart = null, ?array $json = null): array
{
    $url = api_url($path, $query);
    if (!function_exists('curl_init') || $url === null || !in_array($method, ['GET', 'POST', 'PATCH'], true)) {
        return api_failure();
    }
    if ($method === 'PATCH' && (!preg_match('~\A/api/v1/auditorias/[1-9][0-9]*\z~', $path) || $json === null || $multipart !== null)) return api_failure();
    if ($method === 'POST' && !(
        ((public_auth_endpoint($path) || preg_match('~\A/api/v1/access-requests/[1-9][0-9]*/(?:approve|reject|resend)\z~', $path) || preg_match('~\A/api/v1/auditorias/[1-9][0-9]*/estado\z~', $path)) && $json !== null && $multipart === null)
        ||
        (in_array($path, ['/api/v1/auth/login', '/api/v1/documentos', '/api/v1/auditorias', '/api/v1/evidencias/logica'], true) && $json !== null && $multipart === null)
        || ($path === '/api/v1/auth/logout' && $multipart === null && $json === null)
        || (($path === '/api/v1/evidencias/archivo' || preg_match('~\A/api/v1/documentos/[1-9][0-9]*/versiones\z~', $path)) && $multipart !== null && $json === null)
    )) {
        return api_failure();
    }
    $headers = api_headers($path, $json !== null);
    $handle = curl_init($url);
    if ($handle === false) {
        return api_failure();
    }
    try {
        $authRequest = str_starts_with($path, '/api/v1/auth/');
        $retryAfter = null;
        $totalCount = null;
        curl_setopt_array($handle, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => API_CONNECT_TIMEOUT,
            CURLOPT_TIMEOUT => $authRequest ? auth_api_timeout_seconds() : ($method !== 'GET' ? 120 : API_TIMEOUT),
            CURLOPT_HEADERFUNCTION => static function ($handle, string $line) use (&$retryAfter, &$totalCount): int {
                if (str_starts_with($line, 'HTTP/')) { $retryAfter = null; $totalCount = null; }
                if (preg_match('/\AX-Total-Count:\s*([0-9]{1,12})\s*\z/i', trim($line), $count)) $totalCount = (int) $count[1];
                if (preg_match('/\ARetry-After:\s*([0-9]{1,5})\s*\z/i', trim($line), $match)) {
                    $retryAfter = max(1, min(1200, (int) $match[1]));
                }
                return strlen($line);
            },
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
        ]);
        if ($method === 'POST' || $method === 'PATCH') {
            if ($method === 'POST') curl_setopt($handle, CURLOPT_POST, true);
            if ($json !== null) {
                // API JSON bodies are objects, including an empty resend command.
                curl_setopt($handle, CURLOPT_POSTFIELDS, json_encode((object) $json, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE));
            } elseif ($multipart !== null) {
                curl_setopt($handle, CURLOPT_POSTFIELDS, $multipart);
            }
            if ($method === 'PATCH') curl_setopt($handle, CURLOPT_CUSTOMREQUEST, 'PATCH');
        }
        $body = curl_exec($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_HTTP_CODE);
        if ($body === false || $status < 200 || $status >= 300) {
            $result = $body === false ? api_failure($status) : api_error_response($status, $body);
            if ($status === 429 && $retryAfter !== null) $result['retry_after'] = $retryAfter;
        } elseif ($status === 204) {
            $result = ['ok' => true, 'status' => 204, 'data' => [], 'message' => ''];
        } else {
            $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
            $result = is_array($data) ? ['ok' => true, 'status' => $status, 'data' => $data, 'message' => ''] : api_failure();
            if ($totalCount !== null) $result['total'] = $totalCount;
        }
    } catch (Throwable $exception) {
        error_log('Frontend API transport: ' . get_class($exception));
        $result = api_failure();
    } finally {
        curl_close($handle);
    }
    return api_finish($result, $path);
}

function api_post_json(string $path, array $payload, array $query = []): array
{
    return api_request('POST', $path, $query, null, $payload);
}

function api_patch_json(string $path, array $payload): array
{
    return api_request('PATCH', $path, [], null, $payload);
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
        $multipart = api_multipart_fields($fields, $files);
    } catch (Throwable $exception) {
        error_log('Frontend multipart preparation failed');
        return api_failure();
    }
    return api_request('POST', $path, [], $multipart);
}

/** Spool to disk before sending headers, never accumulating a file in PHP memory. */
function api_download(string $path): array
{
    $url = api_url($path);
    if (!function_exists('curl_init') || $url === null || !str_ends_with($path, '/descargar')) return api_failure();
    $headers = api_headers($path);
    $stream = tmpfile();
    if ($stream === false) return api_failure();
    $handle = curl_init($url);
    if ($handle === false) { fclose($stream); return api_failure(); }
    $completed = false;
    $responseHeaders = [];
    try {
        curl_setopt_array($handle, [
            CURLOPT_FILE => $stream,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_HEADERFUNCTION => static function ($handle, string $line) use (&$responseHeaders): int {
                if (str_starts_with($line, 'HTTP/')) $responseHeaders = [];
                $parts = explode(':', $line, 2);
                $key = strtolower(trim($parts[0]));
                if (count($parts) === 2 && in_array($key, ['content-type', 'content-disposition'], true)) $responseHeaders[$key] = trim($parts[1]);
                return strlen($line);
            },
            CURLOPT_CONNECTTIMEOUT => API_CONNECT_TIMEOUT,
            CURLOPT_TIMEOUT => 120,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
        ]);
        $ok = curl_exec($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_HTTP_CODE);
        rewind($stream);
        if ($ok === false || $status !== 200) {
            $result = $ok === false ? api_failure($status) : api_error_response($status, (string) fread($stream, 65536));
        } else {
            $completed = true;
            $result = ['ok' => true, 'status' => 200, 'stream' => $stream, 'headers' => $responseHeaders];
        }
    } catch (Throwable $exception) {
        error_log('Frontend download transport: ' . get_class($exception));
        $result = api_failure();
    } finally {
        curl_close($handle);
        if (!$completed) fclose($stream);
    }
    return api_finish($result, $path);
}
