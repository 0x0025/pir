# ЛР4 — Library API через RabbitMQ

Те же сущности, что в ЛР1 (авторы, книги, выдачи), но взаимодействие асинхронное через брокер.

## Схема обмена

```
Клиент ──publish──► api.requests ──► Сервер
Клиент ◄──reply──── (reply-to / api.responses) ◄── Сервер
                         │
                         ▼ (после ошибок / nack)
                      api.dlx → api.dlq
```

## Запуск

```bash
cd lab4
docker compose up -d          # RabbitMQ :5672, UI :15672 (guest/guest)
# подождите ~10 с до готовности брокера (иначе Connection reset)

# терминал 1
../.venv/bin/python server.py

# терминал 2
../.venv/bin/python client.py
```

## Формат сообщений

Запрос:

```json
{
  "id": "uuid",
  "version": "v1",
  "action": "create_author",
  "data": {"name": "Чехов", "country": "Россия"},
  "auth": "library-secret-key"
}
```

Ответ:

```json
{
  "correlation_id": "uuid",
  "status": "ok",
  "data": { ... },
  "error": null
}
```

## Действия (action)

`create_author`, `list_authors`, `get_author`, `update_author`, `delete_author`,  
`create_book`, `list_books`, `get_book`, `update_book`, `delete_book`,  
`create_loan`, `list_loans`, `return_loan`, `stats`

Версия `v2` добавляет поля `birth_year` / `isbn` / `genres` / `notes` (как в REST).

## Механизмы

| Механизм | Реализация |
|----------|------------|
| Auth | поле `auth` = API-ключ |
| Идемпотентность | повтор с тем же `id` возвращает кэш |
| Retry / DLQ | очередь `api.requests` с `x-dead-letter-exchange` → `api.dlq` |
| Журнал ошибок | `error_log` на сервере + логи logging |

## Сравнение с REST

REST — синхронный запрос-ответ по HTTP, удобен для CRUD и документации OpenAPI.  
RabbitMQ — асинхронность, буферизация при пиках, устойчивость к кратковременным сбоям сервера; сложнее отладка и нет «из коробки» Swagger.
