import asyncio
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
    # Удаляем пробелы по краям исходного значения курса.
    value = value.strip()
    # Проверяем, что значение пустое или состоит только из дефисов.
    if not value or set(value) <= {"-"}:
        # Для отсутствующего курса возвращаем None.
        return None

    # Оставляем только цифры и десятичный разделитель, запятую приводим к точке.
    cleaned = re.sub(r"[^\d.,]", "", value).replace(",", ".")
    # Преобразуем непустую строку в число; иначе возвращаем None.
    return float(cleaned) if cleaned else None


def fetch_nbt_currency_rows(client: httpx.Client, currency: str) -> list[dict]:
    # Загружаем страницу НБТ для одной валюты: USD, EUR или RUB.
    response = client.get(NBT_URL, params={"currency": currency})
    # Прерываем выполнение исключением при ошибочном HTTP-статусе ответа.
    response.raise_for_status()

    # Разбираем HTML и ищем основную таблицу с курсами коммерческих банков.
    soup = BeautifulSoup(response.text, "html.parser")
    # Берем первую таблицу на странице.
    table = soup.find("table")
    # Если таблица отсутствует, курсов для обработки нет.
    if table is None:
        return []

    # Получаем все строки найденной таблицы.
    rows = table.find_all("tr")
    # Пустая таблица также дает пустой результат.
    if not rows:
        return []

    # По заголовкам определяем индексы нужных колонок.
    header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
    # Сохраняем позиции колонок; index вызовет ValueError, если заголовка нет.
    indexes = {
        # Колонка покупки наличной валюты банком.
        "cash_buy": header.index("Cash Buy"),
        # Колонка продажи наличной валюты банком.
        "cash_sell": header.index("Cash Sell"),
        # Колонка покупки безналичной валюты банком.
        "transfer_buy": header.index("Non-Cash Buy"),
        # Колонка продажи безналичной валюты банком.
        "transfer_sell": header.index("Non-Cash Sell"),
    }

    # Здесь накапливаем словари с курсами отдельных банков.
    parsed_rows = []
    # Обрабатываем строки данных, пропуская первую строку с заголовками.
    for row in rows[1:]:
        # Каждая строка таблицы соответствует одному банку.
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        # Проверяем, хватает ли ячеек для всех нужных индексов.
        if len(cells) <= max(indexes.values()):
            # Неполную строку пропускаем, чтобы не получить IndexError.
            continue

        # Добавляем название банка и очищенные числовые значения курсов.
        parsed_rows.append(
            {
                # Название банка находится в первой ячейке строки.
                "bank_name": cells[0],
                # Курсы покупки и продажи наличной валюты.
                "cash": {
                    # Преобразуем значение покупки в float или None.
                    "buy": clean_float(cells[indexes["cash_buy"]]),
                    # Аналогично преобразуем значение продажи.
                    "sell": clean_float(cells[indexes["cash_sell"]]),
                },
                # Курсы покупки и продажи безналичной валюты.
                "transfer": {
                    # Преобразуем безналичный курс покупки.
                    "buy": clean_float(cells[indexes["transfer_buy"]]),
                    # Преобразуем безналичный курс продажи.
                    "sell": clean_float(cells[indexes["transfer_sell"]]),
                },
            }
        )

    # Возвращаем курсы всех найденных банков для запрошенной валюты.
    return parsed_rows


def collect_bank_rates() -> dict:
    # Создаем общий словарь: название банка -> его курсы и источник.
    result: dict[str, dict] = {}

    # Один HTTP-клиент переиспользуется для всех трех валют.
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True, verify=False) as client:
        # Последовательно запрашиваем USD, EUR и RUB.
        for currency in CURRENCIES:
            # Получаем список банков и их курсов для текущей валюты.
            rows = fetch_nbt_currency_rows(client, currency)

            # Переносим данные каждого банка в общий словарь.
            for row in rows:
                # При первом появлении создаем банк, затем дополняем его валютами.
                bank = result.setdefault(
                    # Название банка служит ключом общего словаря.
                    row["bank_name"],
                    {
                        # Для нового банка создаем пустой словарь валют.
                        "rates": {},
                        # Запоминаем адрес страницы, откуда получены данные.
                        "source": NBT_URL,
                    },
                )

                # Записываем курсы текущей валюты в данные этого банка.
                bank["rates"][currency] = {
                    # Сохраняем пару наличных курсов покупки и продажи.
                    "cash": row["cash"],
                    # Сохраняем пару безналичных курсов покупки и продажи.
                    "transfer": row["transfer"],
                }

    # Возвращаем данные банков после обработки всех валют.
    return result


async def sync_rate(redis_client) -> None:
    # Выполняем синхронные HTTP-запросы в отдельном потоке, не блокируя цикл asyncio.
    rates_data = await asyncio.to_thread(collect_bank_rates)
    # Превращаем словарь курсов в текст для пользователя.
    rates_text = format_bank_rates_for_client(rates_data)
    # Сохраняем текст в поле rate хеша exchange_rate в Redis.
    await redis_client.hset("exchange_rate", "rate", rates_text)
    # Записываем в журнал успешное обновление курсов.
    logging.info("Exchange rates were synced to Redis")


async def send_rate(bot: Bot, channel_id: int, redis_client) -> None:
    # Задача расписания: взять готовый текст из Redis и отправить его в канал.
    rate = await redis_client.hget("exchange_rate", "rate")
    # Проверяем, есть ли сохраненный текст курсов.
    if not rate:
        # Сообщаем в журнале, почему отправка не состоится.
        logging.warning("Exchange rates were not found in Redis, nothing to send")
        # Завершаем функцию без отправки сообщений.
        return

    # Перехватываем ошибки отправки и последующих операций с Redis.
    try:
        # Собираем отправленные сообщения, чтобы сохранить их идентификаторы.
        sent_messages = []
        # Разбиваем текст на части с помощью вспомогательной функции.
        for message_part in split_text_for_telegram(rate):
            # Отправляем очередную часть текста в Telegram.
            sent_message = await bot.send_message(
                # Указываем канал-получатель.
                chat_id=channel_id,
                # Передаем текущую часть текста курсов.
                text=message_part,
                # Включаем обработку HTML-разметки сообщения.
                parse_mode="HTML",
            )
            # Сохраняем объект отправленного сообщения.
            sent_messages.append(sent_message)

        # Читаем из Redis идентификаторы сообщений предыдущей публикации.
        previous_message_ids_raw = await redis_client.get(LAST_RATE_MESSAGE_IDS_KEY)
        # Удаление старой публикации нужно только при наличии сохраненных данных.
        if previous_message_ids_raw:
            # Пытаемся прочитать сохраненные идентификаторы из JSON.
            try:
                previous_message_ids = json.loads(previous_message_ids_raw)
            # При некорректном JSON продолжаем работу без удаления старых сообщений.
            except json.JSONDecodeError:
                previous_message_ids = []
                # Фиксируем повреждение сохраненных данных в журнале.
                logging.warning("Stored exchange rate message ids are corrupted")

            # Удаляем каждое сообщение предыдущей публикации.
            for message_id in previous_message_ids:
                # Ошибку удаления одного сообщения обрабатываем отдельно.
                try:
                    # Приводим идентификатор к целому числу и вызываем Telegram API.
                    await bot.delete_message(chat_id=channel_id, message_id=int(message_id))
                except Exception as exc:
                    # Записываем причину ошибки и продолжаем обработку остальных сообщений.
                    logging.warning(f"Failed to delete previous exchange rates message {message_id}: {exc}")

        # Запоминаем идентификаторы новой публикации для следующего обновления.
        await redis_client.set(
            # Используем постоянный ключ для списка последних сообщений.
            LAST_RATE_MESSAGE_IDS_KEY,
            # Извлекаем идентификаторы отправленных сообщений и сериализуем список в JSON.
            json.dumps([message.message_id for message in sent_messages]),
        )
        # Фиксируем успешное завершение публикации.
        logging.info("Scheduled exchange rates message was sent")
    except Exception as exc:
        # Записываем ошибку отправки или работы с Redis в журнал.
        logging.error(f"Scheduled exchange rates sending failed: {exc}")


# Этот блок выполняется только при прямом запуске файла, а не при импорте.
if __name__ == "__main__":
    # Собираем курсы, форматируем их и выводим текст в консоль.
    print(format_bank_rates_for_client(collect_bank_rates()))
