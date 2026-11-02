import asyncio

try:
    from aiogram.exceptions import TelegramNetworkError
except Exception:  # pragma: no cover - зависит от версии aiogram
    TelegramNetworkError = ()


async def retry_request(send, bot, method, exception_type, attempts=3, max_wait=60, sleep=asyncio.sleep):
    for attempt in range(attempts + 1):
        try:
            return await send(bot, method)
        except exception_type as exc:
            delay = float(getattr(exc, 'retry_after', 0))
            if attempt >= attempts or not 0 <= delay <= max_wait:
                raise
            await sleep(delay)
        except TelegramNetworkError:
            if attempt >= attempts:
                raise
            delay = min(float(2 ** attempt), float(max_wait))
            await sleep(delay)


class RetryRequestMiddleware:
    async def __call__(self, make_request, bot, method):
        from aiogram.exceptions import TelegramRetryAfter
        return await retry_request(make_request, bot, method, TelegramRetryAfter)
