# ПИР — лабораторные работы (локально)

Студент: **Орлов Михаил Дмитриевич**, группа **231-331**.

| Каталог | Содержание |
|---------|------------|
| `api/` | ЛР1+ЛР2 — REST API библиотеки (FastAPI) |
| `lab3/` | ЛР3 — клиент к `other_api/2` (Strategies API) |
| `lab4/` | ЛР4 — тот же домен через RabbitMQ |
| `other_api/` | Чужой API для ЛР3 |
| `reports/` | Отчёты DOCX |

Репозиторий GitVerse не создавался (по указанию — локальная версия).

## Быстрый старт

```bash
# зависимости уже в .venv
source .venv/bin/activate

# ЛР1/2
cd api && uvicorn main:app --port 8000

# ЛР3: сначала other_api/2 на :8002, затем lab3/client.py

# ЛР4
cd lab4 && docker compose up -d && python server.py
# в другом терминале: python client.py
```

Отчёты: `reports/231-331_Орлов-лаб{1,2,3,4}.docx`  
Пересборка: `python reports/generate_reports.py`
