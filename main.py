"""Telegram-бот. При импорте файла реальный Bot не создаётся."""
import asyncio
from datetime import datetime,timedelta
import logging
from logging.handlers import RotatingFileHandler
import sys
import config
from data_manager import data_manager,ScheduleUnavailable,UnknownGroup,UNAVAILABLE

async def run_bot():
    from aiogram import Bot,Dispatcher,F,types
    from aiogram.client.default import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.filters import Command
    from aiogram.exceptions import TelegramBadRequest,TelegramRetryAfter
    from inline_handler import inline_router
    from retry import RetryRequestMiddleware
    import keyboards
    import subscription
    import ui_templates as ui
    if not config.BOT_TOKEN:
        raise ValueError('Заполните BOT_TOKEN в .env рядом с main.py.')
    session=AiohttpSession(proxy=config.PROXY) if config.PROXY else None
    bot=Bot(config.BOT_TOKEN,default=DefaultBotProperties(parse_mode='HTML'),session=session)
    bot.session.middleware(RetryRequestMiddleware())
    subscription.init(bot, config.CHANNEL)
    if not await subscription.check_configuration():
        raise RuntimeError(
            'Проверка канала не пройдена: бот должен быть администратором канала '
            'или укажите CHANNEL="" / REQUIRE_SUBSCRIPTION=false.'
        )
    dp=Dispatcher(); dp.update.middleware(subscription.SubscriptionMiddleware()); dp.include_router(inline_router)

    def get_target_id(event) -> int:
        if isinstance(event, types.CallbackQuery):
            msg = event.message
            if msg and msg.chat and msg.chat.type in ('group', 'supergroup'):
                return msg.chat.id
            return event.from_user.id if event.from_user else 0
        if isinstance(event, types.Message):
            if event.chat and event.chat.type in ('group', 'supergroup'):
                return event.chat.id
            return event.from_user.id if event.from_user else 0
        return 0

    async def send_chunks(message,text,keyboard=None):
        parts=ui.split_messages(text)
        for i,part in enumerate(parts):
            await message.answer(part,parse_mode='HTML',reply_markup=keyboard if i==len(parts)-1 else None)
    async def choose(message):
        if message.chat and message.chat.type in ('group', 'supergroup'):
            return await message.answer(
                '⚙️ <b>Настройка группы для беседы</b>\n'
                'Укажите группу командой:\n'
                'Например: <code>/group РЗ 252</code>',
                parse_mode='HTML'
            )
        uid=message.from_user.id if message.from_user else None
        await message.answer('⚙️ <b>Настройки расписания</b>\nКто вы?',reply_markup=keyboards.get_settings_keyboard(uid),parse_mode='HTML')

    @dp.errors()
    async def errors_handler(event:types.ErrorEvent):
        exc=event.exception
        if isinstance(exc,TelegramBadRequest) and any(v in str(exc).lower() for v in ['message is not modified','query is too old','query id is invalid']): return True
        logger=logging.getLogger(__name__)
        logger.error('Ошибка Telegram: %s',type(exc).__name__,exc_info=(type(exc),exc,exc.__traceback__))
        message=event.update.message
        if message is None and event.update.callback_query: message=event.update.callback_query.message
        if isinstance(message,types.Message):
            if isinstance(exc,ScheduleUnavailable): text=UNAVAILABLE
            elif isinstance(exc,UnknownGroup): text='Группа или преподаватель не найдены. Откройте настройки и выберите заново.'
            elif isinstance(exc,TelegramRetryAfter): text='Telegram ограничил отправку. Попробуйте чуть позже.'
            else: text='Не удалось выполнить действие. Попробуйте позже. Ошибка не означает, что занятий нет.'
            try: await message.answer(text)
            except Exception: logger.warning('Не удалось отправить уведомление об ошибке.')
        return True

    @dp.message(Command('start','menu'))
    async def start(message:types.Message):
        if not message.from_user: return
        cid=get_target_id(message)
        data_manager.touch_user(cid)
        if message.chat and message.chat.type in ('group','supergroup'):
            target=data_manager.get_user_target(cid)
            if target:
                return await message.answer(
                    f'👋 «Опять пары» в беседе!\n'
                    f'Группа беседы: <b>{ui.safe(target)}</b>\n\n'
                    f'📌 <b>Команды:</b>\n'
                    f'/today — расписание на сегодня\n'
                    f'/tomorrow — на завтра\n'
                    f'/week — на неделю\n'
                    f'/pic — картинка недели\n'
                    f'/daypic — картинка на день\n'
                    f'/group ИМЯ_ГРУППЫ — сменить группу',
                    parse_mode='HTML'
                )
            return await message.answer(
                '👋 Привет! Чтобы бот показывал расписание в этой беседе, укажите группу:\n'
                'Например: <code>/group РЗ 252</code>',
                parse_mode='HTML'
            )
        parts=(message.text or '').split(maxsplit=1)
        if len(parts)==2 and parts[1]=='select_group':
            if not await subscription.is_subscribed(message.from_user.id):
                return await message.answer(subscription.sub_text(),parse_mode='HTML',reply_markup=subscription.subscribe_keyboard())
            return await choose(message)
        target=data_manager.get_user_target(message.from_user.id)
        if target:
            if data_manager.is_teacher_target(target):
                label='Преподаватель: <b>'+ui.safe(data_manager.target_name(target))+'</b>'
            else:
                label='Группа: <b>'+ui.safe(target)+'</b>'
            await message.answer('👋 «Опять пары»\n'+label,reply_markup=keyboards.get_main_keyboard(),parse_mode='HTML')
        else:
            if not await subscription.is_subscribed(message.from_user.id):
                await message.answer(subscription.sub_text(),parse_mode='HTML',reply_markup=subscription.subscribe_keyboard())
                return
            await message.answer('👋 Привет! Выберите свою группу или преподавателя.')
            await choose(message)

    async def show_day(event,target):
        callback=isinstance(event,types.CallbackQuery)
        message=event.message if callback else event
        if not isinstance(message,types.Message) or not event.from_user: return
        cid=get_target_id(event)
        data_manager.touch_user(cid)
        user_target=data_manager.get_user_target(cid)
        if not user_target:
            if message.chat and message.chat.type in ('group','supergroup'):
                return await message.answer('В этой беседе не выбрана группа. Напишите: <code>/group РЗ 252</code>',parse_mode='HTML')
            return await choose(message)
        if data_manager.is_teacher_target(user_target):
            t_name=data_manager.target_name(user_target)
            lessons=data_manager.get_teacher_schedule_for_day(t_name,target)
            text=ui.format_day_schedule(target,lessons,data_manager.get_academic_week(target),is_teacher=True,target_name=t_name)+data_manager.status_note()
        else:
            group=user_target
            lessons=data_manager.get_schedule_for_day(group,target)
            text='👥 <b>'+ui.safe(group)+'</b>\n'+ui.format_day_schedule(target,lessons,data_manager.get_academic_week(target))+data_manager.status_note()
        keyboard=keyboards.get_schedule_nav_keyboard(target)
        if not callback: return await send_chunks(message,text,keyboard)
        parts=ui.split_messages(text)
        try: await message.edit_text(parts[0],parse_mode='HTML',reply_markup=keyboard if len(parts)==1 else None)
        except TelegramBadRequest as exc:
            if 'message is not modified' not in str(exc).lower(): raise
        for i,part in enumerate(parts[1:],1):
            await message.answer(part,parse_mode='HTML',reply_markup=keyboard if i==len(parts)-1 else None)

    @dp.message(F.text=='📅 Сегодня')
    @dp.message(Command('today','сегодня','day'))
    async def today(message:types.Message): await show_day(message,data_manager.now())

    @dp.message(F.text=='⏭ Завтра')
    @dp.message(Command('tomorrow','завтра'))
    async def tomorrow(message:types.Message): await show_day(message,data_manager.now()+timedelta(days=1))

    async def show_week(message,following=False):
        if not message.from_user: return
        cid=get_target_id(message)
        data_manager.touch_user(cid)
        user_target=data_manager.get_user_target(cid)
        if not user_target:
            if message.chat and message.chat.type in ('group','supergroup'):
                return await message.answer('В этой беседе не выбрана группа. Напишите: <code>/group РЗ 252</code>',parse_mode='HTML')
            return await choose(message)
        now=data_manager.now(); monday=now-timedelta(days=now.weekday())+timedelta(weeks=int(following))
        if data_manager.is_teacher_target(user_target):
            text=data_manager.get_teacher_week_text(data_manager.target_name(user_target),monday)
        else:
            text=data_manager.get_week_text(user_target,monday)
        pic_kb=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text='🖼 Картинка недели',callback_data='pic:next' if following else 'pic:cur')]])
        await send_chunks(message,text,pic_kb)

    @dp.message(F.text=='🗓 Неделя')
    @dp.message(Command('week','неделя'))
    async def week(message:types.Message): await show_week(message)

    @dp.message(F.text=='📆 След. неделя')
    @dp.message(Command('next_week','следнеделя'))
    async def next_week(message:types.Message): await show_week(message,True)

    @dp.message(F.text=='⚙️ Настройки')
    @dp.message(Command('settings','настройки'))
    async def settings(message:types.Message): await choose(message)

    @dp.message(Command('group','setgroup','группа'))
    async def cmd_group(message:types.Message):
        cid=get_target_id(message)
        parts=(message.text or '').split(maxsplit=1)
        if len(parts)<2:
            cur=data_manager.get_user_target(cid)
            cur_label=f" Текущая: <b>{ui.safe(cur)}</b>." if cur else ""
            return await message.answer(f"Использование: <code>/group ИМЯ_ГРУППЫ</code> (например: <code>/group РЗ 252</code>).{cur_label}",parse_mode='HTML')
        query=parts[1].strip()
        matched=next((g for g in data_manager.get_groups() if g.lower()==query.lower()),None)
        if not matched:
            cands=[g for g in data_manager.get_groups() if query.lower() in g.lower()]
            if len(cands)==1: matched=cands[0]
        if not matched:
            return await message.answer(f"Группа «{ui.safe(query)}» не найдена в расписании. Проверьте правильность написания.")
        data_manager.save_user_target(cid,matched)
        chat_kind="этой беседы" if message.chat and message.chat.type in ('group','supergroup') else "вас"
        await message.answer(
            f"✅ Для {chat_kind} установлена группа: <b>{ui.safe(matched)}</b>\n"
            f"Доступные команды: /today, /tomorrow, /week, /pic, /daypic",
            parse_mode='HTML',
            reply_markup=keyboards.get_main_keyboard() if message.chat.type=='private' else None
        )

    @dp.message(Command('stats','stat','статистика'))
    async def cmd_stats(message:types.Message):
        if not message.from_user or message.from_user.id!=config.ADMIN_ID:
            return
        stats=data_manager.get_stats()
        top_lines=[f"{i}. <b>{ui.safe(g)}</b> — {cnt}" for i,(g,cnt) in enumerate(stats['top_groups'],1)]
        top_str='\n'.join(top_lines) if top_lines else 'нет данных'
        text=(
            "📊 <b>Статистика бота</b>\n\n"
            f"👤 Пользователей (ЛС): <b>{stats['total_users']}</b>\n"
            f"💬 Бесед (групп): <b>{stats['total_chats']}</b>\n"
            f"⚡ Активных за 24 ч: <b>{stats['active_24h']}</b>\n"
            f"📅 Активных за 7 дней: <b>{stats['active_7d']}</b>\n"
            f"⏰ С напоминаниями: <b>{stats['with_reminders']}</b>\n"
            f"👨‍🏫 В режиме преподавателя: <b>{stats['teachers_users']}</b>\n\n"
            f"🏆 <b>Топ групп:</b>\n{top_str}"
        )
        await message.answer(text,parse_mode='HTML')

    async def send_schedule_image(event,target,monday):
        from image_generator import render_week_image
        callback=isinstance(event,types.CallbackQuery)
        message=event.message if callback else event
        is_t=data_manager.is_teacher_target(target)
        name=data_manager.target_name(target) if is_t else target
        try:
            png_bytes=render_week_image(name,monday,is_teacher=is_t)
            fn=f"schedule_{name.replace(' ', '_')}_{monday:%d_%m}.png"
            friday=monday+timedelta(days=4)
            caption=f"🖼 <b>Расписание: {ui.safe(name)}</b>\n({monday:%d.%m} — {friday:%d.%m})"
            await message.answer_photo(
                photo=types.BufferedInputFile(png_bytes,filename=fn),
                caption=caption,
                parse_mode='HTML'
            )
        except Exception as exc:
            if callback: await event.answer('Не удалось сформировать картинку.')
            else: await handle_error(message,exc)

    async def send_day_schedule_image(event,target,day):
        from image_generator import render_day_image
        callback=isinstance(event,types.CallbackQuery)
        message=event.message if callback else event
        is_t=data_manager.is_teacher_target(target)
        name=data_manager.target_name(target) if is_t else target
        try:
            png_bytes=render_day_image(name,day,is_teacher=is_t)
            fn=f"day_{name.replace(' ', '_')}_{day:%d_%m}.png"
            caption=f"🖼 <b>Расписание: {ui.safe(name)}</b> ({day:%d.%m.%Y})"
            await message.answer_photo(
                photo=types.BufferedInputFile(png_bytes,filename=fn),
                caption=caption,
                parse_mode='HTML'
            )
        except Exception as exc:
            if callback: await event.answer('Не удалось сформировать картинку дня.')
            else: await handle_error(message,exc)

    @dp.message(Command('pic','photo','image','картинка'))
    async def cmd_pic(message:types.Message):
        if not message.from_user: return
        cid=get_target_id(message)
        user_target=data_manager.get_user_target(cid)
        if not user_target:
            if message.chat and message.chat.type in ('group','supergroup'):
                return await message.answer('В этой беседе не выбрана группа. Напишите: <code>/group РЗ 252</code>',parse_mode='HTML')
            return await choose(message)
        now=data_manager.now(); monday=now-timedelta(days=now.weekday())
        await send_schedule_image(message,user_target,monday)

    @dp.message(Command('daypic','day_pic','картинка_дня'))
    async def cmd_daypic(message:types.Message):
        if not message.from_user: return
        cid=get_target_id(message)
        user_target=data_manager.get_user_target(cid)
        if not user_target:
            if message.chat and message.chat.type in ('group','supergroup'):
                return await message.answer('В этой беседе не выбрана группа. Напишите: <code>/group РЗ 252</code>',parse_mode='HTML')
            return await choose(message)
        now=data_manager.now()
        target_day=(now+timedelta(days=1)).date() if now.hour>=18 else now.date()
        await send_day_schedule_image(message,user_target,target_day)

    @dp.callback_query(F.data.startswith('pic:'))
    async def callback_pic(callback:types.CallbackQuery):
        await callback.answer('Генерирую картинку...')
        if not callback.from_user: return
        cid=get_target_id(callback)
        user_target=data_manager.get_user_target(cid)
        parts=(callback.data or '').split(':')
        now=data_manager.now()

        if len(parts)>=3 and parts[1]=='day':
            day=datetime.strptime(parts[2],'%Y-%m-%d').date()
            if not user_target: return await choose(callback.message)
            return await send_day_schedule_image(callback,user_target,day)

        if len(parts)>=4 and parts[1]=='tday':
            tid=parts[2]
            teacher=next((t for t in data_manager.get_teachers() if keyboards.teacher_id(t)==tid),None)
            if not teacher: return
            day=datetime.strptime(parts[3],'%Y-%m-%d').date()
            return await send_day_schedule_image(callback,'teacher:'+teacher,day)

        if len(parts)>=2 and parts[1]=='next':
            monday=now-timedelta(days=now.weekday())+timedelta(weeks=1)
            target=user_target
        elif len(parts)>=4 and parts[1]=='t':
            tid=parts[2]
            teacher=next((t for t in data_manager.get_teachers() if keyboards.teacher_id(t)==tid),None)
            if not teacher: return
            target='teacher:'+teacher
            monday=datetime.strptime(parts[3],'%Y-%m-%d').date()
        else:
            monday=now-timedelta(days=now.weekday())
            target=user_target
        if not target: return await choose(callback.message)
        await send_schedule_image(callback,target,monday)

    @dp.message(F.text=='🔍 Преподаватель')
    @dp.message(Command('teacher','t'))
    async def teacher_search_entry(message:types.Message):
        parts=(message.text or '').split(maxsplit=1)
        if len(parts)>1 and parts[0].startswith('/'):
            return await do_teacher_search(message,parts[1].strip())
        await message.answer(
            '🔍 <b>Поиск преподавателя</b>\n\n'
            'Напишите фамилию преподавателя в чат (например: <code>Шаталов</code> или <code>Денисенко</code>)\n'
            'или выберите по первой букве фамилии:',
            reply_markup=keyboards.get_teacher_buckets_keyboard(back_callback=None),
            parse_mode='HTML'
        )

    async def do_teacher_search(message:types.Message,query:str):
        matches=data_manager.find_teachers(query)
        if not matches:
            return await message.answer(f'Преподаватель по запросу «{ui.safe(query)}» не найден.\nПроверьте написание фамилии.')
        if len(matches)==1:
            return await show_searched_teacher(message,matches[0],data_manager.now())
        await message.answer(
            f'Найдено несколько преподавателей по запросу «{ui.safe(query)}»:\nВыберите нужного:',
            reply_markup=keyboards.get_teacher_search_results_keyboard(matches)
        )

    async def show_searched_teacher(event,teacher_name:str,target):
        callback=isinstance(event,types.CallbackQuery)
        message=event.message if callback else event
        lessons=data_manager.get_teacher_schedule_for_day(teacher_name,target)
        text=ui.format_day_schedule(target,lessons,data_manager.get_academic_week(target),is_teacher=True,target_name=teacher_name)+data_manager.status_note()
        keyboard=keyboards.get_teacher_view_keyboard(teacher_name,target)
        if not callback: return await send_chunks(message,text,keyboard)
        parts=ui.split_messages(text)
        try: await message.edit_text(parts[0],parse_mode='HTML',reply_markup=keyboard if len(parts)==1 else None)
        except TelegramBadRequest as exc:
            if 'message is not modified' not in str(exc).lower(): raise
        for i,part in enumerate(parts[1:],1):
            await message.answer(part,parse_mode='HTML',reply_markup=keyboard if i==len(parts)-1 else None)

    @dp.callback_query(F.data=='set:student')
    async def set_student(callback:types.CallbackQuery):
        await callback.answer()
        if isinstance(callback.message,types.Message):
            await callback.message.edit_text('Выберите специальность:',reply_markup=keyboards.get_group_prefixes_keyboard())

    @dp.callback_query(F.data=='set:teacher')
    async def set_teacher(callback:types.CallbackQuery):
        await callback.answer()
        if isinstance(callback.message,types.Message):
            await callback.message.edit_text('👨‍🏫 <b>Выберите преподавателя</b> по первой букве фамилии:',reply_markup=keyboards.get_teacher_buckets_keyboard(),parse_mode='HTML')

    @dp.callback_query(F.data=='set:back')
    async def set_back(callback:types.CallbackQuery):
        await callback.answer()
        if isinstance(callback.message,types.Message):
            uid=callback.from_user.id if callback.from_user else None
            await callback.message.edit_text('⚙️ <b>Настройки расписания</b>\nКто вы?',reply_markup=keyboards.get_settings_keyboard(uid),parse_mode='HTML')

    @dp.callback_query(F.data=='set:time_menu')
    async def time_menu(callback:types.CallbackQuery):
        await callback.answer()
        if isinstance(callback.message,types.Message):
            await callback.message.edit_text(
                '⏰ <b>Настройка времени напоминания</b>\n\n'
                '• <b>Вечерние</b> (18:00–22:00): присылают расписание на <b>завтра</b>\n'
                '• <b>Утренние</b> (07:00–08:00): присылают расписание на <b>сегодня</b>\n\n'
                'Выберите удобное время:',
                reply_markup=keyboards.get_notify_time_keyboard(),
                parse_mode='HTML'
            )

    @dp.callback_query(F.data.startswith('nt:'))
    async def set_notify_time(callback:types.CallbackQuery):
        if not callback.from_user or not isinstance(callback.message,types.Message): return
        val=(callback.data or '').removeprefix('nt:')
        uid=callback.from_user.id
        if val=='off':
            data_manager.set_user_notify_time(uid,None)
            await callback.answer('🔕 Напоминания выключены.',show_alert=True)
        else:
            data_manager.set_user_notify_time(uid,val)
            await callback.answer(f'🔔 Напоминание установлено на {val}!',show_alert=True)
        try:
            await callback.message.edit_text(
                '⚙️ <b>Настройки расписания</b>\nКто вы?',
                reply_markup=keyboards.get_settings_keyboard(uid),
                parse_mode='HTML'
            )
        except TelegramBadRequest: pass

    @dp.callback_query(F.data.startswith('tb:'))
    async def pick_bucket(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        idx=int((callback.data or '').removeprefix('tb:'))
        await callback.message.edit_text('Выберите преподавателя:',reply_markup=keyboards.get_teachers_by_bucket_keyboard(idx))

    @dp.callback_query(F.data.startswith('tset:'))
    async def pick_teacher_save(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        wanted=(callback.data or '').removeprefix('tset:')
        teacher=next((t for t in data_manager.get_teachers() if keyboards.teacher_id(t)==wanted),None)
        if not teacher: raise UnknownGroup('Преподаватель не найден.')
        cid=get_target_id(callback)
        data_manager.save_user_target(cid,'teacher:'+teacher)
        await callback.message.edit_text(f'✅ Выбран преподаватель: <b>{ui.safe(teacher)}</b>',parse_mode='HTML')
        await callback.message.answer('Расписание доступно через кнопки 👇',reply_markup=keyboards.get_main_keyboard() if callback.message.chat.type=='private' else None)

    @dp.callback_query(F.data.startswith('tpick:'))
    async def pick_teacher_view(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        wanted=(callback.data or '').removeprefix('tpick:')
        teacher=next((t for t in data_manager.get_teachers() if keyboards.teacher_id(t)==wanted),None)
        if not teacher: raise UnknownGroup('Преподаватель не найден.')
        await show_searched_teacher(callback,teacher,data_manager.now())

    @dp.callback_query(F.data.startswith('tday:'))
    async def teacher_day_nav(callback:types.CallbackQuery):
        await callback.answer()
        parts=(callback.data or '').split(':')
        try:
            tid=parts[1]
            teacher=next((t for t in data_manager.get_teachers() if keyboards.teacher_id(t)==tid),None)
            if not teacher: raise UnknownGroup('Преподаватель не найден.')
            if len(parts)==3 and parts[2]=='today': target=data_manager.now()
            elif len(parts)==4 and parts[3] in ['prev','next']:
                target=datetime.strptime(parts[2],'%Y-%m-%d')+timedelta(days=1 if parts[3]=='next' else -1)
            else: raise ValueError('Неверная кнопка.')
        except (ValueError,OverflowError,IndexError):
            if isinstance(callback.message,types.Message): await callback.message.answer('Кнопка устарела.')
            return
        await show_searched_teacher(callback,teacher,target)

    @dp.callback_query(F.data.startswith('tweek:'))
    async def teacher_week_view(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        wanted=(callback.data or '').removeprefix('tweek:')
        teacher=next((t for t in data_manager.get_teachers() if keyboards.teacher_id(t)==wanted),None)
        if not teacher: raise UnknownGroup('Преподаватель не найден.')
        now=data_manager.now(); monday=now-timedelta(days=now.weekday())
        text=data_manager.get_teacher_week_text(teacher,monday)
        pic_kb=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text='🖼 Картинка недели',callback_data=f'pic:t:{wanted}:{monday:%Y-%m-%d}')]])
        await send_chunks(callback.message,text,pic_kb)

    @dp.callback_query(F.data.startswith('prefix:'))
    async def pick_prefix(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        wanted=(callback.data or '').removeprefix('prefix:')
        value=next((p for p in sorted({keyboards.prefix(g) for g in data_manager.get_groups()}) if keyboards.group_id(p)==wanted),None)
        if value is None: return await choose(callback.message)
        await callback.message.edit_text('Выберите группу:',reply_markup=keyboards.get_groups_by_prefix_keyboard(value))
    @dp.callback_query(F.data=='prefixes')
    async def back(callback:types.CallbackQuery):
        await callback.answer()
        if isinstance(callback.message,types.Message): await callback.message.edit_text('Выберите специальность:',reply_markup=keyboards.get_group_prefixes_keyboard())
    @dp.callback_query(F.data.startswith('group:'))
    async def pick_group(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        wanted=(callback.data or '').removeprefix('group:')
        group=next((g for g in data_manager.get_groups() if keyboards.group_id(g)==wanted),None)
        if not group: raise UnknownGroup('Группа не найдена.')
        cid=get_target_id(callback)
        data_manager.save_user_target(cid,group)
        await callback.message.edit_text('✅ Группа: <b>'+ui.safe(group)+'</b>',parse_mode='HTML')
        await callback.message.answer('Расписание доступно через кнопки 👇',reply_markup=keyboards.get_main_keyboard() if callback.message.chat.type=='private' else None)
    @dp.callback_query(F.data.startswith('day:'))
    async def navigation(callback:types.CallbackQuery):
        await callback.answer()
        parts=(callback.data or '').split(':')
        try:
            if parts==['day','today']: target=data_manager.now()
            elif len(parts)==3 and parts[2] in ['prev','next']:
                target=datetime.strptime(parts[1],'%Y-%m-%d')+timedelta(days=1 if parts[2]=='next' else -1)
            else: raise ValueError('Неверная кнопка.')
        except (ValueError,OverflowError):
            if isinstance(callback.message,types.Message): await callback.message.answer('Кнопка устарела. Нажмите «Сегодня».')
            return
        await show_day(callback,target)
    @dp.callback_query(F.data=='sub:check')
    async def sub_check(callback:types.CallbackQuery):
        await callback.answer()
        message=callback.message
        if not isinstance(message,types.Message) or not callback.from_user: return
        if await subscription.is_subscribed(callback.from_user.id,force=True):
            try: await message.edit_text('✅ Спасибо! Теперь выберите группу.')
            except TelegramBadRequest: pass
            await choose(message)
            return
        await callback.answer('Вы ещё не подписались. Откройте канал и нажмите «Я подписался».',show_alert=True)
    @dp.callback_query()
    async def old_button(callback:types.CallbackQuery): await callback.answer('Кнопка от старой версии. Откройте /start.',show_alert=True)
    @dp.message(Command('help','помощь'))
    async def help_command(message:types.Message):
        if message.chat and message.chat.type in ('group','supergroup'):
            await message.answer(
                '📌 <b>Команды бота в беседе:</b>\n'
                '/today — расписание на сегодня\n'
                '/tomorrow — на завтра\n'
                '/week — на неделю\n'
                '/pic — расписание недели картинкой\n'
                '/daypic — расписание дня картинкой\n'
                '/group ИМЯ_ГРУППЫ — установить группу для беседы',
                parse_mode='HTML'
            )
            return
        await message.answer('Выберите группу или преподавателя в /start или через ⚙️ Настройки.\nДля поиска преподавателя напишите его фамилию в чат или нажмите кнопку «🔍 Преподаватель».',reply_markup=keyboards.get_main_keyboard())
    @dp.message()
    async def unknown(message:types.Message):
        if message.chat and message.chat.type in ('group','supergroup'):
            return
        text=(message.text or '').strip()
        if len(text)>=3:
            matches=data_manager.find_teachers(text)
            if matches:
                return await do_teacher_search(message,text)
        await message.answer('Используйте меню или отправьте фамилию преподавателя для поиска.',reply_markup=keyboards.get_main_keyboard())
    async def background_worker():
        last_sent_hm=''
        while True:
            try:
                await asyncio.sleep(30)
                # 1. Проверка обновления файла расписания
                has_changed,changed_targets=data_manager.check_and_reload()
                if has_changed and changed_targets:
                    for target in changed_targets:
                        users=data_manager.get_users_by_target(target)
                        if not users: continue
                        label=f"преподавателя <b>{ui.safe(data_manager.target_name(target))}</b>" if data_manager.is_teacher_target(target) else f"группы <b>{ui.safe(target)}</b>"
                        msg=f"📢 <b>Внимание! Расписание обновилось.</b>\nВ расписании {label} произошли изменения. Нажмите «📅 Сегодня» или «🗓 Неделя», чтобы посмотреть актуальные пары."
                        for uid in users:
                            try:
                                await bot.send_message(uid,msg,parse_mode='HTML')
                                await asyncio.sleep(0.05)
                            except Exception: pass

                # 2. Напоминания по времени пользователя
                now=data_manager.now()
                cur_hm=now.strftime('%H:%M')
                if last_sent_hm!=cur_hm:
                    last_sent_hm=cur_hm
                    time_users=data_manager.get_users_for_time(cur_hm)
                    if time_users:
                        is_evening=cur_hm>='12:00'
                        target_day=(now+timedelta(days=1)).date() if is_evening else now.date()
                        if target_day.weekday()<=4:
                            day_prefix="на завтра" if is_evening else "на сегодня"
                            for uid,target in time_users:
                                try:
                                    if data_manager.is_teacher_target(target):
                                        t_name=data_manager.target_name(target)
                                        lessons=data_manager.get_teacher_schedule_for_day(t_name,target_day)
                                        text=f"🔔 <b>Расписание {day_prefix} ({ui.DAYS[target_day.weekday()]}, {target_day:%d.%m}):</b>\n\n"+ui.format_day_schedule(target_day,lessons,data_manager.get_academic_week(target_day),is_teacher=True,target_name=t_name)
                                    else:
                                        lessons=data_manager.get_schedule_for_day(target,target_day)
                                        text=f"🔔 <b>Расписание {day_prefix} ({ui.DAYS[target_day.weekday()]}, {target_day:%d.%m}):</b>\n👥 <b>{ui.safe(target)}</b>\n\n"+ui.format_day_schedule(target_day,lessons,data_manager.get_academic_week(target_day))
                                    await bot.send_message(uid,text,parse_mode='HTML',reply_markup=keyboards.get_main_keyboard())
                                    await asyncio.sleep(0.05)
                                except Exception: pass
            except asyncio.CancelledError: break
            except Exception as exc:
                logging.getLogger(__name__).warning('Фоновый планировщик: %s',exc)

    bg_task=asyncio.create_task(background_worker())
    try:
        await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types(),close_bot_session=False)
    finally:
        bg_task.cancel()
        await bot.session.close()

class SafeFormatter(logging.Formatter):
    def format(self,record):
        return config.redact(super().format(record))

def main():
    formatter=SafeFormatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler=logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handlers=[handler]
    if '--check' not in sys.argv:
        file_handler=RotatingFileHandler(
            config.BASE_DIR/'bot.log',
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    logging.basicConfig(level=logging.INFO,handlers=handlers,force=True)
    try:
        if '--check' in sys.argv:
            data_manager._check_reload(force=True)
            print(f'OK: {len(data_manager.get_groups())} групп; первая неделя с {config.WEEK1_MONDAY}; единый JSON: {config.SCHEDULE_PATH}')
            return 0
        if not config.BOT_TOKEN: raise ValueError('Создайте .env по образцу .env.example и вставьте новый токен от BotFather.')
        asyncio.run(run_bot()); return 0
    except KeyboardInterrupt: return 0
    except Exception:
        logging.getLogger(__name__).exception('Не удалось запустить или продолжить работу бота.')
        return 1
if __name__=='__main__': raise SystemExit(main())
