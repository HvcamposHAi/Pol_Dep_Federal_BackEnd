"""Cliente HTTP compartilhado (httpx async) + helper de request com retry/backoff.

Todas as chamadas externas (Apollo, ViaCEP) DEVEM passar por aqui — nunca criar
``httpx.Client`` avulso. Um único cliente é gerenciado no lifespan da app (e no
início da CLI) para reaproveitar o pool de conexões.
"""

from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings

_client: httpx.AsyncClient | None = None

# Status que justificam retry (rate limit / erros transitórios do servidor)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableHTTPError(Exception):
    """Erro transitório que deve ser re-tentado."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message or f"HTTP {status_code}")


def init_client() -> httpx.AsyncClient:
    """Cria (uma vez) o cliente compartilhado."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    return _client


def get_client() -> httpx.AsyncClient:
    if _client is None:
        return init_client()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException, RetryableHTTPError))


async def request_with_retry(
    method: str,
    url: str,
    **kwargs: object,
) -> httpx.Response:
    """Faz a requisição com retry exponencial+jitter em erros de rede/timeout/429/5xx.

    Outros 4xx NÃO são re-tentados (retornados ao chamador para tratar como
    no_match / requisição inválida). Respeita ``Retry-After`` levantando erro
    retryable que o tenacity reprograma.
    """
    settings = get_settings()

    @retry(
        reraise=True,
        stop=stop_after_attempt(settings.http_max_retries),
        wait=wait_exponential_jitter(initial=2, max=60),
        retry=retry_if_exception(_is_retryable),
    )
    async def _do() -> httpx.Response:
        client = get_client()
        resp = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
        if resp.status_code in _RETRYABLE_STATUS:
            raise RetryableHTTPError(resp.status_code, f"retryable status {resp.status_code}")
        return resp

    return await _do()
