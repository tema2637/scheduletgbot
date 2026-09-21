from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
import hashlib
import json
import logging
import sqlite3
import config
from storage import validate

logger=logging.getLogger(__name__)
UNAVAILABLE='⚠️ Расписание не загружено или временно недоступно. Это не означает, что пар нет. Попробуйте позже.'
class ScheduleUnavailable(RuntimeError): pass
class UnknownGroup(ValueError): pass

class DataManager:
    def __init__(self,schedule_path=None,db_path=None):
        self.schedule_path=Path(schedule_path) if schedule_path else config.SCHEDULE_PATH
        self.db_path=Path(db_path) if db_path else config.DB_PATH
        self.semester_start=config.SEMESTER_START
        self.week1_monday=config.WEEK1_MONDAY
        self.semester_end=config.SEMESTER_END
        self._schedule=[]; self._index={}; self._groups=[]
        self._signature=None; self._revision=''; self._error=None; self._max_week=0
        self._updated=None; self._lock=RLock()
    def now(self): return datetime.now(config.TZ)
    def local_date(self,value):
        if isinstance(value,datetime):
            return value.astimezone(config.TZ).date() if value.tzinfo else value.date()
        return value
    def get_academic_week(self,value):
        return (self.local_date(value)-self.week1_monday).days//7+1
    def _check_reload(self,force=False):
        with self._lock:
            try:
                stat=self.schedule_path.stat()
                signature=(stat.st_mtime_ns,stat.st_size)
                if not force and signature==self._signature:
                    if not self._schedule: raise ScheduleUnavailable(UNAVAILABLE)
                    return
                self._signature=signature
                if stat.st_size>20*1024*1024: raise ValueError('JSON превышает 20 МБ.')
                raw=self.schedule_path.read_bytes()
                if len(raw)>20*1024*1024: raise ValueError('JSON превышает 20 МБ.')
                records=validate(json.loads(raw.decode('utf-8-sig')))
                index=defaultdict(list)
                for r in records:
                    for w in r['Weeks']:
                        index[(r['Group']['Name'],r['TimeSlot']['DayOfWeek'],w)].append(r)
                self._schedule=records; self._index=dict(index)
                self._groups=sorted({r['Group']['Name'] for r in records})
                self._max_week=max(w for r in records for w in r['Weeks'])
                self._revision=hashlib.sha256(raw).hexdigest()[:16]
                self._updated=datetime.fromtimestamp(stat.st_mtime,config.TZ)
                self._error=None
            except ScheduleUnavailable: raise
            except (OSError,ValueError,TypeError,KeyError) as exc:
                if isinstance(exc,OSError): self._signature=None
                self._error=type(exc).__name__
                logger.warning('Расписание не обновлено: %s',type(exc).__name__)
                if not self._schedule: raise ScheduleUnavailable(UNAVAILABLE) from exc
    def get_groups(self):
        self._check_reload()
        with self._lock: return list(self._groups)
    def _from_current(self,group,value):
        target=self.local_date(value)
        if group not in self._groups: raise UnknownGroup('Группы больше нет в расписании. Выберите её заново.')
        end=self.semester_end or self.week1_monday+timedelta(weeks=self._max_week,days=-1)
        if target<self.semester_start or target>end: return None
        records=deepcopy(self._index.get((group,target.isoweekday(),self.get_academic_week(target)),[]))
        return sorted(records,key=lambda r:r['TimeSlot']['NumberSlot'])
    def get_schedule_for_day(self,group,value):
        self._check_reload()
        with self._lock: return self._from_current(group,value)
    def get_week_text(self,group,start):
        import ui_templates
        self._check_reload()
        with self._lock:
            text=ui_templates.format_week_schedule(start,self._from_current,group,self.get_academic_week(start))
            return text+self.status_note()
    def status_note(self):
        note=''
        if self._error:
            note+='\n\n⚠️ Показана последняя корректная версия: обновление не удалось. Уточните возможные изменения.'
        return note
    def _connect(self):
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(self.db_path,timeout=5)
        c.execute('CREATE TABLE IF NOT EXISTS user_preferences(user_id INTEGER PRIMARY KEY,group_name TEXT)')
        return c
    def get_user_group(self,user_id):
        c=self._connect()
        try:
            with c:
                row=c.execute('SELECT group_name FROM user_preferences WHERE user_id=?',(user_id,)).fetchone()
                return row[0] if row else None
        finally: c.close()
    def save_user_group(self,user_id,group):
        if group not in self.get_groups(): raise UnknownGroup('Группа не найдена.')
        c=self._connect()
        try:
            with c: c.execute('INSERT INTO user_preferences(user_id,group_name) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET group_name=excluded.group_name',(user_id,group))
        finally: c.close()

data_manager=DataManager()
