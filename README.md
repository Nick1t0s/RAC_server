# RAC Server

Сервер удалённого управления ПК. FastAPI + SQLite + Jinja2 + ванильный JS.

В одном приложении: API для агентов и веб-админка с консолью, проводником и
загрузкой файлов.

## Установка

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

## Настройка

1. Сгенерировать пароль и `session_secret`:

   ```bash
   python generate_password.py
   ```

   Скрипт спросит пароль (с подтверждением), напечатает `password_hash`
   и `session_secret`. Файл `config.yaml` он не трогает.

2. Открыть `config.yaml` и заменить:
   - `auth.password_hash` — на полученный bcrypt-хэш
   - `auth.session_secret` — на сгенерированный секрет (≥ 32 символа)

3. Опционально — поправить порт, лимиты, пути в `config.yaml`.

С плейсхолдерами `REPLACE_ME...` сервер откажется стартовать.

## Запуск

```bash
python main.py
```

Создаются `data.db`, `cmds/`, `uploads/`. Слушает `host:port` из конфига.
По адресу `http://<host>:<port>/` — веб-админка (логин: значение из
`auth.username`).

## Деплой

За reverse proxy с HTTPS (nginx/Caddy/etc.). HTTPS внутри сервера
не реализован намеренно. При работе за прокси используется leftmost-IP
из `X-Forwarded-For`.

## HTTP-протокол агента

Базовый префикс `/api/agent/`. Все ответы — JSON, кроме скачиваний файлов.
Все эндпоинты, кроме `/register`, требуют заголовок
`Authorization: Bearer <token>`. Без токена / с невалидным — `401`.

Рекомендуемый интервал поллинга: см. `polling.agent_poll_interval_sec` в
`config.yaml` (по умолчанию 2 секунды).

### `POST /api/agent/register`

Регистрация при первом запуске. Без авторизации.

Body (JSON):
```json
{ "mac": "AA:BB:CC:DD:EE:FF", "hostname": "USER-PC", "ip": "192.168.1.10" }
```

Валидация:
- `mac` — `^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$`, нормализуется в верхний
  регистр с `:`.
- `hostname` — непустая строка до 255 символов.

Если запись с такой же парой `(mac, hostname)` уже есть — обновляется
`last_ip`/`last_seen` и **возвращается существующий токен**.

Ответ (200):
```json
{ "device_id": 5, "token": "abc...xyz" }
```

Токен сохраняется агентом локально и используется для всех последующих
запросов.

### `GET /api/agent/command`

Получить следующую команду из очереди (FIFO). Если pending-команд нет —
`204 No Content`.

Если есть:
```json
{
  "command_id": 42,
  "name": "screenshot",
  "payload": "fullscreen --quality=80",
  "has_file": false,
  "file_url": null
}
```

Если у команды есть прикреплённый админом файл —
`has_file: true`, `file_url: "/api/agent/command/42/file"`.

Команда сразу переводится в статус `in_progress`.

### `GET /api/agent/command/{command_id}/file`

Скачать файл, прикреплённый админом к этой команде. Доступ только
у устройства-владельца команды. `Content-Type: application/octet-stream`,
оригинальное имя в `Content-Disposition`.

Ошибки: 404 (нет команды / нет файла / чужая команда).

### `POST /api/agent/result`

Отправить результат выполнения. **multipart/form-data**.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `command_id` | int | да | ID команды |
| `status` | str | да | `done` или `error` |
| `output` | str | да | Текстовый вывод (может быть пустой строкой) |
| `file` | file | нет | Опциональный файл-результат |

Файл сохраняется на сервере как
`cmds/<sanitized_command_name>/<timestamp>_<sanitized_filename>`.

Ответы:
- `200 {"ok": true}` — успех.
- `400` — невалидный `status`.
- `404` — нет команды / чужая команда.
- `409` — команда уже завершена (`done`/`error`).
- `413` — файл больше `max_upload_size_mb`.

## Сценарий клиента (псевдокод)

```
1. token = local_load() or register(mac, hostname, ip).token
2. loop:
     resp = GET /api/agent/command   (Authorization: Bearer <token>)
     if 204: sleep(2); continue
     cmd = resp.json()
     if cmd.has_file:
         data = GET cmd.file_url
     output, exit = execute(cmd.name, cmd.payload, data)
     POST /api/agent/result (command_id, status='done'|'error', output, file=optional)
```

## Что не реализовано (по ТЗ)

- Никаких WebSocket / SSE — только polling.
- Никаких ORM, никаких сборщиков фронта.
- Регистрация новых пользователей — только один админ из конфига.
- Автоматических чисток БД и файлов нет — история сохраняется навсегда.
- Сам агент — отдельный проект, не входит сюда.
