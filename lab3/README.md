# ЛР3 — клиент к чужому Strategies API

Клиент на **Python + httpx** для API из `other_api/2` (Strategies API).

## Что делает

- Аутентификация через `X-API-Key: demo-key`
- CRUD: list / create / get / update / delete
- Пагинация (`page`, `page_size`) и `fields`
- Идемпотентный POST с `Idempotency-Key`
- Internal `GET /internal/stats`
- Обработка 401 / 404 / 429 и сетевых ошибок

## Запуск

Терминал 1 — API:

```bash
cd other_api/2
# из корня проекта:
../.venv/bin/uvicorn main:app --port 8002
```

Терминал 2 — клиент:

```bash
cd lab3
../.venv/bin/python client.py
```

## Структура

| Файл | Назначение |
|------|------------|
| `client.py` | Класс `StrategiesClient` и демо-сценарий |
| `README.md` | Описание |

API: локально `http://127.0.0.1:8002/docs` (репозиторий `other_api/2`).
