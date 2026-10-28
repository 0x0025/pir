# Library API (ЛР1 + ЛР2)

REST API библиотеки: **авторы**, **книги**, **выдачи**.

## Запуск

```bash
cd api
pip install -r requirements.txt   # или из корня: ../.venv/bin/pip install -r requirements.txt
uvicorn main:app --port 8000
# либо: python main.py
```

Документация OpenAPI: http://127.0.0.1:8000/docs

Ключ: `X-API-Key: library-secret-key`

Внутренний токен: `X-Internal-Token: internal-secret`

## Предметная область

| Сущность | Связи |
|----------|--------|
| Author   | 1 → N Book |
| Book     | N → 1 Author; 1 → N Loan |
| Loan     | N → 1 Book (читатель — строка `reader_name`) |

## Версии

| Версия | Отличия |
|--------|---------|
| `/api/v1/` | Базовые поля CRUD |
| `/api/v2/` | Аддитивно: `birth_year` у автора; `isbn`, `genres` у книги; `notes`, `created_at` у выдачи |

v1 продолжает работать после появления v2.

## Аутентификация

Выбран **API-ключ** в заголовке `X-API-Key`: просто для учебного API без сессий и OAuth-инфраструктуры.

## Идемпотентность

Заголовок `Idempotency-Key` на POST. Повтор с тем же ключом возвращает сохранённый ответ без нового ресурса.

## Rate limiting

60 запросов / минуту на ключ. Заголовки ответа: `X-Limit-Remaining`, `Retry-After`.

## ЛР2: расширения (обратимо совместимые)

- **Пагинация**: `?page=1&page_size=20`, заголовок `X-Total-Count` (offset/limit — проще для in-memory).
- **Опциональные поля**: `?fields=id,name,title`.
- **Internal**: `GET /internal/stats` с `X-Internal-Token`.

## Примеры

```bash
# Создать автора
curl -s -X POST http://127.0.0.1:8000/api/v1/authors \
  -H "X-API-Key: library-secret-key" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: author-1" \
  -d '{"name":"Толстой","country":"Россия"}'

# Список с пагинацией и полями
curl -s "http://127.0.0.1:8000/api/v1/authors?page=1&page_size=5&fields=id,name" \
  -H "X-API-Key: library-secret-key" -D -

# Internal
curl -s http://127.0.0.1:8000/internal/stats \
  -H "X-Internal-Token: internal-secret"
```
