"""Bound received bytes before JSON expansion or multipart spooling."""
import re

from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.core.config import settings


class RequestBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        prefix = settings.api_v1_prefix.rstrip('/')
        if (scope['type'] != 'http' or scope.get('method') not in {'POST', 'PUT', 'PATCH', 'DELETE'}
                or not path.startswith(prefix + '/')):
            await self.app(scope, receive, send)
            return
        limit = 1024 * 1024
        if re.fullmatch(re.escape(prefix) + r'/documentos/[^/]+/versiones', path):
            limit = settings.max_document_file_bytes + 128 * 1024
        elif path == prefix + '/evidencias/archivo':
            limit = settings.max_evidence_file_bytes + 128 * 1024
        headers = dict(scope.get('headers', []))
        length = headers.get(b'content-length')
        if length is not None and (len(length) > 20 or not length.isdigit()):
            await JSONResponse({'detail': 'Longitud de solicitud invalida'}, status_code=400)(scope, receive, send)
            return
        if length is not None and int(length) > limit:
            await JSONResponse({'detail': 'Solicitud demasiado grande'}, status_code=413,
                               headers={'Cache-Control': 'no-store'})(scope, receive, send)
            return
        received = 0
        multipart = headers.get(b'content-type', b'').lower().startswith(b'multipart/form-data')
        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    # Starlette's parser closes all partially spooled files on
                    # MultiPartException. Raising HTTPException here skips that cleanup.
                    if multipart:
                        raise MultiPartException('Solicitud demasiado grande')
                    raise HTTPException(status_code=413, detail='Solicitud demasiado grande')
            return message
        await self.app(scope, bounded_receive, send)
