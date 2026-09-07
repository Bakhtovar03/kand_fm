import asyncio
import logging
import os

import redis.asyncio as redis
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import load_config
from handlers.user import user_router
from sync_script import send_rate, sync_rate


logger = logging.getLogger(__name__)


async def main():
    # Redis хранит FSM-состояния aiogram и готовый текст с курсами валют.
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True, db=0)
    storage = RedisStorage(redis_client)

    config = load_config()
    logging.basicConfig(level=config.log.level, format=config.log.format)


    dp = Dispatcher(storage=storage)
    dp.include_router(user_router)


    bot = Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Redis-клиент в bot, чтобы handlers могли подключится к redis.
    setattr(bot, "redis_client", redis_client)

    # APScheduler запускает фоновые задачи в том же asyncio loop, что и aiogram.
    scheduler = AsyncIOScheduler(timezone="Asia/Dushanbe")

    # В 07:40 обновляем курсы и сохраняем готовый текст в Redis.
    scheduler.add_job(
        sync_rate,
        "cron",
        hour=23,
        minute=40,
        args=[redis_client],
        id="sync_exchange_rates",
        replace_existing=True,
    )

    # В 08:00 отправляем сохраненный текст в канал, если CHANNEL_ID задан в .env.
    if config.bot.channel_id is not None:
        scheduler.add_job(
            send_rate,
            "cron",
            hour=23,
            minute=40,
            args=[bot, config.bot.channel_id, redis_client],
            id="send_exchange_rates",
            replace_existing=True,
        )
    else:
        logger.warning("CHANNEL_ID is not set, scheduled sending is disabled")

    scheduler.start()
    await dp.start_polling(bot)


#  python main.py
if __name__ == "__main__":
    asyncio.run(main())
