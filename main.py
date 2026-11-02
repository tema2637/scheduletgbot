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

    async def send_chunks(message,text,keyboard=None):
        parts=ui.split_messages(text)
        for i,part in enumerate(parts):
            await message.answer(part,parse_mode='HTML',reply_markup=keyboard if i==len(parts)-1 else None)
    async def choose(message):
        await message.answer('Выберите специальность:',reply_markup=keyboards.get_group_prefixes_keyboard())

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
            elif isinstance(exc,UnknownGroup): text='Группа не найдена. Откройте настройки и выберите её заново.'
            elif isinstance(exc,TelegramRetryAfter): text='Telegram ограничил отправку. Попробуйте чуть позже.'
            else: text='Не удалось выполнить действие. Попробуйте позже. Ошибка не означает, что занятий нет.'
            try: await message.answer(text)
            except Exception: logger.warning('Не удалось отправить уведомление об ошибке.')
        return True

    @dp.message(Command('start','menu'))
    async def start(message:types.Message):
        if not message.from_user: return
        parts=(message.text or '').split(maxsplit=1)
        if len(parts)==2 and parts[1]=='select_group':
            if not await subscription.is_subscribed(message.from_user.id):
                return await message.answer(subscription.sub_text(),parse_mode='HTML',reply_markup=subscription.subscribe_keyboard())
            return await choose(message)
        group=data_manager.get_user_group(message.from_user.id)
        if group:
            await message.answer('👋 «Опять пары»\nГруппа: <b>'+ui.safe(group)+'</b>',reply_markup=keyboards.get_main_keyboard())
        else:
            if not await subscription.is_subscribed(message.from_user.id):
                await message.answer(subscription.sub_text(),parse_mode='HTML',reply_markup=subscription.subscribe_keyboard())
                return
            await message.answer('👋 Привет! Выберите свою группу.')
            await choose(message)

    async def show_day(event,target):
        callback=isinstance(event,types.CallbackQuery)
        message=event.message if callback else event
        if not isinstance(message,types.Message) or not event.from_user: return
        group=data_manager.get_user_group(event.from_user.id)
        if not group: return await choose(message)
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
    async def today(message:types.Message): await show_day(message,data_manager.now())
    @dp.message(F.text=='⏭ Завтра')
    async def tomorrow(message:types.Message): await show_day(message,data_manager.now()+timedelta(days=1))
    async def show_week(message,following=False):
        if not message.from_user: return
        group=data_manager.get_user_group(message.from_user.id)
        if not group: return await choose(message)
        now=data_manager.now(); monday=now-timedelta(days=now.weekday())+timedelta(weeks=int(following))
        await send_chunks(message,data_manager.get_week_text(group,monday),keyboards.get_main_keyboard())
    @dp.message(F.text=='🗓 Неделя')
    async def week(message:types.Message): await show_week(message)
    @dp.message(F.text=='📆 След. неделя')
    async def next_week(message:types.Message): await show_week(message,True)
    @dp.message(F.text=='⚙️ Настройки')
    async def settings(message:types.Message): await choose(message)

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
        if isinstance(callback.message,types.Message): await choose(callback.message)
    @dp.callback_query(F.data.startswith('group:'))
    async def pick_group(callback:types.CallbackQuery):
        await callback.answer()
        if not isinstance(callback.message,types.Message): return
        wanted=(callback.data or '').removeprefix('group:')
        group=next((g for g in data_manager.get_groups() if keyboards.group_id(g)==wanted),None)
        if not group: raise UnknownGroup('Группа не найдена.')
        data_manager.save_user_group(callback.from_user.id,group)
        await callback.message.edit_text('✅ Группа: <b>'+ui.safe(group)+'</b>',parse_mode='HTML')
        await callback.message.answer('Расписание доступно через кнопки 👇',reply_markup=keyboards.get_main_keyboard())
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
    @dp.message(Command('help'))
    async def help_command(message:types.Message):
        await message.answer('Выберите группу в /start. Inline: @имя_бота сегодня / завтра / неделя / следующая неделя. Если inline не включён, используйте /setinline в BotFather.',reply_markup=keyboards.get_main_keyboard())
    @dp.message()
    async def unknown(message:types.Message): await message.answer('Используйте меню или /help.',reply_markup=keyboards.get_main_keyboard())
    try:
        await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types(),close_bot_session=False)
    finally: await bot.session.close()

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
