"""Клиент Library API через RabbitMQ — лабораторная работа №4.

Публикует запросы в api.requests, ждёт ответ по correlation_id / reply-очереди.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

import aio_pika
from aio_pika import IncomingMessage, Message

AMQP_URL = "amqp://guest:guest@127.0.0.1/"
API_KEY = "library-secret-key"


class RabbitLibraryClient:
    def __init__(self, amqp_url: str = AMQP_URL, auth: str = API_KEY) -> None:
        self.amqp_url = amqp_url
        self.auth = auth
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.Channel] = None
        self._callback_queue: Optional[aio_pika.Queue] = None
        self._futures: dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self.amqp_url)
        self._channel = await self._connection.channel()
        # те же аргументы, что у сервера (иначе PRECONDITION_FAILED)
        await self._channel.declare_queue(
            "api.requests",
            durable=True,
            arguments={"x-dead-letter-exchange": "api.dlx"},
        )
        await self._channel.declare_queue("api.responses", durable=True)
        self._callback_queue = await self._channel.declare_queue(
            exclusive=True, auto_delete=True
        )
        await self._callback_queue.consume(self._on_response)

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()

    async def _on_response(self, message: IncomingMessage) -> None:
        async with message.process():
            corr = message.correlation_id
            if corr and corr in self._futures:
                payload = json.loads(message.body.decode())
                self._futures[corr].set_result(payload)

    async def call(
        self,
        action: str,
        data: Optional[dict] = None,
        version: str = "v1",
        request_id: Optional[str] = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        assert self._channel and self._callback_queue
        req_id = request_id or str(uuid.uuid4())
        body = {
            "id": req_id,
            "version": version,
            "action": action,
            "data": data or {},
            "auth": self.auth,
        }
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._futures[req_id] = future

        await self._channel.default_exchange.publish(
            Message(
                body=json.dumps(body, ensure_ascii=False).encode(),
                correlation_id=req_id,
                reply_to=self._callback_queue.name,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key="api.requests",
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._futures.pop(req_id, None)


async def demo() -> None:
    client = RabbitLibraryClient()
    await client.connect()
    print("Подключено к RabbitMQ")

    fixed_id = str(uuid.uuid4())
    r1 = await client.call(
        "create_author",
        {"name": "Чехов", "country": "Россия"},
        request_id=fixed_id,
    )
    print("create_author:", json.dumps(r1, ensure_ascii=False, indent=2))

    r2 = await client.call(
        "create_author",
        {"name": "Дубликат", "country": "X"},
        request_id=fixed_id,  # тот же id → идемпотентность
    )
    print("create_author (повтор id):", json.dumps(r2, ensure_ascii=False, indent=2))
    assert r1["data"]["id"] == r2["data"]["id"]

    author_id = r1["data"]["id"]
    book = await client.call(
        "create_book",
        {"title": "Вишнёвый сад", "author_id": author_id, "year": 1904},
    )
    print("create_book:", json.dumps(book, ensure_ascii=False, indent=2))

    listed = await client.call("list_authors")
    print("list_authors:", json.dumps(listed, ensure_ascii=False, indent=2))

    v2 = await client.call(
        "create_author",
        {"name": "Булгаков", "country": "Россия", "birth_year": 1891},
        version="v2",
    )
    print("create_author v2:", json.dumps(v2, ensure_ascii=False, indent=2))

    stats = await client.call("stats")
    print("stats:", json.dumps(stats, ensure_ascii=False, indent=2))

    bad = await client.call("get_author", {"id": "missing"})
    print("ошибка get_author:", json.dumps(bad, ensure_ascii=False, indent=2))

    await client.close()
    print("Демо завершено")


if __name__ == "__main__":
    asyncio.run(demo())
