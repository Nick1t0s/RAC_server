# Команды клиента (RAC agent)

Список команд, которые понимает агент `client/agent.py`. Команда отправляется
через админку или прямой вызов `POST /api/web/commands` и состоит из:

- `name` — имя команды (одно слово, без пробелов).
- `payload` — аргументы (текст, путь, DSL — зависит от команды).
- `upload_id` — необязательный id заранее загруженного файла (нужен `post`).

В админке поле `#cmd-name` принимает обе части одной строкой: первое слово
становится `name`, остаток — `payload`. Например `exec ping 8.8.8.8`
сохранится как `name="exec"`, `payload="ping 8.8.8.8"`.

Любая команда возвращает JSON-результат с полями:

- `status` — `done` или `error`.
- `output` — строковый вывод (stdout/stderr, лог действий, текст ошибки).
- опционально `output_file_path` — путь к прикреплённому файлу-результату
  на сервере (`cmds/<name>/<timestamp>_<filename>`).

Неизвестное `name` → `status="error"`, `output="неизвестная команда: <name>"`.
Любое исключение в обработчике ловится и возвращается как `error` с traceback —
агент не падает на одной плохой команде.

---

## `exec` — shell-команда

Запускает `payload` через `subprocess.run(..., shell=True)` с таймаутом
`exec_timeout_sec` из `client/config.json` (по умолчанию 120 с).

- `payload` — командная строка для системного шелла (`cmd.exe` на Windows,
  `/bin/sh` на Linux/macOS).
- Результат: `stdout` + `stderr` + строка `[exit code: N]`.
- `status="done"` если код возврата 0, иначе `error`.
- Таймаут → `error` с накопленным выводом.

На Windows байты декодируются по OEM-кодировке (cp866 на русской локали),
не cp1251 — иначе вывод `cmd.exe` превратится в кракозябры.

Примеры:

```
exec ping -n 2 8.8.8.8
exec dir C:\Windows
exec whoami /all
```

---

## `get` — забрать файл/директорию с клиента

`payload` — путь на клиенте (поддерживается `~`).

- Файл → отправляется как есть, имя сохраняется.
- Директория → упаковывается в zip в памяти, имя архива `<dirname>.zip`,
  внутри корнем лежит сама папка (`<dirname>/...`). Файлы, которые не удалось
  прочитать, пропускаются — их список (до 20) попадает в `output`.

Серверный путь результата: `cmds/get/<timestamp>_<filename>`.

Примеры:

```
get C:\Users\user\Desktop\notes.txt
get ~/Documents
get /var/log/syslog
```

---

## `post` — отправить файл на клиент

Перед командой админ загружает файл (`POST /api/web/uploads`) и передаёт его
`upload_id` вместе с командой — сервер прокинет на клиента ссылку
(`has_file=true`, `file_url`).

- `payload` — путь назначения на клиенте.
  - пусто → файл сохранится рядом с агентом под исходным именем;
  - оканчивается на `/` или `\` или указывает на существующую директорию →
    в эту папку под исходным именем;
  - иначе → ровно по этому пути (родительские каталоги создаются).

Примеры:

```
post C:\tmp\
post /home/user/payload.bin
post                       # рядом с agent.py под исходным именем
```

---

## `screenshot` — снимок всех мониторов

`payload` игнорируется. Снимает все экраны как один прямоугольник через
`mss` и шлёт PNG. В `output` — размер картинки.

Зависимость: `mss`. Серверный путь:
`cmds/screenshot/<timestamp>_screenshot.png`.

---

## `photo` — кадр с веб-камеры

`payload` — индекс камеры (целое, по умолчанию `0`). Используется
`opencv-python`; на Windows — backend `CAP_DSHOW`. Прогрев 5 кадров
(первые часто чёрные), затем PNG в результат.

Зависимость: `opencv-python`. В `output` — `photo WxH cam=N`.
Серверный путь: `cmds/photo/<timestamp>_photo.png`.

Примеры:

```
photo
photo 1
```

---

## `input` — эмуляция мыши и клавиатуры

`payload` — мини-DSL: одна строка = одно действие. Пустые строки и строки,
начинающиеся с `#`, игнорируются. Failsafe `pyautogui` включён — курсор
в углу `(0, 0)` прерывает выполнение.

Зависимость: `pyautogui`. На Linux дополнительно нужны `python3-tk`,
`python3-dev`, `scrot` (для скриншотов внутри pyautogui).

### Действия

| Действие | Аргументы | Описание |
|---|---|---|
| `move` | `x y [dur]` | переместить курсор в абсолютные координаты |
| `moveto` | `x y [dur]` | алиас `move` |
| `moverel` | `dx dy [dur]` | переместить относительно текущей позиции |
| `click` | `[x y] [button] [clicks]` | клик; `button` ∈ `left`/`right`/`middle` |
| `doubleclick` | `[x y]` | двойной клик |
| `rightclick` | `[x y]` | правый клик |
| `mousedown` | `[x y] [button]` | зажать кнопку |
| `mouseup` | `[x y] [button]` | отпустить кнопку |
| `drag` | `dx dy [dur] [button]` | drag относительно |
| `dragto` | `x y [dur] [button]` | drag в абсолютную точку |
| `scroll` | `N [x y]` | вертикальный скролл (`+` вверх, `−` вниз) |
| `hscroll` | `N [x y]` | горизонтальный скролл (Linux) |
| `press` | `key [count]` | нажать клавишу `count` раз |
| `keydown` | `key` | зажать клавишу |
| `keyup` | `key` | отпустить клавишу |
| `hotkey` | `k1 k2 ...` | комбинация (`hotkey ctrl c`) |
| `type` | `<текст>` | напечатать остаток строки (только ASCII) |
| `write` | `<текст>` | алиас `type` |
| `sleep` | `секунды` | пауза (поддерживает дроби) |

`dur` — длительность движения в секундах (`0` = мгновенно).

Имена клавиш — как у `pyautogui.KEY_NAMES` (`enter`, `esc`, `tab`, `space`,
`backspace`, `delete`, `f1`…`f12`, `up`/`down`/`left`/`right`, `home`/`end`,
`pageup`/`pagedown`, `ctrl`/`shift`/`alt`, `win`/`winleft`/`winright`,
`a`…`z`, `0`…`9`, …).

`type` использует `pyautogui.write` — кириллицу он не печатает. Для не-ASCII
кладите текст в буфер обмена и вставляйте через `hotkey ctrl v` (буфер
заполняется отдельно — например, через `exec` с `clip`/`xclip`).

`output` — построчный лог: `<lineno>: <line> ok` для каждого действия плюс
финальная позиция курсора. Первая ошибка прерывает выполнение, всё что
успело отработать — остаётся в `output`.

### Примеры

Открыть «Пуск» и запустить «Блокнот»:

```
hotkey win
sleep 0.3
type notepad
press enter
```

Кликнуть и перетащить:

```
move 100 200 0.2
mousedown
moverel 300 0 0.5
mouseup
```

Скриншот через Win+Shift+S:

```
hotkey win shift s
```

Скролл вниз 5 «щелчков» в точке (800, 400):

```
scroll -5 800 400
```

Серия Alt+Tab:

```
keydown alt
press tab 3
keyup alt
```

---

## Краткая шпаргалка по строке `#cmd-name`

```
exec dir
get C:\file.txt
post C:\dest\
screenshot
photo 0
input
click 500 300
press enter
type hello
```

(многострочный `input` удобнее слать прямым `POST /api/web/commands`
с явным `payload`).
