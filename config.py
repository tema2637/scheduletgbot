from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import re
from dotenv import dotenv_values

BASE_DIR=Path(__file__).resolve().parent
ENV={**dotenv_values(BASE_DIR/'.env'),**os.environ}
BOT_TOKEN=(ENV.get('BOT_TOKEN') or '').strip()
PROXY=(ENV.get('PROXY') or '').strip()
CHANNEL=(ENV.get('CHANNEL') or '').strip()
FOOTER_TEXT=(ENV.get('FOOTER_TEXT') or 'Лучший VPN — EtherVPN').strip()
FOOTER_URL=(ENV.get('FOOTER_URL') or 'https://t.me/ethervpnbot?start=partner_268964754').strip()
CHANNEL_URL=(ENV.get('CHANNEL_URL') or '').strip()

def _env_bool(name,default):
    value=ENV.get(name)
    if value is None or str(value).strip()=='':
        return default
    return str(value).strip().lower() in ('1','true','yes','on','да')

def _env_int(name,default,minimum=0):
    try:
        value=int(str(ENV.get(name) or '').strip())
    except ValueError:
        return default
    return max(minimum,value)

REQUIRE_SUBSCRIPTION=_env_bool('REQUIRE_SUBSCRIPTION',True)
SUBSCRIPTION_FAIL_OPEN=_env_bool('SUBSCRIPTION_FAIL_OPEN',True)
SUBSCRIPTION_CACHE_TTL=_env_int('SUBSCRIPTION_CACHE_TTL',300)
SUBSCRIPTION_NEGATIVE_TTL=_env_int('SUBSCRIPTION_NEGATIVE_TTL',30)
LOG_MAX_BYTES=_env_int('LOG_MAX_BYTES',5*1024*1024,1024)
LOG_BACKUP_COUNT=_env_int('LOG_BACKUP_COUNT',5,0)

def redact(text):
    if BOT_TOKEN:
        text=text.replace(BOT_TOKEN,'[TOKEN]')
    if PROXY:
        text=text.replace(PROXY,'[PROXY]')
    return re.sub(r'(://[^:/\s]+:)[^@\s]+@',r'\1[REDACTED]@',text)

TZ=ZoneInfo(ENV.get('TIMEZONE') or 'Europe/Moscow')
SEMESTER_START=date.fromisoformat(ENV.get('SEMESTER_START') or '2026-09-01')
WEEK1_MONDAY=date.fromisoformat(ENV.get('WEEK1_MONDAY') or (SEMESTER_START-timedelta(days=SEMESTER_START.weekday())).isoformat())
SEMESTER_END=date.fromisoformat(ENV['SEMESTER_END']) if ENV.get('SEMESTER_END') else None
if WEEK1_MONDAY.weekday()!=0:
    raise ValueError('WEEK1_MONDAY должен быть понедельником.')
if not 0 <= (SEMESTER_START-WEEK1_MONDAY).days <= 6:
    raise ValueError('SEMESTER_START должен попадать в первую учебную неделю.')
if SEMESTER_END is not None and SEMESTER_END<SEMESTER_START:
    raise ValueError('SEMESTER_END раньше начала семестра.')
def project_path(key,default):
    path=Path(ENV.get(key) or default).expanduser()
    return path.resolve() if path.is_absolute() else (BASE_DIR/path).resolve()
SCHEDULE_PATH=project_path('SCHEDULE_PATH','data/schedule.json')
DB_PATH=project_path('DB_PATH','data/users.db')
if SCHEDULE_PATH==DB_PATH:
    raise ValueError('Пути расписания и базы пользователей должны различаться.')
