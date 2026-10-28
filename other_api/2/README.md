# ЛР2 — расширение REST API

Тот же API, что в ЛР1, плюс:

- пагинация: `?page=1&page_size=10` + заголовок `X-Total-Count`
- поля: `?fields=id,name`
- internal: `GET /internal/stats` с `X-Internal-Token: internal-secret`

```bash
python main.py
# или: uvicorn main:app --port 8002
```

http://127.0.0.1:8002/ → `/docs`

Совместимость: списки по-прежнему JSON-массив.
