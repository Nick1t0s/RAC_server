"""RAC loader.

Копирует agent.exe в C:\\rac_windows\\ (туда же, где agent хранит токен),
прописывает его в автостарт текущего пользователя (HKCU\\...\\Run),
запускает и показывает Windows toast-уведомление, после чего завершается.

Предполагается запуск как скомпилированный pyinstaller'ом loader.exe,
рядом с которым лежит agent.exe.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "RAC"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

INSTALL_DIR = Path(r"C:\rac_windows")
INSTALL_PATH = INSTALL_DIR / "agent.exe"

SRC_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent
SRC_PATH = SRC_DIR / "agent.exe"


def install_agent() -> None:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    if SRC_PATH.resolve() != INSTALL_PATH.resolve():
        shutil.copy2(SRC_PATH, INSTALL_PATH)


def add_to_autostart(command: str) -> None:
    import winreg
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)


def launch_agent(agent: Path) -> None:
    subprocess.Popen(
        [str(agent)],
        cwd=str(agent.parent),
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def show_toast(title: str, message: str) -> None:
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, "
        "Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n=$t.GetElementsByTagName('text');"
        f"$n.Item(0).AppendChild($t.CreateTextNode('{title}')) | Out-Null;"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{message}')) | Out-Null;"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($t);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_NAME}').Show($toast);"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
        except Exception:
            pass


def main() -> int:
    if not SRC_PATH.exists():
        return 1
    install_agent()
    add_to_autostart(f'"{INSTALL_PATH}"')
    launch_agent(INSTALL_PATH)
    show_toast(APP_NAME, "RAC установлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
