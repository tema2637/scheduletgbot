"""Гейт подписки на канал. Подключается в main.py через init() + middleware.

Использование:
    import subscription
    subscription.init(bot, config.CHANNEL)
    dp.update.middleware(subscription.SubscriptionMiddleware())
"""
import logging
import time
from aiogram import types
from aiogram.dispatcher.middlewares.base import BaseMiddleware

_logger = logging.getLogger(__name__)
_BOT = None
_CHANNEL_ID = ''
_CACHE = {}          # user_id -> (expires_ts, True); кэшируем только подписку
_CACHE_TTL = 0.0     # сек: 0 = проверяем при КАЖДОМ действии, отписка видна мгновенно


def init(bot, channel):
    global _BOT, _CHANNEL_ID
    _BOT = bot
    ch = (channel or '').strip()
    if ch and not ch.startswith('@') and not ch.lstrip('-').isdigit():
        ch = '@' + ch
    _CHANNEL_ID = ch
    _logger.info('subscription init: channel=%r', _CHANNEL_ID)


def channel_username():
    return _CHANNEL_ID[1:] if _CHANNEL_ID.startswith('@') else _CHANNEL_ID


def channel_url():
    return 'https://t.me/' + channel_username()


def sub_text():
    return ('👋 <b>Добро пожаловать!</b>\n\n'
            'Чтобы пользоваться ботом, подпишитесь на наш канал:\n'
            '🔗 <a href="' + channel_url() + '">t.me/' + channel_username() + '</a>\n\n'
            'После подписки нажмите <b>«Я подписался»</b>.')


def subscribe_keyboard():
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text='📢 Открыть канал', url=channel_url()),
        types.InlineKeyboardButton(text='✅ Я подписался', callback_data='sub:check'),
    ]])


def _normalize(event):
    """dp.update.middleware отдаёт Update — достаём внутренний объект."""
    if isinstance(event, types.Update):
        for attr in ('message', 'edited_message', 'channel_post',
                     'callback_query', 'inline_query'):
            obj = getattr(event, attr, None)
            if obj is not None:
                return obj
    return event


def _user_id(event):
    obj = getattr(event, 'from_user', None)
    if obj is not None:
        return getattr(obj, 'id', None)
    msg = getattr(event, 'message', None)
    if msg is not None and getattr(msg, 'from_user', None) is not None:
        return msg.from_user.id
    return None


async def is_subscribed(user_id):
    if not _CHANNEL_ID:
        return True
    bot = _BOT
    if bot is None:
        return True
    cached = _CACHE.get(user_id)
    if cached and cached[0] > time.time():
        _logger.debug('sub check: user=%s OK (cache)', user_id)
        return True
    try:
        member = await bot.get_chat_member(_CHANNEL_ID, user_id)
        ok = member.status not in ('left', 'kicked')
        if ok:
            _CACHE[user_id] = (time.time() + _CACHE_TTL, True)
        else:
            _CACHE.pop(user_id, None)
        _logger.info('sub check: user=%s channel=%s status=%s -> %s',
                     user_id, _CHANNEL_ID, member.status, ok)
        return ok
    except Exception as exc:  # бот не админ / канал недоступен
        text = str(exc).lower()
        if any(v in text for v in ('user not found', 'user is not a participant',
                                   'chat admin required')):
            _CACHE.pop(user_id, None)
            _logger.warning('sub check: user=%s НЕ подписан (tg: %s)', user_id, text)
            return False
        _logger.error('sub check: user=%s ошибка проверки подписки: %s',
                      user_id, exc, exc_info=True)
        return True


async def _block(event):
    if isinstance(event, types.Message):
        _logger.info('sub block: сообщение от user=%s', getattr(getattr(event, 'from_user', None), 'id', None))
        await event.answer(sub_text(), parse_mode='HTML', reply_markup=subscribe_keyboard())
    elif isinstance(event, types.CallbackQuery):
        _logger.info('sub block: callback от user=%s', getattr(getattr(event, 'from_user', None), 'id', None))
        try:
            await event.answer('Вы не подписаны на канал.', show_alert=True)
        except Exception:
            pass
        msg = event.message
        if isinstance(msg, types.Message):
            try:
                await msg.edit_text(sub_text(), parse_mode='HTML', reply_markup=subscribe_keyboard())
            except Exception:
                pass
    elif isinstance(event, types.InlineQuery):
        try:
            await event.answer([], button=types.InlineQueryResultsButton(
                text='Подпишитесь на канал', url=channel_url()), cache_time=1, is_personal=True)
        except Exception:
            pass
    else:
        _logger.warning('sub block: неподдерживаемый тип апдейта %r', type(event).__name__)


class SubscriptionMiddleware(BaseMiddleware):
    """Проверяет подписку на каждый апдейт. Отписался — блокирует.

    ВАЖНО: event здесь — объект Update. Его НЕЛЬЗЯ заменять на внутренний
    объект при передаче в handler: dispatcher._listen_update читает
    update.event_type у оригинала. Внутренний объект достаём только
    для проверки user_id и блокировки.
    """

    async def __call__(self, handler, event, data):
        if not _CHANNEL_ID:
            return await handler(event, data)
        inner = _normalize(event)
        user_id = _user_id(inner)
        if user_id is None:
            _logger.warning('sub middleware: нет user_id в %r — пропускаем',
                            type(event).__name__)
            return await handler(event, data)
        # self-check кнопки «Я подписался» всегда пропускаем к хендлеру
        if isinstance(inner, types.CallbackQuery) and inner.data == 'sub:check':
            return await handler(event, data)
        if await is_subscribed(user_id):
            return await handler(event, data)
        _logger.info('sub middleware: блокирую user=%s (%s)',
                     user_id, type(inner).__name__)
        await _block(inner)
        return False  # хендлер не вызываем