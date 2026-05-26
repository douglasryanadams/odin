# Minimal type stub for asyncpg, covering only the symbols this project uses.
# asyncpg ships no py.typed marker, so pyright infers partial/unknown types from
# its source. This stub pins the surface we call. Extend it as new asyncpg APIs
# are used rather than reaching for cast() or `# pyright: ignore`.

from typing import Any

class Pool:
    async def execute(self, query: str, *args: object) -> str: ...
    async def fetchval(self, query: str, *args: object, column: int = ...) -> Any: ...
    async def fetchrow(self, query: str, *args: object) -> Any: ...
    async def close(self) -> None: ...

async def create_pool(
    dsn: str,
    *,
    min_size: int = ...,
    max_size: int = ...,
) -> Pool: ...
