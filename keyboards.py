import hashlib
import re
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,KeyboardButton,ReplyKeyboardMarkup
from data_manager import data_manager

def group_id(value): return hashlib.sha256(value.encode()).hexdigest()[:16]
def prefix(value):
    m=re.match(r'^\d*([^\d]+)',value)
    return (m.group(1) if m else value).strip(' -–—')
def get_main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in [['📅 Сегодня','⏭ Завтра'],['🗓 Неделя','📆 След. неделя'],['⚙️ Настройки']]],resize_keyboard=True)
def get_group_prefixes_keyboard():
    values=sorted({prefix(g) for g in data_manager.get_groups()})
    buttons=[InlineKeyboardButton(text=p,callback_data='prefix:'+group_id(p)) for p in values]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+3] for i in range(0,len(buttons),3)])
def get_groups_by_prefix_keyboard(selected):
    groups=[g for g in data_manager.get_groups() if prefix(g)==selected]
    buttons=[InlineKeyboardButton(text=g,callback_data='group:'+group_id(g)) for g in groups]
    rows=[buttons[i:i+2] for i in range(0,len(buttons),2)]
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='prefixes')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def get_schedule_nav_keyboard(day):
    value=day.strftime('%Y-%m-%d')
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='⬅️',callback_data=f'day:{value}:prev'),
        InlineKeyboardButton(text='📅 Сегодня',callback_data='day:today'),
        InlineKeyboardButton(text='➡️',callback_data=f'day:{value}:next')]])
