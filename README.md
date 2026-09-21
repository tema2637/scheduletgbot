# Опять пары

Telegram-бот с расписанием учебных групп. Показывает занятия на сегодня, завтра, текущую и следующую неделю; поддерживает inline-режим и необязательную проверку подписки на канал.

## Требования

- Python 3.10 или новее;
- токен Telegram-бота от [@BotFather](https://t.me/BotFather);
- для проверки подписки — публичный канал, где бот добавлен администратором.

## Установка

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

На Windows:

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

Откройте `.env` и заполните `BOT_TOKEN`. Если проверка подписки не нужна, оставьте `CHANNEL` пустым.

Перед запуском проверьте конфигурацию и расписание:

```bash
python main.py --check
```

Запуск:

```bash
python main.py
```

На Linux можно использовать `./start_bot.sh`, на Windows — `start_bot.bat`.

## Настройки

| Переменная | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `BOT_TOKEN` | токен Telegram-бота | обязательна для запуска |
| `CHANNEL` | имя публичного канала без `https://t.me/` | проверка отключена |
| `PROXY` | прокси для Telegram API | не используется |
| `FOOTER_TEXT` | необязательная подпись под расписанием | пусто |
| `FOOTER_URL` | ссылка для подписи | пусто |
| `TIMEZONE` | часовой пояс | `Europe/Moscow` |
| `SEMESTER_START` | первый календарный день семестра | `2026-09-01` |
| `WEEK1_MONDAY` | понедельник первой учебной недели | `2026-08-31` |
| `SEMESTER_END` | последний день семестра | определяется по JSON |
| `SCHEDULE_PATH` | путь к расписанию | `data/schedule.json` |
| `DB_PATH` | путь к SQLite с настройками пользователей | `data/users.db` |

## Обновление расписания

Исходная таблица находится в `imports/Расписание-2.xlsx`. Сначала выполните проверку без изменения рабочего JSON:

```bash
python schedule_parser.py "imports/Расписание-2.xlsx" --check
```

Если ошибок нет, опубликуйте расписание:

```bash
python schedule_parser.py "imports/Расписание-2.xlsx"
```

Парсер пишет отчёт в `data/last_import_report.json` и не заменяет рабочий JSON при ошибках. Время звонков задаётся в `TIME_SLOTS` внутри `schedule_parser.py`.

## Inline-режим

Включите inline-режим командой `/setinline` в [@BotFather](https://t.me/BotFather). После этого доступны запросы:

```text
@имя_бота сегодня
@имя_бота завтра
@имя_бота неделя
@имя_бота следующая неделя
```

## Данные

- `data/schedule.json` — расписание, его можно хранить в Git;
- `data/users.db` — пользовательские настройки, создаются при запуске и не коммитятся;
- `bot.log` — журнал работы, не коммитится;
- `.env` — токен и локальные настройки, не коммитится.

Перед обновлением на сервере сохраните резервную копию `data/users.db`.

## Проверки

```bash
python -m unittest discover -s tests -v
python main.py --check
```

CI запускает те же проверки для Python 3.10 и 3.12.

## Структура

```text
.
├── data/schedule.json          # рабочее расписание
├── imports/Расписание-2.xlsx   # исходная таблица
├── tests/                      # тесты без обращения к Telegram
├── main.py                     # запуск бота
├── schedule_parser.py          # импорт CSV/XLSX
├── config.py                   # чтение .env
└── .env.example                # пример конфигурации
```
