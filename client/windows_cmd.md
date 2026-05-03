# Команды Windows (`cmd.exe`)

Справочник для отправки через `exec` агента. На русской локали вывод
`cmd.exe` декодируется в cp866 — если что-то ломается, попробуйте
запустить через `cmd /u /c <команда>` (UTF-16) и перекодировать.

Большинство команд поддерживают `/?` — `exec ipconfig /?`.

---

## Файловая система

| Команда | Назначение | Пример |
|---|---|---|
| `dir` | список файлов и папок | `exec dir C:\Windows` |
| `cd` | сменить каталог (в одной строке) | `exec cd C:\ && dir` |
| `type` | вывести содержимое файла | `exec type C:\boot.ini` |
| `more` | постраничный вывод | `exec more C:\file.log` |
| `copy` | копировать файл | `exec copy a.txt b.txt` |
| `xcopy` | копировать с подкаталогами | `exec xcopy src dst /E /I /Y` |
| `robocopy` | надёжное копирование, зеркалирование | `exec robocopy src dst /MIR` |
| `move` | переместить/переименовать | `exec move old.txt new.txt` |
| `ren` | переименовать | `exec ren a.txt b.txt` |
| `del` / `erase` | удалить файлы | `exec del /F /Q C:\tmp\*.log` |
| `mkdir` / `md` | создать каталог | `exec mkdir C:\tmp\new` |
| `rmdir` / `rd` | удалить каталог | `exec rmdir /S /Q C:\tmp\old` |
| `attrib` | показать/изменить атрибуты | `exec attrib +H secret.txt` |
| `tree` | дерево каталогов | `exec tree C:\Users /F` |
| `where` | найти исполняемый файл в PATH | `exec where python` |
| `fc` | сравнить файлы | `exec fc a.txt b.txt` |
| `comp` | побайтовое сравнение | `exec comp a.bin b.bin` |
| `findstr` | grep для Windows | `exec findstr /S /I "TODO" *.py` |
| `forfiles` | действия по фильтру | `exec forfiles /S /M *.tmp /C "cmd /c del @path"` |

---

## Сеть

| Команда | Назначение | Пример |
|---|---|---|
| `ipconfig` | конфигурация интерфейсов | `exec ipconfig /all` |
| `ipconfig /flushdns` | очистить DNS-кэш | `exec ipconfig /flushdns` |
| `ipconfig /release` `/renew` | сбросить/получить DHCP | `exec ipconfig /renew` |
| `ping` | проверка доступности | `exec ping -n 4 8.8.8.8` |
| `tracert` | трассировка маршрута | `exec tracert google.com` |
| `pathping` | tracert + потери | `exec pathping 8.8.8.8` |
| `nslookup` | DNS-запрос | `exec nslookup example.com` |
| `netstat -ano` | соединения + PID | `exec netstat -ano` |
| `netstat -rn` | таблица маршрутизации | `exec netstat -rn` |
| `arp -a` | ARP-таблица | `exec arp -a` |
| `route print` | маршруты | `exec route print` |
| `getmac` | MAC-адреса | `exec getmac /v` |
| `net view` | соседи в сети | `exec net view` |
| `net use` | подключить/смотреть сетевые диски | `exec net use Z: \\srv\share` |
| `net share` | расшаренные ресурсы | `exec net share` |
| `nbtstat -n` | NetBIOS-имена | `exec nbtstat -n` |
| `telnet host port` | проверка TCP-порта | `exec telnet 1.2.3.4 80` |
| `curl` | HTTP-клиент (Win10+) | `exec curl -I https://ya.ru` |
| `powershell Invoke-WebRequest` | то же из PowerShell | `exec powershell -c "iwr https://ya.ru"` |

---

## Процессы и службы

| Команда | Назначение | Пример |
|---|---|---|
| `tasklist` | список процессов | `exec tasklist /V` |
| `tasklist /FI` | фильтр | `exec tasklist /FI "IMAGENAME eq chrome.exe"` |
| `taskkill /PID` | убить по PID | `exec taskkill /PID 1234 /F` |
| `taskkill /IM` | убить по имени | `exec taskkill /IM notepad.exe /F` |
| `start` | запустить программу | `exec start notepad` |
| `wmic process` | расширенный список (deprec.) | `exec wmic process get Name,ProcessId,CommandLine` |
| `sc query` | список служб | `exec sc query` |
| `sc start` `stop` | управлять службой | `exec sc start spooler` |
| `sc config` | автозапуск | `exec sc config spooler start= auto` |
| `net start` `stop` | то же, проще | `exec net start spooler` |
| `schtasks /query` | планировщик | `exec schtasks /query /FO LIST` |
| `schtasks /create` | создать задачу | `exec schtasks /create /SC ONLOGON /TN MyTask /TR app.exe` |

---

## Система и пользователи

| Команда | Назначение | Пример |
|---|---|---|
| `whoami` | текущий пользователь | `exec whoami /all` |
| `hostname` | имя машины | `exec hostname` |
| `systeminfo` | сводка по ОС/железу | `exec systeminfo` |
| `ver` | версия Windows | `exec ver` |
| `set` | переменные окружения | `exec set` |
| `setx` | задать env постоянно | `exec setx FOO bar` |
| `net user` | список/инфо о юзерах | `exec net user` |
| `net user <имя>` | детали | `exec net user Администратор` |
| `net localgroup` | локальные группы | `exec net localgroup Администраторы` |
| `query user` | сессии | `exec query user` |
| `logoff <id>` | завершить сессию | `exec logoff 2` |
| `shutdown /s /t 60` | выключение через 60 с | `exec shutdown /s /t 60` |
| `shutdown /r /t 0` | перезагрузка сейчас | `exec shutdown /r /t 0` |
| `shutdown /a` | отменить | `exec shutdown /a` |
| `shutdown /l` | logout | `exec shutdown /l` |
| `date /t`, `time /t` | дата/время | `exec date /t` |
| `chcp` | кодовая страница | `exec chcp 65001` |
| `gpresult /R` | применённые GPO | `exec gpresult /R` |
| `gpupdate /force` | обновить GPO | `exec gpupdate /force` |

---

## Диски и тома

| Команда | Назначение | Пример |
|---|---|---|
| `vol` | метка тома | `exec vol C:` |
| `label` | задать метку | `exec label C: SYSTEM` |
| `chkdsk` | проверка диска | `exec chkdsk C: /F` |
| `diskpart` | управление дисками (интеракт.) | `exec diskpart /s script.txt` |
| `defrag` | дефрагментация | `exec defrag C: /A` |
| `format` | форматирование | `exec format E: /FS:NTFS /Q` |
| `fsutil volume diskfree` | свободно на томе | `exec fsutil volume diskfree C:` |
| `mountvol` | точки монтирования | `exec mountvol` |
| `wmic logicaldisk` | список дисков | `exec wmic logicaldisk get Name,Size,FreeSpace` |

---

## Реестр и WMI

| Команда | Назначение | Пример |
|---|---|---|
| `reg query` | прочитать ключ | `exec reg query "HKLM\Software\Microsoft\Windows NT\CurrentVersion" /v ProductName` |
| `reg add` | добавить значение | `exec reg add HKCU\Test /v Foo /t REG_SZ /d bar /f` |
| `reg delete` | удалить ключ/значение | `exec reg delete HKCU\Test /f` |
| `reg export` / `import` | бэкап / восстановление | `exec reg export HKCU\Test test.reg` |
| `wmic os get` | свойства ОС | `exec wmic os get Caption,Version,OSArchitecture` |
| `wmic cpu get` | CPU | `exec wmic cpu get Name,NumberOfCores` |
| `wmic memorychip get` | RAM | `exec wmic memorychip get Capacity,Speed` |
| `wmic bios get` | BIOS | `exec wmic bios get SerialNumber,Manufacturer` |
| `wmic product get` | установленный софт | `exec wmic product get Name,Version` |
| `powershell Get-CimInstance` | замена WMIC | `exec powershell -c "Get-CimInstance Win32_OperatingSystem | fl"` |

---

## Безопасность и брандмауэр

| Команда | Назначение | Пример |
|---|---|---|
| `netsh advfirewall show allprofiles` | статус брандмауэра | `exec netsh advfirewall show allprofiles` |
| `netsh advfirewall firewall add rule` | добавить правило | `exec netsh advfirewall firewall add rule name="Allow80" dir=in action=allow protocol=TCP localport=80` |
| `netsh advfirewall firewall delete rule` | удалить | `exec netsh advfirewall firewall delete rule name="Allow80"` |
| `netsh wlan show profiles` | сохранённые Wi-Fi | `exec netsh wlan show profiles` |
| `netsh wlan show profile name="X" key=clear` | пароль Wi-Fi | `exec netsh wlan show profile name="MySSID" key=clear` |
| `cipher /w:` | затереть свободное место | `exec cipher /w:C:\` |
| `icacls` | NTFS-права | `exec icacls C:\tmp /grant User:F` |
| `takeown` | взять владение | `exec takeown /F C:\file /A` |

---

## Полезные комбо

```
exec ipconfig /flushdns && ipconfig /renew
exec netstat -ano | findstr :443
exec tasklist /FI "IMAGENAME eq chrome.exe" /FO CSV
exec wmic process where "name='chrome.exe'" get ProcessId,CommandLine
exec powershell -c "Get-Process | Sort-Object CPU -Desc | Select -First 10"
exec for /f "tokens=2" %i in ('tasklist ^| findstr notepad') do taskkill /PID %i /F
```

---

## Тонкости отправки через `exec`

- Каждая команда выполняется в **новом** `cmd.exe` — `cd` в одной команде
  не сохранится для следующей. Цепляйте через `&&` / `&`.
- Кавычки: одинарные не работают в `cmd`, только двойные (`"..."`).
  Внутри payload экранировать не нужно — строка идёт в шелл как есть.
- Перенаправление вывода (`>`, `>>`, `|`) поддерживается шеллом —
  работает прямо в `payload`.
- Долгие команды (>120 с по умолчанию) обрубаются по таймауту
  `exec_timeout_sec` из `client/config.json`.
- Для UTF-8 вывода: `exec chcp 65001 && <команда>` — но у агента всё равно
  декодер cp866, поэтому надёжнее перекодировать на стороне команды
  (`powershell -c "[Console]::OutputEncoding=[Text.Encoding]::UTF8; ..."`).
- Админ-права: агент работает с правами процесса, который его запустил.
  Команды вроде `sc config`, `netsh advfirewall`, `shutdown` без админа
  упадут с `Access denied`.
