"""Library REST API — лабораторные работы №1 и №2.

Предметная область: библиотека (авторы, книги, выдачи).
Запуск: uvicorn main:app --port 8000
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, timezone
from time import time
from typing import Annotated, Any, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

API_KEY = "library-secret-key"
INTERNAL_TOKEN = "internal-secret"
RATE_LIMIT = 60
RATE_WINDOW = 60.0

authors: dict[str, dict] = {}
books: dict[str, dict] = {}
loans: dict[str, dict] = {}
idempotency_store: dict[str, dict] = {}
rate_hits: dict[str, deque] = defaultdict(deque)

app = FastAPI(
    title="Library API",
    description="REST API библиотеки: авторы, книги, выдачи. Версии v1 и v2.",
    version="2.0.0",
)


# ---- models ----

class AuthorIn(BaseModel):
    name: str = Field(..., min_length=1, examples=["Лев Толстой"])
    country: str = Field(default="", examples=["Россия"])


class AuthorInV2(AuthorIn):
    birth_year: Optional[int] = Field(default=None, examples=[1828])


class BookIn(BaseModel):
    title: str = Field(..., min_length=1)
    author_id: str
    year: Optional[int] = None


class BookInV2(BookIn):
    isbn: Optional[str] = None
    genres: list[str] = Field(default_factory=list)


class LoanIn(BaseModel):
    book_id: str
    reader_name: str = Field(..., min_length=1)
    due_date: Optional[date] = None


class LoanInV2(LoanIn):
    notes: str = ""


# ---- helpers ----

def require_api_key(key: Optional[str]) -> None:
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Требуется заголовок X-API-Key: library-secret-key")


def require_internal(token: Optional[str]) -> None:
    if token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Требуется X-Internal-Token: internal-secret")


def pick_fields(obj: dict, fields: Optional[str]) -> dict:
    if not fields:
        return obj
    wanted = {f.strip() for f in fields.split(",") if f.strip()} | {"id"}
    return {k: v for k, v in obj.items() if k in wanted}


def paginate(items: list, page: int, page_size: int) -> tuple[list, int]:
    total = len(items)
    start = (page - 1) * page_size
    return items[start : start + page_size], total


def public_author_v1(a: dict) -> dict:
    return {"id": a["id"], "name": a["name"], "country": a["country"]}


def public_author_v2(a: dict) -> dict:
    return {
        "id": a["id"],
        "name": a["name"],
        "country": a["country"],
        "birth_year": a.get("birth_year"),
    }


def public_book_v1(b: dict) -> dict:
    return {
        "id": b["id"],
        "title": b["title"],
        "author_id": b["author_id"],
        "year": b.get("year"),
    }


def public_book_v2(b: dict) -> dict:
    return {
        "id": b["id"],
        "title": b["title"],
        "author_id": b["author_id"],
        "year": b.get("year"),
        "isbn": b.get("isbn"),
        "genres": b.get("genres", []),
    }


def public_loan_v1(loan: dict) -> dict:
    return {
        "id": loan["id"],
        "book_id": loan["book_id"],
        "reader_name": loan["reader_name"],
        "due_date": loan.get("due_date"),
        "returned": loan.get("returned", False),
    }


def public_loan_v2(loan: dict) -> dict:
    out = public_loan_v1(loan)
    out["notes"] = loan.get("notes", "")
    out["created_at"] = loan.get("created_at")
    return out


# ---- middleware: rate limit ----

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/", "/docs", "/openapi.json", "/redoc", "/health"):
        return await call_next(request)

    key = request.headers.get("X-API-Key") or request.headers.get("X-Internal-Token") or "anon"
    now = time()
    bucket = rate_hits[key]
    while bucket and now - bucket[0] > RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT:
        return JSONResponse(
            {"detail": "Превышен лимит запросов"},
            status_code=429,
            headers={"X-Limit-Remaining": "0", "Retry-After": "60"},
        )
    bucket.append(now)
    response = await call_next(request)
    response.headers["X-Limit-Remaining"] = str(RATE_LIMIT - len(bucket))
    response.headers["Retry-After"] = "0"
    return response


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


# ==================== AUTHORS v1 ====================

@app.get("/api/v1/authors", tags=["authors-v1"])
def list_authors_v1(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fields: Optional[str] = Query(None, description="Через запятую: id,name,country"),
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    """Список авторов (v1). Поддерживает пагинацию и выбор полей."""
    require_api_key(x_api_key)
    items = [public_author_v1(a) for a in authors.values()]
    chunk, total = paginate(items, page, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [pick_fields(x, fields) for x in chunk]


@app.post("/api/v1/authors", status_code=201, tags=["authors-v1"])
def create_author_v1(
    body: AuthorIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    """Создание автора. Повторный POST с тем же Idempotency-Key не создаёт дубликат."""
    require_api_key(x_api_key)
    if idempotency_key and idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
    aid = str(uuid4())
    row = {"id": aid, "name": body.name, "country": body.country, "birth_year": None}
    authors[aid] = row
    out = public_author_v1(row)
    if idempotency_key:
        idempotency_store[idempotency_key] = out
    return out


@app.get("/api/v1/authors/{author_id}", tags=["authors-v1"])
def get_author_v1(
    author_id: str,
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    a = authors.get(author_id)
    if not a:
        raise HTTPException(404, "Автор не найден")
    return pick_fields(public_author_v1(a), fields)


@app.put("/api/v1/authors/{author_id}", tags=["authors-v1"])
def update_author_v1(
    author_id: str,
    body: AuthorIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    if author_id not in authors:
        raise HTTPException(404, "Автор не найден")
    authors[author_id].update(name=body.name, country=body.country)
    return public_author_v1(authors[author_id])


@app.delete("/api/v1/authors/{author_id}", status_code=204, tags=["authors-v1"])
def delete_author_v1(
    author_id: str,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    if author_id not in authors:
        raise HTTPException(404, "Автор не найден")
    linked = [b for b in books.values() if b["author_id"] == author_id]
    if linked:
        raise HTTPException(409, "Нельзя удалить автора: есть связанные книги")
    del authors[author_id]
    return Response(status_code=204)


# ==================== AUTHORS v2 (аддитивно: birth_year) ====================

@app.get("/api/v2/authors", tags=["authors-v2"])
def list_authors_v2(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    items = [public_author_v2(a) for a in authors.values()]
    chunk, total = paginate(items, page, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [pick_fields(x, fields) for x in chunk]


@app.post("/api/v2/authors", status_code=201, tags=["authors-v2"])
def create_author_v2(
    body: AuthorInV2,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    require_api_key(x_api_key)
    cache_key = f"v2:{idempotency_key}" if idempotency_key else None
    if cache_key and cache_key in idempotency_store:
        return idempotency_store[cache_key]
    aid = str(uuid4())
    row = {
        "id": aid,
        "name": body.name,
        "country": body.country,
        "birth_year": body.birth_year,
    }
    authors[aid] = row
    out = public_author_v2(row)
    if cache_key:
        idempotency_store[cache_key] = out
    return out


@app.get("/api/v2/authors/{author_id}", tags=["authors-v2"])
def get_author_v2(
    author_id: str,
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    a = authors.get(author_id)
    if not a:
        raise HTTPException(404, "Автор не найден")
    return pick_fields(public_author_v2(a), fields)


# ==================== BOOKS v1 ====================

@app.get("/api/v1/books", tags=["books-v1"])
def list_books_v1(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fields: Optional[str] = None,
    author_id: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    items = [public_book_v1(b) for b in books.values()]
    if author_id:
        items = [b for b in items if b["author_id"] == author_id]
    chunk, total = paginate(items, page, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [pick_fields(x, fields) for x in chunk]


@app.post("/api/v1/books", status_code=201, tags=["books-v1"])
def create_book_v1(
    body: BookIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    require_api_key(x_api_key)
    if body.author_id not in authors:
        raise HTTPException(400, "author_id не существует")
    if idempotency_key and idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
    bid = str(uuid4())
    row = {
        "id": bid,
        "title": body.title,
        "author_id": body.author_id,
        "year": body.year,
        "isbn": None,
        "genres": [],
    }
    books[bid] = row
    out = public_book_v1(row)
    if idempotency_key:
        idempotency_store[idempotency_key] = out
    return out


@app.get("/api/v1/books/{book_id}", tags=["books-v1"])
def get_book_v1(
    book_id: str,
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    b = books.get(book_id)
    if not b:
        raise HTTPException(404, "Книга не найдена")
    return pick_fields(public_book_v1(b), fields)


@app.put("/api/v1/books/{book_id}", tags=["books-v1"])
def update_book_v1(
    book_id: str,
    body: BookIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    if book_id not in books:
        raise HTTPException(404, "Книга не найдена")
    if body.author_id not in authors:
        raise HTTPException(400, "author_id не существует")
    books[book_id].update(title=body.title, author_id=body.author_id, year=body.year)
    return public_book_v1(books[book_id])


@app.delete("/api/v1/books/{book_id}", status_code=204, tags=["books-v1"])
def delete_book_v1(
    book_id: str,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    if book_id not in books:
        raise HTTPException(404, "Книга не найдена")
    active = [ln for ln in loans.values() if ln["book_id"] == book_id and not ln.get("returned")]
    if active:
        raise HTTPException(409, "Книга выдана читателю")
    del books[book_id]
    return Response(status_code=204)


# ==================== BOOKS v2 (аддитивно: isbn, genres) ====================

@app.get("/api/v2/books", tags=["books-v2"])
def list_books_v2(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    items = [public_book_v2(b) for b in books.values()]
    chunk, total = paginate(items, page, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [pick_fields(x, fields) for x in chunk]


@app.post("/api/v2/books", status_code=201, tags=["books-v2"])
def create_book_v2(
    body: BookInV2,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    require_api_key(x_api_key)
    if body.author_id not in authors:
        raise HTTPException(400, "author_id не существует")
    cache_key = f"v2book:{idempotency_key}" if idempotency_key else None
    if cache_key and cache_key in idempotency_store:
        return idempotency_store[cache_key]
    bid = str(uuid4())
    row = {
        "id": bid,
        "title": body.title,
        "author_id": body.author_id,
        "year": body.year,
        "isbn": body.isbn,
        "genres": list(body.genres),
    }
    books[bid] = row
    out = public_book_v2(row)
    if cache_key:
        idempotency_store[cache_key] = out
    return out


@app.get("/api/v2/books/{book_id}", tags=["books-v2"])
def get_book_v2(
    book_id: str,
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    b = books.get(book_id)
    if not b:
        raise HTTPException(404, "Книга не найдена")
    return pick_fields(public_book_v2(b), fields)


# ==================== LOANS v1 ====================

@app.get("/api/v1/loans", tags=["loans-v1"])
def list_loans_v1(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    items = [public_loan_v1(ln) for ln in loans.values()]
    chunk, total = paginate(items, page, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [pick_fields(x, fields) for x in chunk]


@app.post("/api/v1/loans", status_code=201, tags=["loans-v1"])
def create_loan_v1(
    body: LoanIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    require_api_key(x_api_key)
    if body.book_id not in books:
        raise HTTPException(400, "book_id не существует")
    if idempotency_key and idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
    lid = str(uuid4())
    row = {
        "id": lid,
        "book_id": body.book_id,
        "reader_name": body.reader_name,
        "due_date": body.due_date.isoformat() if body.due_date else None,
        "returned": False,
        "notes": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    loans[lid] = row
    out = public_loan_v1(row)
    if idempotency_key:
        idempotency_store[idempotency_key] = out
    return out


@app.get("/api/v1/loans/{loan_id}", tags=["loans-v1"])
def get_loan_v1(
    loan_id: str,
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    ln = loans.get(loan_id)
    if not ln:
        raise HTTPException(404, "Выдача не найдена")
    return pick_fields(public_loan_v1(ln), fields)


@app.put("/api/v1/loans/{loan_id}", tags=["loans-v1"])
def update_loan_v1(
    loan_id: str,
    body: LoanIn,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    if loan_id not in loans:
        raise HTTPException(404, "Выдача не найдена")
    if body.book_id not in books:
        raise HTTPException(400, "book_id не существует")
    loans[loan_id].update(
        book_id=body.book_id,
        reader_name=body.reader_name,
        due_date=body.due_date.isoformat() if body.due_date else None,
    )
    return public_loan_v1(loans[loan_id])


@app.delete("/api/v1/loans/{loan_id}", status_code=204, tags=["loans-v1"])
def delete_loan_v1(
    loan_id: str,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    if loan_id not in loans:
        raise HTTPException(404, "Выдача не найдена")
    del loans[loan_id]
    return Response(status_code=204)


# ==================== LOANS v2 ====================

@app.get("/api/v2/loans", tags=["loans-v2"])
def list_loans_v2(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fields: Optional[str] = None,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    require_api_key(x_api_key)
    items = [public_loan_v2(ln) for ln in loans.values()]
    chunk, total = paginate(items, page, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [pick_fields(x, fields) for x in chunk]


@app.post("/api/v2/loans", status_code=201, tags=["loans-v2"])
def create_loan_v2(
    body: LoanInV2,
    x_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    require_api_key(x_api_key)
    if body.book_id not in books:
        raise HTTPException(400, "book_id не существует")
    cache_key = f"v2loan:{idempotency_key}" if idempotency_key else None
    if cache_key and cache_key in idempotency_store:
        return idempotency_store[cache_key]
    lid = str(uuid4())
    row = {
        "id": lid,
        "book_id": body.book_id,
        "reader_name": body.reader_name,
        "due_date": body.due_date.isoformat() if body.due_date else None,
        "returned": False,
        "notes": body.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    loans[lid] = row
    out = public_loan_v2(row)
    if cache_key:
        idempotency_store[cache_key] = out
    return out


@app.post("/api/v1/loans/{loan_id}/return", tags=["loans-v1"])
def return_loan_v1(
    loan_id: str,
    x_api_key: Annotated[Optional[str], Header()] = None,
):
    """Аддитивное изменение ЛР1: возврат книги без ломки CRUD."""
    require_api_key(x_api_key)
    ln = loans.get(loan_id)
    if not ln:
        raise HTTPException(404, "Выдача не найдена")
    ln["returned"] = True
    return public_loan_v1(ln)


# ==================== INTERNAL (ЛР2) ====================

@app.get("/internal/stats", tags=["internal"])
def internal_stats(
    x_internal_token: Annotated[Optional[str], Header()] = None,
):
    """Внутренний эндпоинт для мониторинга: агрегаты без публичной схемы."""
    require_internal(x_internal_token)
    active_loans = sum(1 for ln in loans.values() if not ln.get("returned"))
    return {
        "authors": len(authors),
        "books": len(books),
        "loans": len(loans),
        "active_loans": active_loans,
        "idempotency_keys": len(idempotency_store),
    }


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"] = schema.get("components") or {}
    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }
    schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
