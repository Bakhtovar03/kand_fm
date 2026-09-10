import logging
import json
import re

import httpx
from aiogram import Bot
from bs4 import BeautifulSoup

from utils import format_bank_rates_for_client, split_text_for_telegram


NBT_URL = "https://www.nbt.tj/en/kurs/kurs_kommer_bank.php"
CURRENCIES = ("USD", "EUR", "RUB")
LAST_RATE_MESSAGE_IDS_KEY = "exchange_rate:last_message_ids"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


def clean_float(value: str) -> float | None:
    # НБТ иногда ставит "---" или пустые значения, их превращаем в None.
    value = value.strip()
    if not value or set(value) <= {"-"}:
        return None

    # Оставляем только цифры и десятичный разделитель, запятую приводим к точке.
    cleaned = re.sub(r"[^\d.,]", "", value).replace(",", ".")
    return float(cleaned) if cleaned else None


def fetch_nbt_currency_rows(client: httpx.Client, currency: str) -> list[dict]:
    # Загружаем страницу НБТ для одной валюты: USD, EUR или RUB.
    response = client.get(NBT_URL, params={"currency": currency})
    response.raise_for_status()

    # Разбираем HTML и ищем основную таблицу с курсами коммерческих банков.
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    # По заголовкам определяем индексы нужных колонок.
    header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
    indexes = {
        "cash_buy": header.index("Cash Buy"),
        "cash_sell": header.index("Cash Sell"),
        "transfer_buy": header.index("Non-Cash Buy"),
        "transfer_sell": header.index("Non-Cash Sell"),
        "date": header.index("Date"),
    }

    parsed_rows = []
    for row in rows[1:]:
        # Каждая строка таблицы соответствует одному банку.
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) <= max(indexes.values()):
            continue

        parsed_rows.append(
            {
                "bank_name": cells[0],
                "cash": {
                    "buy": clean_float(cells[indexes["cash_buy"]]),
                    "sell": clean_float(cells[indexes["cash_sell"]]),
                },
                "transfer": {
                    "buy": clean_float(cells[indexes["transfer_buy"]]),
                    "sell": clean_float(cells[indexes["transfer_sell"]]),
                },
                "updated_at": cells[indexes["date"]],
            }
        )

    return parsed_rows


def collect_bank_rates() -> dict:
    result: dict[str, dict] = {}

    # Один HTTP-клиент переиспользуется для всех трех валют.
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True, verify=False) as client:
        for currency in CURRENCIES:
            rows = fetch_nbt_currency_rows(client, currency)

            for row in rows:
                # При первом появлении создаем банк, затем дополняем его валютами.
                bank = result.setdefault(
                    row["bank_name"],
                    {
                        "rates": {},
                        "source": NBT_URL,
                    },
                )

                bank["rates"][currency] = {
                    "cash": row["cash"],
                    "transfer": row["transfer"],
                }
                bank["updated_at"] = row["updated_at"]

    return result


async def sync_rate(redis_client) -> None:
    # Задача расписания: собрать курсы, отформатировать и сохранить в Redis.
    rates_data = collect_bank_rates()
    rates_text = format_bank_rates_for_client(rates_data)
    await redis_client.hset("exchange_rate", "rate", rates_text)
    logging.info("Exchange rates were synced to Redis")


async def send_rate(bot: Bot, channel_id: int, redis_client) -> None:
    # Задача расписания: взять готовый текст из Redis и отправить его в канал.
    rate = await redis_client.hget("exchange_rate", "rate")
    if not rate:
        logging.warning("Exchange rates were not found in Redis, nothing to send")
        return

    try:
        sent_messages = []
        for message_part in split_text_for_telegram(rate):
            sent_message = await bot.send_message(
                chat_id=channel_id,
                text=message_part,
                parse_mode="HTML",
            )
            sent_messages.append(sent_message)

        previous_message_ids_raw = await redis_client.get(LAST_RATE_MESSAGE_IDS_KEY)
        if previous_message_ids_raw:
            try:
                previous_message_ids = json.loads(previous_message_ids_raw)
            except json.JSONDecodeError:
                previous_message_ids = []
                logging.warning("Stored exchange rate message ids are corrupted")

            for message_id in previous_message_ids:
                try:
                    await bot.delete_message(chat_id=channel_id, message_id=int(message_id))
                except Exception as exc:
                    logging.warning(f"Failed to delete previous exchange rates message {message_id}: {exc}")

        await redis_client.set(
            LAST_RATE_MESSAGE_IDS_KEY,
            json.dumps([message.message_id for message in sent_messages]),
        )
        logging.info("Scheduled exchange rates message was sent")
    except Exception as exc:
        logging.error(f"Scheduled exchange rates sending failed: {exc}")


if __name__ == "__main__":
    print(format_bank_rates_for_client(collect_bank_rates()))
