"""ЛР1: простой REST API (стратегии). In-memory.

Запуск:
  python main.py
  # или: uvicorn main:app --port 8001
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import time
from typing import Annotated, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

API_KEY = "demo-key"
LIMIT, WINDOW = 60, 60.0
strategies: dict[str, dict] = {}
idem: dict[str, dict] = {}
hits: dict[str, deque] = defaultdict(deque)

app = FastAPI(title="Strategies API", version="1.0")


class StrategyIn(BaseModel):
    name: str
    description: str = ""


class StrategyInV2(StrategyIn):
    tags: list[str] = Field(default_factory=list)


def check_key(key: Optional[str]) -> None:
    if key != API_KEY:
        raise HTTPException(401, "need X-API-Key: demo-key")


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in ("/", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    k = request.headers.get("X-API-Key") or "anon"
    now = time()
    q = hits[k]
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= LIMIT:
        return JSONResponse(
            {"detail": "rate limit"},
            status_code=429,
            headers={"X-Limit-Remaining": "0", "Retry-After": "60"},
        )
    q.append(now)
    resp = await call_next(request)
    resp.headers["X-Limit-Remaining"] = str(LIMIT - len(q))
    return resp


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/api/v1/strategies")
def list_v1(x_api_key: Annotated[Optional[str], Header()] = None):
    check_key(x_api_key)
    return [
        {"id": s["id"], "name": s["name"], "description": s["description"]}
        for s in strategies.values()
    ]


@app.post("/api/v1/strategies", status_code=201)
def create_v1(
    body: StrategyIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    check_key(x_api_key)
    if idempotency_key and idempotency_key in idem:
        return idem[idempotency_key]
    sid = str(uuid4())
    row = {"id": sid, "name": body.name, "description": body.description, "tags": []}
    strategies[sid] = row
    out = {"id": sid, "name": row["name"], "description": row["description"]}
    if idempotency_key:
        idem[idempotency_key] = out
    return out


@app.get("/api/v1/strategies/{sid}")
def get_v1(sid: str, x_api_key: Annotated[Optional[str], Header()] = None):
    check_key(x_api_key)
    s = strategies.get(sid)
    if not s:
        raise HTTPException(404)
    return {"id": s["id"], "name": s["name"], "description": s["description"]}


@app.put("/api/v1/strategies/{sid}")
def put_v1(
    sid: str,
    body: StrategyIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    check_key(x_api_key)
    if sid not in strategies:
        raise HTTPException(404)
    strategies[sid].update(name=body.name, description=body.description)
    s = strategies[sid]
    return {"id": s["id"], "name": s["name"], "description": s["description"]}


@app.delete("/api/v1/strategies/{sid}", status_code=204)
def del_v1(sid: str, x_api_key: Annotated[Optional[str], Header()] = None):
    check_key(x_api_key)
    if sid not in strategies:
        raise HTTPException(404)
    del strategies[sid]
    return Response(status_code=204)


@app.get("/api/v2/strategies")
def list_v2(x_api_key: Annotated[Optional[str], Header()] = None):
    check_key(x_api_key)
    return list(strategies.values())


@app.post("/api/v2/strategies", status_code=201)
def create_v2(
    body: StrategyInV2,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    check_key(x_api_key)
    sid = str(uuid4())
    row = {
        "id": sid,
        "name": body.name,
        "description": body.description,
        "tags": list(body.tags),
    }
    strategies[sid] = row
    return row


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)
