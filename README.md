DenisPredicts v6 — Полная упаковка (готово к деплою)

Содержимое:
- backend/ — FastAPI приложение, содержит Dockerfile + render.yaml
- frontend/ — Next.js приложение (готово для Vercel)
- README.md (этот файл) — инструкция ниже

ВАЖНО: в архив уже вставлены твои ключи API-Football и OddsPortal в backend/.env.
Если хочешь, можешь заменить их на переменные окружения на платформе (рекомендуется).

Шаги для быстрого деплоя:

A) Backend (Render) — автоматический деплой через Docker
1. Зарегистрируйся на https://render.com
2. Создай новый Web Service -> Connect a repository OR Manual -> Upload (загрузить папку backend)
3. Render обнаружит Dockerfile и соберёт образ.
4. Задай Environment variables (если не хочешь хранить в файле .env):
   - API_KEY (если не в .env)
   - BASE_URL=https://api-football-v1.p.rapidapi.com/v3
   - ODDSPORTAL_KEY (если не в .env)
   - ODDSPORTAL_URL (укажи реальный URL OddsPortal API)
   - OPENAI_API_KEY (опционально)
5. Запусти сервис. URL будет, например, https://denispredicts-backend.onrender.com

B) Frontend (Vercel)
1. Войди в https://vercel.com
2. Создай новый проект -> Import -> загрузить папку frontend (или подключить GitHub)
3. В Project Settings -> Environment Variables добавь:
   - BACKEND_URL = https://denispredicts-backend.onrender.com
4. Deploy. Сайт появится, например, https://denispredicts.vercel.app

Локальный запуск (тест):
1) Backend:
   cd backend
   pip install -r requirements.txt
   (проверь .env)
   uvicorn main:app --reload --port 8000

2) Frontend:
   cd frontend
   npm install
   npm run dev
   Открой: http://localhost:3000

Если хочешь, могу:
- Залить этот проект в GitHub (создать репозиторий и commit) — ты сможешь подключить напрямую к Render и Vercel.  
- Подробно настроить вебхуки/cron для обновлений или настроить мониторинг и alert'ы.

