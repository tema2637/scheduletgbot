"""Гейт подписки на канал. Подключается в main.py через init() + middleware.

Проверка отключается пустым CHANNEL или REQUIRE_SUBSCRIPTION=false.
Результаты кэшируются: положительные и отрицательные.
"""
import html
import logging
import time
from aiogram import types
from aiogram.dispatcher.middlewares.base import BaseMiddleware
import config

_logger = logging.getLogger(__name__)
_BOT = None
_CHANNEL_ID = ''
_ENABLED = False
_CACHE = {}  # user_id -> (expires_ts, bool)
_CACHE_TTL = config.SUBSCRIPTION_CACHE_TTL
_NEGATIVE_TTL = config.SUBSCRIPTION_NEGATIVE_TTL
_CACHE_LIMIT = 10000


def init(bot, channel, require=None):
    global _BOT, _CHANNEL_ID, _ENABLED
    _BOT = bot
    ch = (channel or '').strip()
    if ch and not ch.startswith('@') and not ch.lstrip('-').isdigit():
        ch = '@' + ch
    _CHANNEL_ID = ch
    enabled = config.REQUIRE_SUBSCRIPTION if require is None else bool(require)
    _ENABLED = bool(enabled and ch)
    _CACHE.clear()
    _logger.info('subscription init: channel=%r enabled=%s', _CHANNEL_ID, _ENABLED)


def channel_username():
    return _CHANNEL_ID[1:] if _CHANNEL_ID.startswith('@') else ''


def channel_url():
    override = config.CHANNEL_URL.strip()
    if override.startswith(('https://', 'http://')):
        return override
    if channel_username():
        return 'https://t.me/' + channel_username()
    return ''


def sub_text():
    url = channel_url()
    if url:
        link = '<a href="' + html.escape(url, quote=True) + '">' + html.escape(
            channel_username() or url, quote=False
        ) + '</a>'
        return ('👋 <b>Добро пожаловать!</b>\n\n'
                'Чтобы пользоваться ботом, подпишитесь на наш канал:\n'
                '🔗 ' + link + '\n\n'
                'После подписки нажмите <b>«Я подписался»</b>.')
    return ('👋 <b>Добро пожаловать!</b>\n\n'
            'Чтобы пользоваться ботом, подпишитесь на наш канал.\n'
            'Ссылку на канал можно получить у администратора.\n\n'
            'После подписки нажмите <b>«Я подписался»</b>.')


def subscribe_keyboard():
    url = channel_url()
    buttons = []
    if url:
        buttons.append(types.InlineKeyboardButton(text='📢 Открыть канал', url=url))
    buttons.append(types.InlineKeyboardButton(text='✅ Я подписался', callback_data='sub:check'))
    return types.InlineKeyboardMarkup(inline_keyboard=[buttons])


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


def _prune():
    if len(_CACHE) <= _CACHE_LIMIT:
        return
    now = time.time()
    for user_id, (expires, _) in list(_CACHE.items()):
        if expires <= now:
            _CACHE.pop(user_id, None)
    if len(_CACHE) > _CACHE_LIMIT:
        _CACHE.clear()


def _store(user_id, ok):
    ttl = _CACHE_TTL if ok else _NEGATIVE_TTL
    if ttl > 0:
        _CACHE[user_id] = (time.time() + ttl, ok)
    else:
        _CACHE.pop(user_id, None)
    _prune()


async def is_subscribed(user_id, force=False):
    if not _ENABLED:
        return True
    bot = _BOT
    if bot is None:
        return not config.REQUIRE_SUBSCRIPTION
    if not force:
        cached = _CACHE.get(user_id)
        if cached and cached[0] > time.time():
            return cached[1]
    try:
        member = await bot.get_chat_member(_CHANNEL_ID, user_id)
        ok = member.status in ('member', 'administrator', 'creator')
        if member.status == 'restricted':
            ok = bool(getattr(member, 'is_member', False))
        _store(user_id, ok)
        _logger.info('sub check: user=%s channel=%s status=%s -> %s',
                     user_id, _CHANNEL_ID, member.status, ok)
        return ok
    except Exception as exc:
        text = str(exc).lower()
        if any(v in text for v in ('user not found', 'user is not a participant',
                                   'chat admin required', 'participant_id_invalid')):
            _store(user_id, False)
            _logger.warning('sub check: user=%s НЕ подписан (tg: %s)', user_id, text)
            return False
        _logger.error('sub check: user=%s ошибка проверки подписки: %s',
                      user_id, exc, exc_info=True)
        # Сетевой сбой не должен полностью останавливать бота. Политика
        # настраивается: fail-open по умолчанию, fail-closed через .env.
        if config.SUBSCRIPTION_FAIL_OPEN:
            _store(user_id, True)
            return True
        return False


async def check_configuration():
    """Проверяет, что бот видит канал и является его администратором."""
    if not _ENABLED:
        return True
    if _BOT is None:
        return False
    try:
        me = await _BOT.get_me()
        member = await _BOT.get_chat_member(_CHANNEL_ID, me.id)
    except Exception:
        _logger.exception('Не удалось проверить канал %s', _CHANNEL_ID)
        return False
    ok = member.status in ('administrator', 'creator')
    if not ok:
        _logger.error(
            'Бот не администратор канала %s (status=%s). '
            'Добавьте бота администратором или отключите проверку подписки.',
            _CHANNEL_ID, member.status,
        )
    return ok


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
            url = channel_url()
            button = (types.InlineQueryResultsButton(text='Подпишитесь на канал', url=url)
                      if url else
                      types.InlineQueryResultsButton(text='Открыть бота', start_parameter='select_group'))
            await event.answer([], button=button, cache_time=1, is_personal=True)
        except Exception:
            pass
    else:
        _logger.warning('sub block: неподдерживаемый тип апдейта %r', type(event).__name__)


class SubscriptionMiddleware(BaseMiddleware):
    """Проверяет подписку на каждый апдейт. Отписался — блокирует."""

    async def __call__(self, handler, event, data):
        if not _ENABLED:
            return await handler(event, data)
        inner = _normalize(event)
        user_id = _user_id(inner)
        if user_id is None:
            _logger.warning('sub middleware: нет user_id в %r — пропускаем',
                            type(event).__name__)
            return await handler(event, data)
        if isinstance(inner, types.CallbackQuery) and inner.data == 'sub:check':
            return await handler(event, data)
        if isinstance(inner, types.Message) and inner.chat.type in ('group', 'supergroup'):
            return await handler(event, data)
        if isinstance(inner, types.CallbackQuery) and inner.message and inner.message.chat.type in ('group', 'supergroup'):
            return await handler(event, data)
        if await is_subscribed(user_id):
            return await handler(event, data)
        _logger.info('sub middleware: блокирую user=%s (%s)',
                     user_id, type(inner).__name__)
        await _block(inner)
        return False
