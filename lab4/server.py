"""Сервер Library API через RabbitMQ — лабораторная работа №4.

Очереди:
  api.requests  — входящие запросы
  api.responses — ответы (reply-to)
  api.dlq       — Dead Letter Queue

Запуск:
  docker compose up -d
  python server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, IncomingMessage, Message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lab4.server")

AMQP_URL = "amqp://guest:guest@127.0.0.1/"
API_KEY = "library-secret-key"
MAX_RETRIES = 3

authors: dict[str, dict] = {}
books: dict[str, dict] = {}
loans: dict[str, dict] = {}
processed_ids: dict[str, dict] = {}
error_log: list[dict] = []


def check_auth(auth: Any) -> Optional[str]:
    if auth != API_KEY:
        return "Неверный auth (ожидается API-ключ library-secret-key)"
    return None


def handle_action(version: str, action: str, data: dict) -> dict:
    data = data or {}

    if action == "create_author":
        aid = str(uuid4())
        row = {
            "id": aid,
            "name": data["name"],
            "country": data.get("country", ""),
            "birth_year": data.get("birth_year") if version == "v2" else None,
        }
        authors[aid] = row
        if version == "v2":
            return {
                "id": aid,
                "name": row["name"],
                "country": row["country"],
                "birth_year": row["birth_year"],
            }
        return {"id": aid, "name": row["name"], "country": row["country"]}

    if action == "list_authors":
        items = list(authors.values())
        if version == "v1":
            return [
                {"id": a["id"], "name": a["name"], "country": a["country"]}
                for a in items
            ]
        return [
            {
                "id": a["id"],
                "name": a["name"],
                "country": a["country"],
                "birth_year": a.get("birth_year"),
            }
            for a in items
        ]

    if action == "get_author":
        a = authors.get(data["id"])
        if not a:
            raise KeyError("Автор не найден")
        if version == "v1":
            return {"id": a["id"], "name": a["name"], "country": a["country"]}
        return {
            "id": a["id"],
            "name": a["name"],
            "country": a["country"],
            "birth_year": a.get("birth_year"),
        }

    if action == "update_author":
        a = authors.get(data["id"])
        if not a:
            raise KeyError("Автор не найден")
        a["name"] = data.get("name", a["name"])
        a["country"] = data.get("country", a["country"])
        if version == "v2" and "birth_year" in data:
            a["birth_year"] = data["birth_year"]
        return {
            "id": a["id"],
            "name": a["name"],
            "country": a["country"],
            **({"birth_year": a.get("birth_year")} if version == "v2" else {}),
        }

    if action == "delete_author":
        aid = data["id"]
        if aid not in authors:
            raise KeyError("Автор не найден")
        if any(b["author_id"] == aid for b in books.values()):
            raise ValueError("Есть связанные книги")
        del authors[aid]
        return {"deleted": aid}

    if action == "create_book":
        if data["author_id"] not in authors:
            raise ValueError("author_id не существует")
        bid = str(uuid4())
        row = {
            "id": bid,
            "title": data["title"],
            "author_id": data["author_id"],
            "year": data.get("year"),
            "isbn": data.get("isbn") if version == "v2" else None,
            "genres": list(data.get("genres", [])) if version == "v2" else [],
        }
        books[bid] = row
        if version == "v1":
            return {
                "id": bid,
                "title": row["title"],
                "author_id": row["author_id"],
                "year": row["year"],
            }
        return row

    if action == "list_books":
        if version == "v1":
            return [
                {
                    "id": b["id"],
                    "title": b["title"],
                    "author_id": b["author_id"],
                    "year": b.get("year"),
                }
                for b in books.values()
            ]
        return list(books.values())

    if action == "get_book":
        b = books.get(data["id"])
        if not b:
            raise KeyError("Книга не найдена")
        if version == "v1":
            return {
                "id": b["id"],
                "title": b["title"],
                "author_id": b["author_id"],
                "year": b.get("year"),
            }
        return b

    if action == "update_book":
        b = books.get(data["id"])
        if not b:
            raise KeyError("Книга не найдена")
        for key in ("title", "author_id", "year", "isbn", "genres"):
            if key in data:
                b[key] = data[key]
        return b

    if action == "delete_book":
        bid = data["id"]
        if bid not in books:
            raise KeyError("Книга не найдена")
        del books[bid]
        return {"deleted": bid}

    if action == "create_loan":
        if data["book_id"] not in books:
            raise ValueError("book_id не существует")
        lid = str(uuid4())
        row = {
            "id": lid,
            "book_id": data["book_id"],
            "reader_name": data["reader_name"],
            "due_date": data.get("due_date"),
            "returned": False,
            "notes": data.get("notes", "") if version == "v2" else "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        loans[lid] = row
        if version == "v1":
            return {
                "id": lid,
                "book_id": row["book_id"],
                "reader_name": row["reader_name"],
                "due_date": row["due_date"],
                "returned": False,
            }
        return row

    if action == "list_loans":
        return list(loans.values())

    if action == "return_loan":
        ln = loans.get(data["id"])
        if not ln:
            raise KeyError("Выдача не найдена")
        ln["returned"] = True
        return ln

    if action == "stats":
        return {
            "authors": len(authors),
            "books": len(books),
            "loans": len(loans),
        }

    raise ValueError(f"Неизвестное действие: {action}")


async def publish_response(
    channel: aio_pika.Channel,
    reply_to: str,
    correlation_id: str,
    result: dict,
) -> None:
    body = {
        "correlation_id": correlation_id,
        "status": result["status"],
        "data": result.get("data"),
        "error": result.get("error"),
    }
    await channel.default_exchange.publish(
        Message(
            body=json.dumps(body, ensure_ascii=False).encode(),
            correlation_id=correlation_id,
            content_type="application/json",
        ),
        routing_key=reply_to,
    )
    log.info("Ответ correlation_id=%s status=%s", correlation_id, result["status"])


async def republish_with_retry(
    channel: aio_pika.Channel,
    message: IncomingMessage,
    retries: int,
) -> None:
    headers = dict(message.headers or {})
    headers["x-retries"] = retries + 1
    await channel.default_exchange.publish(
        Message(
            body=message.body,
            correlation_id=message.correlation_id,
            reply_to=message.reply_to,
            content_type=message.content_type,
            headers=headers,
            delivery_mode=DeliveryMode.PERSISTENT,
        ),
        routing_key="api.requests",
    )
    log.warning("Retry %s для correlation_id=%s", retries + 1, message.correlation_id)


async def on_message(message: IncomingMessage, channel: aio_pika.Channel) -> None:
    retries = int((message.headers or {}).get("x-retries", 0))
    reply_to = message.reply_to or "api.responses"

    try:
        payload = json.loads(message.body.decode())
    except json.JSONDecodeError as exc:
        log.error("Невалидный JSON: %s", exc)
        error_log.append(
            {
                "error": "invalid_json",
                "body": message.body.decode(errors="replace"),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        await message.reject(requeue=False)  # → DLQ
        return

    req_id = payload.get("id") or message.correlation_id or str(uuid4())
    version = payload.get("version", "v1")
    action = payload.get("action", "")
    data = payload.get("data") or {}
    auth = payload.get("auth")
    log.info("Запрос id=%s action=%s version=%s", req_id, action, version)

    if req_id in processed_ids:
        await publish_response(channel, reply_to, req_id, processed_ids[req_id])
        await message.ack()
        return

    auth_err = check_auth(auth)
    if auth_err:
        result = {"status": "error", "data": None, "error": auth_err}
        processed_ids[req_id] = result
        await publish_response(channel, reply_to, req_id, result)
        await message.ack()
        return

    try:
        data_out = handle_action(version, action, data)
        result = {"status": "ok", "data": data_out, "error": None}
        processed_ids[req_id] = result
        await publish_response(channel, reply_to, req_id, result)
        await message.ack()
    except (KeyError, ValueError) as exc:
        err = exc.args[0] if exc.args else str(exc)
        result = {"status": "error", "data": None, "error": err}
        processed_ids[req_id] = result
        await publish_response(channel, reply_to, req_id, result)
        await message.ack()
    except Exception as exc:
        log.exception("Временная ошибка")
        error_log.append(
            {
                "id": req_id,
                "action": action,
                "error": str(exc),
                "retries": retries,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        if retries + 1 < MAX_RETRIES:
            await republish_with_retry(channel, message, retries)
            await message.ack()
        else:
            log.error("Исчерпаны retry → DLQ id=%s", req_id)
            await message.reject(requeue=False)


async def main() -> None:
    connection = await aio_pika.connect_robust(AMQP_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    dlx = await channel.declare_exchange("api.dlx", ExchangeType.FANOUT, durable=True)
    dlq = await channel.declare_queue("api.dlq", durable=True)
    await dlq.bind(dlx)

    requests_q = await channel.declare_queue(
        "api.requests",
        durable=True,
        arguments={"x-dead-letter-exchange": "api.dlx"},
    )
    await channel.declare_queue("api.responses", durable=True)

    async def handler(message: IncomingMessage) -> None:
        await on_message(message, channel)

    await requests_q.consume(handler)
    log.info("Сервер слушает api.requests (%s)", AMQP_URL)
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановка сервера")
