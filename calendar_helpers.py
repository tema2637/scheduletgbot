from datetime import timedelta
import hashlib

def inline_target(text,today):
    text=text.strip().lower()
    if 'недел' in text:
        next_week='след' in text
        monday=today-timedelta(days=today.weekday())
        return 'week',monday+timedelta(weeks=int(next_week)),'Следующая неделя' if next_week else 'Неделя'
    if 'послезавтра' in text: return 'day',today+timedelta(days=2),'Послезавтра'
    if 'завтра' in text: return 'day',today+timedelta(days=1),'Завтра'
    return 'day',today,'Сегодня'

def prepare_inline(manager,user_id,group,query):
    import ui_templates as ui
    kind,target,label=inline_target(query,manager.now())
    if kind=='week': text=manager.get_week_text(group,target)
    else:
        lessons=manager.get_schedule_for_day(group,target)
        text='👥 <b>'+ui.safe(group)+'</b>\n'+ui.format_day_schedule(target,lessons,manager.get_academic_week(target))+manager.status_note()
    if len(text)>3800: text='Расписание слишком длинное для одного inline-сообщения. Откройте бота: там оно показано полностью.'
    key=f'{user_id}|{group}|{kind}|{target:%Y-%m-%d}|{manager._revision}|{manager._error}'
    return hashlib.sha256(key.encode()).hexdigest()[:32],f'📅 {label} — {group}',text
