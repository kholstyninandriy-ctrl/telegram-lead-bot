# AI-Рецепціоніст (WOW-демо для продажів)

Один сервіс для **чату на сайті** і **голосового агента (Vapi)**: відповідає за 2–3 с,
кваліфікує клієнта, пропонує вільні слоти, збирає ім'я й телефон, **бронює в календар**,
пише власнику в Telegram.

```
Віджет (widget.js) ─┐
                    ├─► FastAPI (app.py) ─► OpenAI gpt-4o-mini + tools
Vapi (телефон) ─────┘         │
                              ├─► Календар: Cal.com | Google Calendar | Mock
                              ├─► SQLite (bookings)
                              └─► Telegram-сповіщення власнику
```

## 1. Запуск локально (5 хв)

```bash
cd receptionist
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # або OPENAI_API_KEY
uvicorn app:app --reload
# → http://127.0.0.1:8000
```
Без календарних ключів працює **mock-календар**, тож демо запускається одразу.
Офлайн-тест усього потоку: `python test_flow.py`.

## 2. Деплой на Render

1. render.com → New → **Blueprint** → цей репозиторій (`render.yaml` уже є).
2. Заповни `ANTHROPIC_API_KEY` (або `OPENAI_API_KEY`), а `PUBLIC_URL` = URL сервісу (напр. `https://ai-receptionist.onrender.com`).
3. Перевір `/health` → `{"ok": true, "calendar": "mock", "llm": "anthropic", ...}`.

> Free-план Render «засинає»: перший запит іде ~30 с. Перед демо відкрий `/health` або візьми Starter ($7).

## 3. Календар (обери один)

**Cal.com (найшвидше):** Settings → Developer → API Keys → створи ключ. Id типу події
видно в URL, коли відкриваєш Event Type. Далі `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`.

**Google Calendar:**
1. Google Cloud → увімкни *Google Calendar API* → створи Service Account → Keys → JSON.
2. У Google Calendar → Налаштування календаря → «Поділитися з певними людьми» → email service account → *Вносити зміни в події*.
3. `GOOGLE_SERVICE_ACCOUNT_JSON` = вміст JSON-файлу, `GOOGLE_CALENDAR_ID` = Calendar ID (з налаштувань календаря).

## 4. Сповіщення в Telegram

`TELEGRAM_BOT_TOKEN` (можна від Lead Finder бота) + `OWNER_CHAT_ID`, тобто твій chat id (напиши @userinfobot).

## 5. Голосовий агент (Vapi) — «Зателефонуйте нашому AI»

1. Відкрий `https://<PUBLIC_URL>/api/vapi/assistant-config?niche=real_estate&business_name=Skyline%20Realty`, там готовий JSON асистента.
2. Vapi Dashboard → Assistants → Create, потім вставити prompt/firstMessage/tools з JSON
   (або `POST https://api.vapi.ai/assistant` з цим JSON і `Authorization: Bearer <VAPI_PRIVATE_KEY>`).
3. Замінити `<VAPI_SECRET>` на значення з Render (Vapi шле його в заголовку `X-Vapi-Secret`).
4. Vapi → Phone Numbers → Buy/Import (Twilio) → прив'язати асистента.
5. Дзвониш, бронюєш, і подія з'являється в календарі, а в Telegram приходить сповіщення.

## 6. Демо під конкретного клієнта

Параметри URL демо-сторінки:
```
https://<PUBLIC_URL>/?business=Smile%20Dental&niche=dental&color=%2310b981&phone=%2B15551234567&logo=https://site.com/logo.png
```
Ніші: `real_estate`, `dental`, `beauty`, `auto` (додаються в `niches.py`).

Вставка на сайт клієнта:
```html
<script src="https://<PUBLIC_URL>/widget.js"
        data-business="Smile Dental" data-niche="dental"
        data-color="#10b981" data-phone="+15551234567"></script>
```
Віджет можна захостити й на Vercel (`static/`), тоді додай `data-api="https://<PUBLIC_URL>"`.

## API

| Метод | Шлях | Опис |
|---|---|---|
| POST | `/api/chat` | `{message, session_id?, niche?, business_name?, services?}` → `{session_id, reply}` |
| POST | `/api/vapi/tools` | Webhook інструментів Vapi |
| GET | `/api/vapi/assistant-config` | JSON асистента для Vapi |
| GET | `/api/bookings` | Записи (`Authorization: Bearer $ADMIN_TOKEN`) |
| GET | `/health` | Статус |
