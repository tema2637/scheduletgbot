"""Общая валидация и атомарная публикация расписания."""
from copy import deepcopy
from datetime import time
from pathlib import Path
import json
import os
import tempfile
from times import TIME_SLOTS

def validate(data):
    if not isinstance(data,list) or not data:
        raise ValueError('Нужен непустой JSON-массив занятий.')
    result=[]
    for number,item in enumerate(data,1):
        if not isinstance(item,dict): raise ValueError(f'Запись {number}: нужен объект.')
        r=deepcopy(item)
        for field in ['LessonTitle','TeacherName','Cabinet']:
            value=r.get(field,'')
            if not isinstance(value,str): raise ValueError(f'Запись {number}: {field} должен быть строкой.')
            r[field]=' '.join(value.split())
        if not r['LessonTitle']: raise ValueError(f'Запись {number}: пустой предмет.')
        g=r.get('Group')
        if not isinstance(g,dict) or not isinstance(g.get('Name'),str) or not g['Name'].strip():
            raise ValueError(f'Запись {number}: нет группы.')
        r['Group']={'Name':' '.join(g['Name'].split())}
        weeks=r.get('Weeks')
        if not isinstance(weeks,list) or not weeks or any(type(w) is not int or not 1<=w<=60 for w in weeks):
            raise ValueError(f'Запись {number}: неверные недели, допустимо 1..60.')
        r['Weeks']=sorted(set(weeks))
        slot=r.get('TimeSlot')
        if not isinstance(slot,dict): raise ValueError(f'Запись {number}: нет TimeSlot.')
        day=slot.get('DayOfWeek')
        lesson=slot.get('NumberSlot')
        if type(day) is not int or not 1<=day<=7: raise ValueError('Неверный день недели.')
        if type(lesson) is not int or not 1<=lesson<=12: raise ValueError('Неверный номер пары.')
        expected=TIME_SLOTS.get(day,{}).get(lesson)
        if expected is None:
            raise ValueError(f'Запись {number}: для дня {day} пары {lesson} нет звонков в TIME_SLOTS.')
        times=[]
        for key in ['StartTime','EndTime']:
            v=slot.get(key,'')
            if not isinstance(v,str) or len(v)!=5 or v[2]!=':': raise ValueError(f'Запись {number}: проверьте время звонков {key}.')
            times.append(time.fromisoformat(v))
        actual=(slot.get('StartTime'),slot.get('EndTime'))
        if actual!=expected:
            raise ValueError(
                f'Запись {number}: время пары {day}/{lesson} {actual[0]}–{actual[1]} '
                f'не совпадает с TIME_SLOTS {expected[0]}–{expected[1]}.'
            )
        if times[1]<=times[0]: raise ValueError(f'Запись {number}: конец пары должен быть позже начала.')
        result.append(r)
    return result

def atomic_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as f:
            tmp=f.name
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path); tmp=None
    finally:
        if tmp is not None:
            try: os.unlink(tmp)
            except FileNotFoundError: pass

def publish(path,data):
    atomic_json(path,validate(data))
