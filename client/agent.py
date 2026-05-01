"""RAC агент-клиент.

Поддерживает команды:
  - exec       — выполнить shell-команду (payload), вернуть stdout/stderr
  - get        — отдать файл/директорию с клиента (payload = путь;
                 директория шлётся как <name>.zip)
  - post       — принять файл от сервера (payload = путь назначения на клиенте)
  - screenshot — снимок экрана(ов) PNG
  - photo      — кадр с веб-камеры PNG
  - input      — эмуляция мыши/клавиатуры через pyautogui (мини-DSL в payload)

Конфиг зашит в код (см. CONFIG ниже).
Токен сохраняется в client/token.txt — повторная регистрация безопасна
(сервер возвращает тот же токен по паре mac+hostname).
"""
from __future__ import annotations

import io
import locale
import logging
import os
import re
import socket
import subprocess
import sys
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import requests

BASE_DIR = Path(__file__).resolve().parent
TOKEN_PATH = Path(r"C:\rac_windows\token.txt")

CONFIG = {
    "server_url": "http://127.0.0.1:8000",
    "poll_interval_sec": 2,
    "request_timeout_sec": 30,
    "exec_timeout_sec": 120,
}

log = logging.getLogger("agent")


# -------------------- системная информация --------------------

def get_mac() -> str:
    n = uuid.getnode()
    mac = ":".join(f"{(n >> i) & 0xFF:02X}" for i in range(40, -1, -8))
    return mac


def get_hostname() -> str:
    return socket.gethostname() or "unknown-host"


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# -------------------- конфиг и токен --------------------

def load_config() -> dict:
    cfg = dict(CONFIG)
    cfg["server_url"] = cfg["server_url"].rstrip("/")
    return cfg


def load_token() -> Optional[str]:
    if not TOKEN_PATH.exists():
        return None
    t = TOKEN_PATH.read_text(encoding="utf-8").strip()
    return t or None


def save_token(token: str) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token, encoding="utf-8")


# -------------------- HTTP --------------------

class Client:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base = cfg["server_url"]
        self.timeout = cfg["request_timeout_sec"]
        self.token: Optional[str] = load_token()
        self.session = requests.Session()

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def register(self) -> str:
        body = {"mac": get_mac(), "hostname": get_hostname(), "ip": get_local_ip()}
        r = self.session.post(
            f"{self.base}/api/agent/register", json=body, timeout=self.timeout
        )
        r.raise_for_status()
        data = r.json()
        self.token = data["token"]
        save_token(self.token)
        log.info("registered: device_id=%s", data.get("device_id"))
        return self.token

    def ensure_token(self) -> None:
        if not self.token:
            self.register()

    def poll(self) -> Optional[dict]:
        self.ensure_token()
        r = self.session.get(
            f"{self.base}/api/agent/command",
            headers=self._auth_headers(),
            timeout=self.timeout,
        )
        if r.status_code == 204:
            return None
        if r.status_code == 401:
            log.warning("401 при поллинге, перерегистрация")
            self.register()
            return None
        r.raise_for_status()
        return r.json()

    def download_command_file(self, file_url: str) -> tuple[bytes, str]:
        r = self.session.get(
            f"{self.base}{file_url}",
            headers=self._auth_headers(),
            timeout=self.timeout,
        )
        r.raise_for_status()
        filename = _parse_filename(r.headers.get("Content-Disposition", "")) or "input.bin"
        return r.content, filename

    def post_result(
        self,
        command_id: int,
        status: str,
        output: str,
        file_bytes: Optional[bytes] = None,
        file_name: Optional[str] = None,
    ) -> None:
        data = {"command_id": str(command_id), "status": status, "output": output or ""}
        files = None
        if file_bytes is not None:
            files = {"file": (file_name or "result.bin", file_bytes, "application/octet-stream")}
        r = self.session.post(
            f"{self.base}/api/agent/result",
            headers=self._auth_headers(),
            data=data,
            files=files,
            timeout=self.timeout,
        )
        if r.status_code == 401:
            self.register()
            r = self.session.post(
                f"{self.base}/api/agent/result",
                headers=self._auth_headers(),
                data=data,
                files=files,
                timeout=self.timeout,
            )
        r.raise_for_status()


def _parse_filename(content_disposition: str) -> Optional[str]:
    if not content_disposition:
        return None
    m = re.search(r'filename\*=UTF-8\'\'([^;]+)', content_disposition)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', content_disposition)
    if m:
        return m.group(1).strip()
    return None


# -------------------- обработчики команд --------------------

def _console_encoding() -> str:
    """Кодировка stdout/stderr дочерних процессов.

    На Windows cmd.exe и большинство консольных утилит пишут в OEM codepage
    (для русской локали — cp866). locale.getpreferredencoding возвращает
    ANSI (cp1251) — она однобайтная и «успешно» декодирует любые байты,
    превращая cp866-вывод в мусор. Поэтому на Windows спрашиваем OEM CP
    через WinAPI.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            cp = ctypes.windll.kernel32.GetOEMCP()
            if cp:
                return f"cp{cp}"
        except Exception:
            pass
        return "cp866"
    return locale.getpreferredencoding(False) or "utf-8"


def _decode(b: bytes) -> str:
    if not b:
        return ""
    return b.decode(_console_encoding(), errors="replace")


def handle_exec(cmd: dict, client: Client) -> dict:
    payload = cmd.get("payload") or ""
    if not payload.strip():
        return {"status": "error", "output": "пустой payload для exec"}
    timeout = client.cfg["exec_timeout_sec"]
    try:
        proc = subprocess.run(
            payload,
            shell=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "status": "error",
            "output": f"timeout после {timeout}s\n{_decode(e.stdout or b'')}\n{_decode(e.stderr or b'')}",
        }
    out = _decode(proc.stdout) + (_decode(proc.stderr) if proc.stderr else "")
    out += f"\n[exit code: {proc.returncode}]"
    return {
        "status": "done" if proc.returncode == 0 else "error",
        "output": out,
    }


def _zip_dir(root: Path) -> tuple[bytes, int, int, list[str]]:
    """Запаковать директорию в zip в памяти.

    Возвращает (bytes, n_files, n_skipped, list_of_skip_reasons).
    Структура внутри архива относительно `root.parent`, т.е. сама папка
    становится корнем — `root.name/...`.
    """
    buf = io.BytesIO()
    n_files = 0
    skipped: list[str] = []
    base = root.parent
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                full = Path(dirpath) / fn
                arcname = full.relative_to(base).as_posix()
                try:
                    zf.write(full, arcname)
                    n_files += 1
                except OSError as e:
                    skipped.append(f"{full}: {e}")
    return buf.getvalue(), n_files, len(skipped), skipped


def handle_get(cmd: dict, client: Client) -> dict:
    """Отдать файл или директорию с клиента на сервер.

    Директория упаковывается в zip в памяти, имя архива — `<dirname>.zip`.
    """
    path = (cmd.get("payload") or "").strip()
    if not path:
        return {"status": "error", "output": "payload должен быть путём к файлу или директории"}
    p = Path(path).expanduser()
    if not p.exists():
        return {"status": "error", "output": f"путь не найден: {p}"}

    if p.is_dir():
        try:
            data, n_files, n_skipped, skipped = _zip_dir(p)
        except OSError as e:
            return {"status": "error", "output": f"ошибка архивирования: {e}"}
        out = f"архив {p} → {p.name}.zip ({len(data)} bytes, {n_files} файлов)"
        if n_skipped:
            out += f"\nпропущено {n_skipped}:\n" + "\n".join(skipped[:20])
            if n_skipped > 20:
                out += f"\n... ещё {n_skipped - 20}"
        return {
            "status": "done",
            "output": out,
            "file_bytes": data,
            "file_name": f"{p.name}.zip",
        }

    if not p.is_file():
        return {"status": "error", "output": f"не файл и не директория: {p}"}
    try:
        data = p.read_bytes()
    except OSError as e:
        return {"status": "error", "output": f"ошибка чтения: {e}"}
    return {
        "status": "done",
        "output": f"отправлен {p} ({len(data)} bytes)",
        "file_bytes": data,
        "file_name": p.name,
    }


def handle_post(cmd: dict, client: Client) -> dict:
    """Принять файл с сервера и сохранить на клиент."""
    if not cmd.get("has_file") or not cmd.get("file_url"):
        return {"status": "error", "output": "у команды нет прикреплённого файла"}
    try:
        data, original_name = client.download_command_file(cmd["file_url"])
    except requests.RequestException as e:
        return {"status": "error", "output": f"скачивание провалилось: {e}"}

    dest_raw = (cmd.get("payload") or "").strip()
    if not dest_raw:
        dest = BASE_DIR / original_name
    else:
        dest = Path(dest_raw).expanduser()
        if dest.is_dir() or dest_raw.endswith(("/", "\\")):
            dest = dest / original_name

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    except OSError as e:
        return {"status": "error", "output": f"ошибка записи: {e}"}
    return {"status": "done", "output": f"сохранено в {dest} ({len(data)} bytes)"}


def handle_screenshot(cmd: dict, client: Client) -> dict:
    try:
        import mss
        import mss.tools
    except ImportError:
        return {"status": "error", "output": "mss не установлен (pip install mss)"}
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # все мониторы как один прямоугольник
            shot = sct.grab(monitor)
            png = mss.tools.to_png(shot.rgb, shot.size)
    except Exception as e:
        return {"status": "error", "output": f"screenshot failed: {e}"}
    return {
        "status": "done",
        "output": f"screenshot {shot.size[0]}x{shot.size[1]}",
        "file_bytes": png,
        "file_name": "screenshot.png",
    }


def handle_photo(cmd: dict, client: Client) -> dict:
    """Снимок с веб-камеры (первый доступный индекс)."""
    try:
        import cv2
    except ImportError:
        return {"status": "error", "output": "opencv-python не установлен (pip install opencv-python)"}

    index = 0
    payload = (cmd.get("payload") or "").strip()
    if payload:
        try:
            index = int(payload)
        except ValueError:
            return {"status": "error", "output": f"payload должен быть индексом камеры (int), а не {payload!r}"}

    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        return {"status": "error", "output": f"камера {index} недоступна"}
    try:
        frame = None
        for _ in range(5):  # прогрев — первые кадры часто чёрные
            ok, frame = cap.read()
            if not ok:
                frame = None
        if frame is None:
            return {"status": "error", "output": "не удалось прочитать кадр"}
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            return {"status": "error", "output": "не удалось закодировать PNG"}
        png = buf.tobytes()
        h, w = frame.shape[:2]
    finally:
        cap.release()

    return {
        "status": "done",
        "output": f"photo {w}x{h} cam={index}",
        "file_bytes": png,
        "file_name": "photo.png",
    }


def handle_input(cmd: dict, client: Client) -> dict:
    """Эмуляция мыши/клавиатуры через pyautogui.

    payload — список действий, по одному на строку. Пустые строки и строки,
    начинающиеся с '#', игнорируются. Поддерживаемые действия:

      move    x y [duration]              — переместить курсор (абсолютно)
      moverel dx dy [duration]            — переместить относительно
      click   [x y] [button] [clicks]     — клик (button=left|right|middle)
      doubleclick [x y]
      rightclick  [x y]
      mousedown   [x y] [button]
      mouseup     [x y] [button]
      drag    dx dy [duration] [button]   — drag относительно
      dragto  x y  [duration] [button]
      scroll  amount [x y]                — + вверх / - вниз
      hscroll amount [x y]
      press   key [count]                 — нажать клавишу N раз
      keydown key
      keyup   key
      hotkey  k1 k2 ...                   — комбинация
      type    <текст до конца строки>     — pyautogui.write (только ASCII)
      write   <текст до конца строки>     — алиас type
      sleep   секунды

    Имена клавиш — как у pyautogui (enter, esc, f1, ctrl, shift, win, ...).
    Кириллицу type не печатает (ограничение pyautogui.write); для не-ASCII
    используйте hotkey + paste через буфер обмена на стороне отдельно.
    Failsafe pyautogui включён: курсор в (0,0) прервёт команду.
    """
    payload = cmd.get("payload") or ""
    if not payload.strip():
        return {"status": "error", "output": "пустой payload для input"}

    try:
        import pyautogui
    except ImportError:
        return {"status": "error", "output": "pyautogui не установлен (pip install pyautogui)"}

    log_lines: list[str] = []

    def _num(s: str) -> float:
        return float(s)

    def _int(s: str) -> int:
        return int(s)

    actions = {
        "move":        lambda a: pyautogui.moveTo(_num(a[0]), _num(a[1]), duration=_num(a[2]) if len(a) > 2 else 0),
        "moveto":      lambda a: pyautogui.moveTo(_num(a[0]), _num(a[1]), duration=_num(a[2]) if len(a) > 2 else 0),
        "moverel":     lambda a: pyautogui.moveRel(_num(a[0]), _num(a[1]), duration=_num(a[2]) if len(a) > 2 else 0),
        "doubleclick": lambda a: pyautogui.doubleClick(*( (_num(a[0]), _num(a[1])) if len(a) >= 2 else () )),
        "rightclick":  lambda a: pyautogui.rightClick(*( (_num(a[0]), _num(a[1])) if len(a) >= 2 else () )),
        "scroll":      lambda a: pyautogui.scroll(_int(a[0]), *( (_num(a[1]), _num(a[2])) if len(a) >= 3 else () )),
        "hscroll":     lambda a: pyautogui.hscroll(_int(a[0]), *( (_num(a[1]), _num(a[2])) if len(a) >= 3 else () )),
        "keydown":     lambda a: pyautogui.keyDown(a[0]),
        "keyup":       lambda a: pyautogui.keyUp(a[0]),
        "hotkey":      lambda a: pyautogui.hotkey(*a),
        "sleep":       lambda a: time.sleep(_num(a[0])),
    }

    def do_click(args: list[str], fn) -> None:
        # [x y] [button] [clicks]
        x = y = None
        button = "left"
        clicks = 1
        rest = list(args)
        if len(rest) >= 2:
            try:
                x, y = _num(rest[0]), _num(rest[1])
                rest = rest[2:]
            except ValueError:
                pass
        if rest and rest[0] in ("left", "right", "middle", "primary", "secondary"):
            button = rest[0]
            rest = rest[1:]
        if rest:
            clicks = _int(rest[0])
        kwargs = {"button": button, "clicks": clicks}
        if x is not None:
            kwargs["x"], kwargs["y"] = x, y
        fn(**kwargs)

    def do_mousebtn(args: list[str], fn) -> None:
        x = y = None
        button = "left"
        rest = list(args)
        if len(rest) >= 2:
            try:
                x, y = _num(rest[0]), _num(rest[1])
                rest = rest[2:]
            except ValueError:
                pass
        if rest and rest[0] in ("left", "right", "middle"):
            button = rest[0]
        kwargs = {"button": button}
        if x is not None:
            kwargs["x"], kwargs["y"] = x, y
        fn(**kwargs)

    def do_drag(args: list[str], rel: bool) -> None:
        # x y [duration] [button]
        if len(args) < 2:
            raise ValueError("drag требует x y")
        x, y = _num(args[0]), _num(args[1])
        duration = 0.0
        button = "left"
        rest = args[2:]
        if rest:
            try:
                duration = _num(rest[0])
                rest = rest[1:]
            except ValueError:
                pass
        if rest and rest[0] in ("left", "right", "middle"):
            button = rest[0]
        if rel:
            pyautogui.dragRel(x, y, duration=duration, button=button)
        else:
            pyautogui.dragTo(x, y, duration=duration, button=button)

    def do_press(args: list[str]) -> None:
        if not args:
            raise ValueError("press требует имя клавиши")
        key = args[0]
        count = _int(args[1]) if len(args) > 1 else 1
        pyautogui.press(key, presses=count)

    for lineno, raw in enumerate(payload.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # type/write — остаток строки как сырой текст
        head, _, tail = line.partition(" ")
        head = head.lower()
        if head in ("type", "write"):
            try:
                pyautogui.write(tail)
                log_lines.append(f"{lineno}: {head} ({len(tail)} chars) ok")
            except Exception as e:
                return {"status": "error", "output": "\n".join(log_lines + [f"{lineno}: {head}: {e}"])}
            continue

        parts = line.split()
        verb = parts[0].lower()
        args = parts[1:]
        try:
            if verb == "click":
                do_click(args, pyautogui.click)
            elif verb == "mousedown":
                do_mousebtn(args, pyautogui.mouseDown)
            elif verb == "mouseup":
                do_mousebtn(args, pyautogui.mouseUp)
            elif verb == "drag":
                do_drag(args, rel=True)
            elif verb == "dragto":
                do_drag(args, rel=False)
            elif verb == "press":
                do_press(args)
            elif verb in actions:
                actions[verb](args)
            else:
                return {"status": "error", "output": "\n".join(log_lines + [f"{lineno}: неизвестное действие {verb!r}"])}
            log_lines.append(f"{lineno}: {line} ok")
        except pyautogui.FailSafeException:
            return {"status": "error", "output": "\n".join(log_lines + [f"{lineno}: failsafe (курсор в углу) — прервано"])}
        except Exception as e:
            return {"status": "error", "output": "\n".join(log_lines + [f"{lineno}: {line}: {e}"])}

    x, y = pyautogui.position()
    log_lines.append(f"done, cursor=({x},{y})")
    return {"status": "done", "output": "\n".join(log_lines)}


HANDLERS = {
    "exec": handle_exec,
    "get": handle_get,
    "post": handle_post,
    "screenshot": handle_screenshot,
    "photo": handle_photo,
    "input": handle_input,
}


def dispatch(cmd: dict, client: Client) -> dict:
    name = cmd.get("name") or ""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"status": "error", "output": f"неизвестная команда: {name}"}
    try:
        return handler(cmd, client)
    except Exception:
        return {"status": "error", "output": traceback.format_exc()}


# -------------------- основной цикл --------------------

def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    client = Client(cfg)
    client.ensure_token()
    log.info("agent started, server=%s host=%s mac=%s",
             cfg["server_url"], get_hostname(), get_mac())

    interval = cfg["poll_interval_sec"]
    while True:
        try:
            cmd = client.poll()
        except requests.RequestException as e:
            log.warning("poll failed: %s", e)
            time.sleep(interval)
            continue

        if cmd is None:
            time.sleep(interval)
            continue

        log.info("got command id=%s name=%s", cmd.get("command_id"), cmd.get("name"))
        result = dispatch(cmd, client)
        try:
            client.post_result(
                command_id=cmd["command_id"],
                status=result["status"],
                output=result.get("output", ""),
                file_bytes=result.get("file_bytes"),
                file_name=result.get("file_name"),
            )
            log.info("result sent: id=%s status=%s", cmd["command_id"], result["status"])
        except requests.RequestException as e:
            log.error("post_result failed for id=%s: %s", cmd.get("command_id"), e)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
