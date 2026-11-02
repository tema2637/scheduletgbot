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
| `CHANNEL` | `@username` или числовой ID канала | проверка отключена |
| `CHANNEL_URL` | ссылка на канал, если нет username | пусто |
| `REQUIRE_SUBSCRIPTION` | включить проверку подписки | `true` |
| `SUBSCRIPTION_CACHE_TTL` | кэш положительной проверки, сек | `300` |
| `SUBSCRIPTION_NEGATIVE_TTL` | кэш отрицательной проверки, сек | `30` |
| `SUBSCRIPTION_FAIL_OPEN` | пускать при сетевой ошибке проверки | `true` |
| `PROXY` | прокси для Telegram API | не используется |
| `FOOTER_TEXT` | необязательная подпись под расписанием | пусто |
| `FOOTER_URL` | ссылка для подписи | пусто |
| `TIMEZONE` | часовой пояс | `Europe/Moscow` |
| `SEMESTER_START` | первый календарный день семестра | `2026-09-01` |
| `WEEK1_MONDAY` | понедельник первой учебной недели | `2026-08-31` |
| `SEMESTER_END` | последний день семестра | определяется по JSON |
| `SCHEDULE_PATH` | путь к расписанию | `data/schedule.json` |
| `DB_PATH` | путь к SQLite с настройками пользователей | `data/users.db` |
| `LOG_MAX_BYTES` | размер файла журнала до ротации | `5242880` |
| `LOG_BACKUP_COUNT` | число архивных копий журнала | `5` |

## Обновление расписания

Исходная таблица находится в `imports/Расписание-2.xlsx`. Сначала выполните проверку без изменения рабочего JSON:

```bash
python schedule_parser.py "imports/Расписание-2.xlsx" --check
```

Если ошибок нет, опубликуйте расписание:

```bash
python schedule_parser.py "imports/Расписание-2.xlsx"
```

При публикации парсер пишет отчёт в `data/last_import_report.json`; `--check` не меняет ни расписание, ни отчёт. Время звонков задаётся в `times.py`; `storage.validate` сверяет с ним каждый слот, поэтому ручная правка времени в JSON не пройдёт проверку.

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

## Тестовый экземпляр

Для проверки новой версии рядом с рабочим ботом используйте отдельную папку и отдельного бота:

```bash
cp -a /config/schedule_bot /config/schedule_bot_test
cd /config/schedule_bot_test
# в .env: новый BOT_TOKEN, CHANNEL="", REQUIRE_SUBSCRIPTION=false,
# DB_PATH=data/users_test.db, SCHEDULE_PATH=data/schedule.json
LOCK_FILE=.bot.lock PYTHON=/config/venv/bin/python ./start_bot.sh
```

Не запускайте два процесса с одним и тем же `BOT_TOKEN`: Telegram вернёт конфликт polling. `start_bot.sh` использует `flock`, чтобы второй экземпляр в той же папке не стартовал.

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
├── times.py                    # единый источник времени звонков
├── config.py                   # чтение .env
└── .env.example                # пример конфигурации
```
