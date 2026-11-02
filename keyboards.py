import hashlib
import re
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,KeyboardButton,ReplyKeyboardMarkup
from data_manager import data_manager

def group_id(value): return hashlib.sha256(value.encode()).hexdigest()[:16]
def prefix(value):
    m=re.match(r'^\d*([^\d]+)',value)
    return (m.group(1) if m else value).strip(' -–—')
TEACHER_BUCKETS = [
    ('А–В', 'АБВ'), ('Г–Д', 'ГД'), ('Е–И', 'ЕЁЖЗИЙ'), ('К–Л', 'КЛ'),
    ('М–Н', 'МН'), ('О–П', 'ОП'), ('Р–С', 'РС'), ('Т–Я', 'ТУФХЦЧШЩЭЮЯ')
]

def teacher_id(value): return hashlib.sha256(('t:'+value).encode()).hexdigest()[:16]

def get_main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in [['📅 Сегодня','⏭ Завтра'],['🗓 Неделя','📆 След. неделя'],['⚙️ Настройки','🔍 Преподаватель']]],resize_keyboard=True)

def get_settings_keyboard(user_id=None):
    nt=data_manager.get_user_notify_time(user_id) if user_id else None
    notify_text=f'🔔 Напоминание: {nt}' if nt else '🔕 Напоминание: Выкл'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👨‍🎓 Выбрать группу',callback_data='set:student')],
        [InlineKeyboardButton(text='👨‍🏫 Выбрать преподавателя',callback_data='set:teacher')],
        [InlineKeyboardButton(text=notify_text,callback_data='set:time_menu')]
    ])

def get_notify_time_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='18:00',callback_data='nt:18:00'),
         InlineKeyboardButton(text='19:00',callback_data='nt:19:00'),
         InlineKeyboardButton(text='20:00',callback_data='nt:20:00')],
        [InlineKeyboardButton(text='21:00',callback_data='nt:21:00'),
         InlineKeyboardButton(text='22:00',callback_data='nt:22:00'),
         InlineKeyboardButton(text='07:30',callback_data='nt:07:30')],
        [InlineKeyboardButton(text='07:00',callback_data='nt:07:00'),
         InlineKeyboardButton(text='08:00',callback_data='nt:08:00'),
         InlineKeyboardButton(text='🔕 Выключить',callback_data='nt:off')],
        [InlineKeyboardButton(text='⬅️ Назад',callback_data='set:back')]
    ])

def get_group_prefixes_keyboard():
    values=sorted({prefix(g) for g in data_manager.get_groups()})
    buttons=[InlineKeyboardButton(text=p,callback_data='prefix:'+group_id(p)) for p in values]
    rows=[buttons[i:i+3] for i in range(0,len(buttons),3)]
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='set:back')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_groups_by_prefix_keyboard(selected):
    groups=[g for g in data_manager.get_groups() if prefix(g)==selected]
    buttons=[InlineKeyboardButton(text=g,callback_data='group:'+group_id(g)) for g in groups]
    rows=[buttons[i:i+2] for i in range(0,len(buttons),2)]
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='prefixes')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_teacher_buckets_keyboard(back_callback='set:back'):
    buttons=[InlineKeyboardButton(text=label,callback_data=f'tb:{i}') for i,(label,_) in enumerate(TEACHER_BUCKETS)]
    rows=[buttons[i:i+3] for i in range(0,len(buttons),3)]
    if back_callback:
        rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_teachers_by_bucket_keyboard(bucket_index):
    _,chars=TEACHER_BUCKETS[bucket_index]
    teachers=[t for t in data_manager.get_teachers() if t and t[0].upper() in chars]
    buttons=[InlineKeyboardButton(text=t,callback_data='tset:'+teacher_id(t)) for t in teachers]
    rows=[buttons[i:i+2] for i in range(0,len(buttons),2)]
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='set:teacher')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_teacher_view_keyboard(teacher_name,day):
    val=day.strftime('%Y-%m-%d')
    tid=teacher_id(teacher_name)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️',callback_data=f'tday:{tid}:{val}:prev'),
         InlineKeyboardButton(text='📅 Сегодня',callback_data=f'tday:{tid}:today'),
         InlineKeyboardButton(text='➡️',callback_data=f'tday:{tid}:{val}:next')],
        [InlineKeyboardButton(text='🗓 Неделя',callback_data=f'tweek:{tid}'),
         InlineKeyboardButton(text='🖼 Картинка дня',callback_data=f'pic:tday:{tid}:{val}')],
        [InlineKeyboardButton(text='📌 Сделать моим расписанием',callback_data=f'tset:{tid}')]
    ])

def get_teacher_search_results_keyboard(teachers):
    buttons=[InlineKeyboardButton(text=t,callback_data='tpick:'+teacher_id(t)) for t in teachers[:10]]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+2] for i in range(0,len(buttons),2)])
def get_schedule_nav_keyboard(day):
    value=day.strftime('%Y-%m-%d')
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️',callback_data=f'day:{value}:prev'),
         InlineKeyboardButton(text='📅 Сегодня',callback_data='day:today'),
         InlineKeyboardButton(text='➡️',callback_data=f'day:{value}:next')],
        [InlineKeyboardButton(text='🖼 Картинка дня',callback_data=f'pic:day:{value}')]
    ])
