from fastapi import Request
import httpx

async def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    FastAPI dependency provider for the shared httpx.AsyncClient instance.
    Retrieves the client from the application state (`request.app.state.http_client`).
    """
    return request.app.state.http_client
