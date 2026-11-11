# Vibe Chat

Корпоративный мессенджер (self-hosted). Продуктовая и архитектурная правда — в [Docs/concept.md](Docs/concept.md), правила для агентов — в [AGENTS.md](AGENTS.md).

## Структура

- `backend/` — FastAPI + SQLAlchemy + Alembic (Python 3.12+)
- `frontend/` — React + TypeScript + Vite (web)
- `deploy/` — docker-compose, realm-export Keycloak, `.env.example`
- `Docs/` — концепция и документация

## Быстрый старт (dev)

Инфраструктура в compose, приложения локально (Docs/concept.md §13):

```bash
# 1. Инфраструктура: postgres, valkey, silo, keycloak
cd deploy
cp .env.example .env
docker compose up -d

# 2. Бэкенд
cd backend
python -m venv ../.venv
../.venv/Scripts/pip install -e ".[dev]"      # Windows; на Linux/macOS: ../.venv/bin/pip
../.venv/Scripts/uvicorn app.main:app --reload

# 3. Фронтенд
cd frontend
npm install
npm run dev
```

Keycloak: http://localhost:8080 (realm `vibe-chat`), Swagger бэкенда: http://localhost:8000/docs, фронт: http://localhost:5173.

## Тесты и качество

```bash
cd backend && ../.venv/Scripts/python -m pytest   # pytest
cd backend && ../.venv/Scripts/python -m ruff check .
cd backend && ../.venv/Scripts/python -m mypy
cd frontend && npm run typecheck && npm test      # vitest
```

pre-commit: `pre-commit install` (ruff + базовые хуки; mypy/vitest запускаются вручную или в CI).

## Полный запуск в контейнерах

```bash
cd deploy && docker compose --profile full up --build
```
