from dataclasses import dataclass
from typing import Optional

from environs import Env


@dataclass
class TgBot:
    token: str
    channel_id: Optional[int]


@dataclass
class LogSettings:
    level: str
    format: str


@dataclass
class Config:
    bot: TgBot
    log: LogSettings


def load_config(path: str | None = None) -> Config:
    env = Env()
    env.read_env(path)

    return Config(
        bot=TgBot(
            token=env("BOT_TOKEN"),
            channel_id=env.int("CHANNEL_ID", default=None),
        ),
        log=LogSettings(
            level=env("LOG_LEVEL"),
            format=env("LOG_FORMAT"),
        ),
    )
