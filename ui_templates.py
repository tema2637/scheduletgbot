from collections import defaultdict
from datetime import timedelta
from html import escape
import config
DAYS=['ПОНЕДЕЛЬНИК','ВТОРНИК','СРЕДА','ЧЕТВЕРГ','ПЯТНИЦА','СУББОТА','ВОСКРЕСЕНЬЕ']
def safe(value,limit=150):
    text=' '.join(str(value).split())
    return escape(text if len(text)<=limit else text[:limit-1]+'…',quote=False)
def footer():
    if not config.FOOTER_TEXT: return ''
    text=safe(config.FOOTER_TEXT,150)
    if config.FOOTER_URL.startswith(('https://','http://')):
        return '\n\n➖\n<a href="'+escape(config.FOOTER_URL,quote=True)+'">'+text+'</a>'
    return '\n\n➖\n'+text
def format_day_schedule(day,lessons,week_num,is_teacher=False,target_name=''):
    prefix=f'👨‍🏫 <b>{safe(target_name)}</b>\n' if (is_teacher and target_name) else ''
    head=prefix+f'📅 <b>{DAYS[day.weekday()]}</b> | {day:%d.%m.%Y}'
    if week_num>0: head+=f' | Неделя: {week_num}'
    if lessons is None: return head+'\n\nℹ️ Дата вне периода загруженного расписания. Наличие занятий на эту дату не подтверждено.'
    if not lessons: return head+'\n\n✨ На этот день в расписании занятий нет.'
    grouped=defaultdict(list)
    for r in lessons: grouped[r['TimeSlot']['NumberSlot']].append(r)
    parts=[head]
    for number,items in sorted(grouped.items()):
        slot=items[0]['TimeSlot']
        block=f'🔹 <b>Пара №{number}</b> <code>{slot["StartTime"]}–{slot["EndTime"]}</code>'
        seen=set()
        for r in items:
            key=(r['LessonTitle'],r['TeacherName'] if not is_teacher else r['Group']['Name'],r['Cabinet'])
            if key in seen: continue
            seen.add(key)
            block+='\n📘 <b>'+safe(r['LessonTitle'])+'</b>'
            if is_teacher: block+='\n👥 Группа: <b>'+safe(r['Group']['Name'])+'</b>'
            block+='\n📍 '+safe(r['Cabinet'] or 'Кабинет не указан',40)
            if not is_teacher and r['TeacherName']: block+='\n👤 '+safe(r['TeacherName'],100)
        parts.append(block)
    line='\u2508'*18
    body=parts[0]+'\n\n'+line+'\n'+('\n'+line+'\n').join(parts[1:])
    return body+footer()

def format_teacher_week_schedule(start,get_schedule,teacher_name,week_num):
    monday=start-timedelta(days=start.weekday()); friday=monday+timedelta(days=4)
    head=f'🗓 <b>ПРЕПОДАВАТЕЛЬ: {safe(teacher_name)}</b>\n📅 {monday:%d.%m.%Y} — {friday:%d.%m.%Y}'
    if week_num>0: head+=f' | Неделя: {week_num}'
    parts=[head]
    for i in range(5):
        day=monday+timedelta(days=i); lessons=get_schedule(teacher_name,day)
        lines=[f'<b>{DAYS[i]} ({day:%d.%m})</b>']
        if lessons is None: lines.append('Дата вне периода расписания')
        elif not lessons: lines.append('Нет занятий по загруженному расписанию')
        else:
            grouped=defaultdict(list)
            for r in lessons: grouped[r['TimeSlot']['NumberSlot']].append(r)
            for _,items in sorted(grouped.items()):
                details=[f"{r['LessonTitle']} [{r['Group']['Name']}]"+(f" ({r['Cabinet']})" if r.get('Cabinet') else "") for r in items]
                text=' / '.join(dict.fromkeys(details))
                lines.append('<code>'+items[0]['TimeSlot']['StartTime']+'</code> '+safe(text,110))
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)+footer()

def format_week_schedule(start,get_schedule,group,week_num):
    monday=start-timedelta(days=start.weekday()); friday=monday+timedelta(days=4)
    head=f'🗓 <b>ГРУППА: {safe(group)}</b>\n📅 {monday:%d.%m.%Y} — {friday:%d.%m.%Y}'
    if week_num>0: head+=f' | Неделя: {week_num}'
    parts=[head]
    for i in range(5):
        day=monday+timedelta(days=i); lessons=get_schedule(group,day)
        lines=[f'<b>{DAYS[i]} ({day:%d.%m})</b>']
        if lessons is None: lines.append('Дата вне периода расписания')
        elif not lessons: lines.append('Нет занятий по загруженному расписанию')
        else:
            grouped=defaultdict(list)
            for r in lessons: grouped[r['TimeSlot']['NumberSlot']].append(r)
            for _,items in sorted(grouped.items()):
                titles=' / '.join(dict.fromkeys(r['LessonTitle'] for r in items))
                lines.append('<code>'+items[0]['TimeSlot']['StartTime']+'</code> '+safe(titles,90))
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)+footer()
def split_messages(text,limit=3800):
    chunks=[]; current=''
    for line in text.split('\n'):
        if len(line)>limit: raise ValueError('Слишком длинная строка сообщения.')
        candidate=current+('\n' if current else '')+line
        if len(candidate)>limit: chunks.append(current); current=line
        else: current=candidate
    if current: chunks.append(current)
    return chunks
