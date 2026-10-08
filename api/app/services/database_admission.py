"""Keep synchronous request dependencies below the SQL pool/thread capacity.

Waiting for a connection in every worker can prevent authenticated requests
from reaching their handler/cleanup. Await admission before consuming workers.
Each server event loop owns its gate; isolated TestClient lifespans stay separate.
"""
import asyncio
from contextlib import asynccontextmanager
from threading import Lock
from weakref import WeakKeyDictionary

from starlette.responses import JSONResponse


class AdmissionFull(Exception):
    pass


class DatabaseAdmissionMiddleware:
    def __init__(self, app, *, capacity: int, prefix: str):
        self.app = app
        self.capacity = max(1, min(capacity, 32))
        self.prefix = prefix.rstrip('/') + '/'
        self.gates = WeakKeyDictionary()
        self.lock = Lock()

    def release_loop(self):
        with self.lock:
            self.gates.pop(asyncio.get_running_loop(), None)

    @asynccontextmanager
    async def acquire(self):
        loop = asyncio.get_running_loop()
        with self.lock:
            gate = self.gates.setdefault(loop, [asyncio.Semaphore(self.capacity), 0])
        if gate[1] >= self.capacity + 256:
            raise AdmissionFull()
        gate[1] += 1
        try:
            async with gate[0]:
                yield
        finally:
            gate[1] -= 1

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            try:
                await self.app(scope, receive, send)
            finally:
                self.release_loop()
            return
        if scope['type'] != 'http' or not scope.get('path', '').startswith(self.prefix):
            await self.app(scope, receive, send)
            return
        try:
            async with self.acquire():
                await self.app(scope, receive, send)
        except AdmissionFull:
            await JSONResponse({'detail': 'Servicio ocupado; intente nuevamente'}, status_code=503,
                headers={'Cache-Control': 'no-store', 'Retry-After': '1'})(scope, receive, send)
