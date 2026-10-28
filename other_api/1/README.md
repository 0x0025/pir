# ЛР1 — REST API (упрощённо)

Одна сущность: **strategy**. In-memory. Файл: `main.py`.

```bash
pip install -r requirements.txt
python main.py
# или: uvicorn main:app --port 8001
```

Откройте http://127.0.0.1:8001/ (редирект на `/docs`) или сразу `/docs`.  
Ключ: `X-API-Key: demo-key`

| Метод | Путь |
|-------|------|
| GET/POST | `/api/v1/strategies` |
| GET/PUT/DELETE | `/api/v1/strategies/{id}` |
| GET/POST | `/api/v2/strategies` (+ поле `tags`) |

- Идемпотентность: заголовок `Idempotency-Key` на POST v1  
- Rate limit: 60/мин, заголовки `X-Limit-Remaining`, `Retry-After`  
- Auth: API-ключ (просто для демо)
