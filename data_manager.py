from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
import hashlib
import json
import logging
import re
import sqlite3
import time
import config
from storage import validate

logger=logging.getLogger(__name__)
UNAVAILABLE='⚠️ Расписание не загружено или временно недоступно. Это не означает, что пар нет. Попробуйте позже.'
class ScheduleUnavailable(RuntimeError): pass
class UnknownGroup(ValueError): pass

def normalize_teacher_name(name):
    name = re.sub(r'\s+', ' ', (name or '').strip())
    m = re.match(r'^([А-ЯЁ][а-яё]+)\s+([А-ЯЁ])\.?\s*([А-ЯЁ])?\.?$', name)
    if m:
        sn, i1, i2 = m.groups()
        return f'{sn} {i1}.{i2}.' if i2 else f'{sn} {i1}.'
    return name

class DataManager:
    def __init__(self,schedule_path=None,db_path=None):
        self.schedule_path=Path(schedule_path) if schedule_path else config.SCHEDULE_PATH
        self.db_path=Path(db_path) if db_path else config.DB_PATH
        self.semester_start=config.SEMESTER_START
        self.week1_monday=config.WEEK1_MONDAY
        self.semester_end=config.SEMESTER_END
        self._schedule=[]; self._index={}; self._teacher_index={}; self._groups=[]; self._teachers=[]
        self._signature=None; self._last_bad_signature=None; self._retry_after=0.0
        self._revision=''; self._error=None; self._max_week=0
        self._updated=None; self._lock=RLock(); self._db_initialized=False
        self._teacher_resolver = normalize_teacher_name
    def now(self): return datetime.now(config.TZ)
    def local_date(self,value):
        if isinstance(value,datetime):
            return value.astimezone(config.TZ).date() if value.tzinfo else value.date()
        return value
    def get_academic_week(self,value):
        return (self.local_date(value)-self.week1_monday).days//7+1
    def _check_reload(self,force=False):
        with self._lock:
            now=time.monotonic()
            try:
                stat=self.schedule_path.stat()
                signature=(stat.st_mtime_ns,stat.st_size)
            except OSError as exc:
                self._error=type(exc).__name__
                logger.warning('Расписание не обновлено: %s',type(exc).__name__)
                if not self._schedule: raise ScheduleUnavailable(UNAVAILABLE) from exc
                return
            if not force and signature==self._signature:
                if not self._schedule: raise ScheduleUnavailable(UNAVAILABLE)
                return
            if not force and signature==self._last_bad_signature and now<self._retry_after:
                if not self._schedule: raise ScheduleUnavailable(UNAVAILABLE)
                return
            try:
                if stat.st_size>20*1024*1024: raise ValueError('JSON превышает 20 МБ.')
                raw=self.schedule_path.read_bytes()
                if len(raw)>20*1024*1024: raise ValueError('JSON превышает 20 МБ.')
                records=validate(json.loads(raw.decode('utf-8-sig')))
                index=defaultdict(list)
                t_index=defaultdict(list)
                raw_teachers={r.get('TeacherName') for r in records if r.get('TeacherName')}
                full_forms=defaultdict(set)
                for item in raw_teachers:
                    norm=normalize_teacher_name(item)
                    if ' ' in norm: full_forms[norm.split()[0]].add(norm)
                def resolve_t(val):
                    norm=normalize_teacher_name(val)
                    if ' ' in norm: return norm
                    if len(full_forms[norm])==1: return next(iter(full_forms[norm]))
                    return norm
                self._teacher_resolver=resolve_t

                for r in records:
                    t=r.get('TeacherName')
                    for w in r['Weeks']:
                        index[(r['Group']['Name'],r['TimeSlot']['DayOfWeek'],w)].append(r)
                        if t:
                            c_t=resolve_t(t)
                            t_index[(c_t,r['TimeSlot']['DayOfWeek'],w)].append(r)
                            if c_t!=t: t_index[(t,r['TimeSlot']['DayOfWeek'],w)].append(r)

                self._schedule=records
                self._index=dict(index)
                self._teacher_index=dict(t_index)
                self._groups=sorted({r['Group']['Name'] for r in records})
                self._teachers=sorted({resolve_t(t) for t in raw_teachers})
                self._max_week=max(w for r in records for w in r['Weeks'])
                self._revision=hashlib.sha256(raw).hexdigest()[:16]
                self._updated=datetime.fromtimestamp(stat.st_mtime,config.TZ)
                self._error=None
                self._signature=signature
                self._last_bad_signature=None
                self._retry_after=0.0
            except ScheduleUnavailable: raise
            except (OSError,ValueError,TypeError,KeyError) as exc:
                self._signature=None
                self._last_bad_signature=signature
                self._retry_after=now+5
                self._error=type(exc).__name__
                logger.warning('Расписание не обновлено: %s',type(exc).__name__)
                if not self._schedule: raise ScheduleUnavailable(UNAVAILABLE) from exc
    def get_groups(self):
        self._check_reload()
        with self._lock: return list(self._groups)
    def get_teachers(self):
        self._check_reload()
        with self._lock: return list(self._teachers)
    def find_teachers(self,query):
        self._check_reload()
        q=(query or '').strip().lower()
        if not q: return []
        with self._lock:
            exact=[t for t in self._teachers if t.lower()==q or t.lower().split()[0]==q]
            if exact: return exact
            return [t for t in self._teachers if q in t.lower()]
    def _from_current(self,group,value):
        target=self.local_date(value)
        if group not in self._groups: raise UnknownGroup('Группы больше нет в расписании. Выберите её заново.')
        end=self.semester_end or self.week1_monday+timedelta(weeks=self._max_week,days=-1)
        if target<self.semester_start or target>end: return None
        week=self.get_academic_week(target)
        if week<1 or week>self._max_week: return None
        records=self._index.get((group,target.isoweekday(),week),[])
        return sorted(records,key=lambda r:r['TimeSlot']['NumberSlot'])
    def _from_current_teacher(self,teacher,value):
        target=self.local_date(value)
        c_t=self._teacher_resolver(teacher) if hasattr(self,'_teacher_resolver') else teacher
        if c_t not in self._teachers and teacher not in self._teachers:
            raise UnknownGroup('Преподаватель не найден в расписании.')
        end=self.semester_end or self.week1_monday+timedelta(weeks=self._max_week,days=-1)
        if target<self.semester_start or target>end: return None
        week=self.get_academic_week(target)
        if week<1 or week>self._max_week: return None
        records=self._teacher_index.get((c_t,target.isoweekday(),week),[])
        return sorted(records,key=lambda r:r['TimeSlot']['NumberSlot'])
    def get_schedule_for_day(self,group,value):
        self._check_reload()
        with self._lock: return self._from_current(group,value)
    def get_teacher_schedule_for_day(self,teacher,value):
        self._check_reload()
        with self._lock: return self._from_current_teacher(teacher,value)
    def get_week_text(self,group,start):
        import ui_templates
        self._check_reload()
        with self._lock:
            text=ui_templates.format_week_schedule(start,self._from_current,group,self.get_academic_week(start))
            return text+self.status_note()
    def get_teacher_week_text(self,teacher,start):
        import ui_templates
        self._check_reload()
        with self._lock:
            text=ui_templates.format_teacher_week_schedule(start,self._from_current_teacher,teacher,self.get_academic_week(start))
            return text+self.status_note()
    def status_note(self):
        with self._lock:
            note=''
            if self._error:
                note+='\n\n⚠️ Показана последняя корректная версия: обновление не удалось. Уточните возможные изменения.'
            return note
    def check_and_reload(self):
        with self._lock:
            old_rev=self._revision
            old_records=self._schedule
            try: self._check_reload(force=False)
            except Exception: return False,set()
            if self._revision==old_rev or not old_records: return False,set()
            def sched_key(r):
                t=r['TimeSlot']
                return (r['LessonTitle'],r.get('TeacherName',''),r.get('Cabinet',''),t['DayOfWeek'],t['NumberSlot'],tuple(r['Weeks']))
            old_by=defaultdict(set)
            for r in old_records:
                old_by[r['Group']['Name']].add(sched_key(r))
                if r.get('TeacherName'):
                    old_by['teacher:'+self._teacher_resolver(r['TeacherName'])].add(sched_key(r))
            new_by=defaultdict(set)
            for r in self._schedule:
                new_by[r['Group']['Name']].add(sched_key(r))
                if r.get('TeacherName'):
                    new_by['teacher:'+self._teacher_resolver(r['TeacherName'])].add(sched_key(r))
            all_t=set(old_by.keys())|set(new_by.keys())
            return True,{t for t in all_t if old_by[t]!=new_by[t]}
    def _ensure_db(self):
        if self._db_initialized: return
        with self._lock:
            if self._db_initialized: return
            self.db_path.parent.mkdir(parents=True,exist_ok=True)
            c=sqlite3.connect(self.db_path,timeout=5)
            try:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE TABLE IF NOT EXISTS user_preferences(user_id INTEGER PRIMARY KEY,group_name TEXT,notify_evening INTEGER DEFAULT 0,notify_time TEXT DEFAULT NULL,last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
                try: c.execute('ALTER TABLE user_preferences ADD COLUMN notify_evening INTEGER DEFAULT 0')
                except sqlite3.OperationalError: pass
                try: c.execute('ALTER TABLE user_preferences ADD COLUMN notify_time TEXT DEFAULT NULL')
                except sqlite3.OperationalError: pass
                try: c.execute('ALTER TABLE user_preferences ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
                except sqlite3.OperationalError: pass
                c.commit()
            finally: c.close()
            self._db_initialized=True
    def _connect(self):
        self._ensure_db()
        c=sqlite3.connect(self.db_path,timeout=5)
        c.execute('PRAGMA busy_timeout=5000')
        return c
    def get_user_notify_time(self,user_id):
        c=self._connect()
        try:
            with c:
                row=c.execute('SELECT notify_time,notify_evening FROM user_preferences WHERE user_id=?',(user_id,)).fetchone()
                if not row: return None
                nt,ne=row
                if nt: return nt if nt!='off' else None
                if ne: return '20:00'
                return None
        finally: c.close()
    def set_user_notify_time(self,user_id,time_str):
        c=self._connect()
        val=time_str if time_str and time_str!='off' else None
        try:
            with c: c.execute('UPDATE user_preferences SET notify_time=?,notify_evening=? WHERE user_id=?',(val,1 if val else 0,user_id))
        finally: c.close()
    def get_user_notify(self,user_id):
        return bool(self.get_user_notify_time(user_id))
    def set_user_notify(self,user_id,enabled:bool):
        self.set_user_notify_time(user_id,'20:00' if enabled else None)
    def get_users_for_time(self,time_str):
        c=self._connect()
        try:
            with c:
                if time_str=='20:00':
                    return c.execute('SELECT user_id,group_name FROM user_preferences WHERE (notify_time="20:00" OR (notify_evening=1 AND (notify_time IS NULL OR notify_time="20:00"))) AND group_name IS NOT NULL').fetchall()
                return c.execute('SELECT user_id,group_name FROM user_preferences WHERE notify_time=? AND group_name IS NOT NULL',(time_str,)).fetchall()
        finally: c.close()
    def get_users_for_digest(self):
        c=self._connect()
        try:
            with c: return c.execute('SELECT user_id,group_name FROM user_preferences WHERE notify_evening=1 AND group_name IS NOT NULL').fetchall()
        finally: c.close()
    def get_users_by_target(self,target):
        c=self._connect()
        try:
            with c: return [r[0] for r in c.execute('SELECT user_id FROM user_preferences WHERE group_name=?',(target,)).fetchall()]
        finally: c.close()
    def touch_user(self,user_id):
        c=self._connect()
        try:
            with c: c.execute('UPDATE user_preferences SET last_active=CURRENT_TIMESTAMP WHERE user_id=?',(user_id,))
        finally: c.close()
    def get_stats(self):
        c=self._connect()
        try:
            with c:
                total_users=c.execute('SELECT count(*) FROM user_preferences WHERE user_id > 0').fetchone()[0]
                total_chats=c.execute('SELECT count(*) FROM user_preferences WHERE user_id < 0').fetchone()[0]
                active_24h=c.execute("SELECT count(*) FROM user_preferences WHERE last_active >= datetime('now', '-1 day')").fetchone()[0]
                active_7d=c.execute("SELECT count(*) FROM user_preferences WHERE last_active >= datetime('now', '-7 days')").fetchone()[0]
                with_reminders=c.execute('SELECT count(*) FROM user_preferences WHERE notify_time IS NOT NULL AND notify_time != "off"').fetchone()[0]
                teachers_users=c.execute("SELECT count(*) FROM user_preferences WHERE group_name LIKE 'teacher:%'").fetchone()[0]
                top_groups=c.execute(
                    "SELECT group_name, count(*) as cnt FROM user_preferences "
                    "WHERE group_name NOT LIKE 'teacher:%' AND group_name IS NOT NULL "
                    "GROUP BY group_name ORDER BY cnt DESC LIMIT 5"
                ).fetchall()
                return {
                    'total_users': total_users,
                    'total_chats': total_chats,
                    'active_24h': active_24h,
                    'active_7d': active_7d,
                    'with_reminders': with_reminders,
                    'teachers_users': teachers_users,
                    'top_groups': top_groups,
                }
        finally: c.close()
    def is_teacher_target(self,target):
        return bool(target and str(target).startswith('teacher:'))
    def target_name(self,target):
        return str(target).removeprefix('teacher:') if target else ''
    def get_user_target(self,user_id):
        c=self._connect()
        try:
            with c:
                row=c.execute('SELECT group_name FROM user_preferences WHERE user_id=?',(user_id,)).fetchone()
                return row[0] if row else None
        finally: c.close()
    def get_user_group(self,user_id):
        return self.get_user_target(user_id)
    def save_user_target(self,user_id,target):
        self._check_reload()
        if self.is_teacher_target(target):
            t_name=self.target_name(target)
            if t_name not in self.get_teachers(): raise UnknownGroup('Преподаватель не найден.')
        else:
            if target not in self.get_groups(): raise UnknownGroup('Группа не найдена.')
        c=self._connect()
        try:
            with c: c.execute('INSERT INTO user_preferences(user_id,group_name,last_active) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET group_name=excluded.group_name,last_active=CURRENT_TIMESTAMP',(user_id,target))
        finally: c.close()
    def save_user_group(self,user_id,group):
        return self.save_user_target(user_id,group)

data_manager=DataManager()
