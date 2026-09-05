import logging

from aiogram import Bot
import re

SAFE_TELEGRAM_MESSAGE_LIMIT = 3900

# Фильтр банков, которые нужно показывать клиенту.

TARGET_BANK_ALIASES = (
    "vasl",
    "spitamen",
    "imon",
    "humo",
    "eskhata",
    "arvand",
    "amonatbonk",
    "alif",
)


def normalize_bank_name(value: str) -> str:
    # Приводим название к нижнему регистру, чтобы Alif/alif/ALIF сравнивались одинаково.
    return value.casefold()


def should_show_bank(bank_name: str) -> bool:
    # Реальные названия из НБТ длинные: OJSC "Alif Bank", LLC MDO "Humo" и т.д.
    # Поэтому проверяем не полное совпадение, а наличие короткого alias внутри названия.
    normalized_name = normalize_bank_name(bank_name)
    return any(alias in normalized_name for alias in TARGET_BANK_ALIASES)


def format_rate_value(value: float | int | str | None) -> str:
    # Если в таблице НБТ пустое значение, показываем клиенту прочерк.
    if value is None:
        return "-"

    # Строки возвращаем как есть, чтобы не сломать уже готовый текст.
    if isinstance(value, str):
        return value

    # Формат :g убирает лишние нули после точки, например 9.2200 -> 9.22.
    return f"{value:g}"


def format_bank_rates_for_client(data: dict) -> str:
    # Собираем список строк, потом объединяем их в один HTML-текст для Telegram.
    lines = []

    for bank_name, bank_data in data.items():
        if not should_show_bank(bank_name):
            continue

        rates = bank_data.get("rates", {})
        updated_at = bank_data.get("updated_at")

        # Название банка выделяем жирным через HTML-тег <b>.
        # Шаблон: ищет открывающую кавычку, затем любые символы внутри, затем закрывающую
        match = re.search(r'"([^"]*)"', bank_name)
        lines.append(f"<b>{match.group(1)}</b>")

        if updated_at:
            lines.append(f"Обновлено: {updated_at}")

        # Если по банку нет курсов, показываем понятное сообщение и идем дальше.
        if not rates:
            lines.append("Курсы валют не найдены")
            lines.append("")
            continue

        # Для каждой валюты выводим отдельно наличный и переводной курс.
        for currency, currency_data in rates.items():
            cash = currency_data.get("cash", {})
            transfer = currency_data.get("transfer", {})

            cash_buy = format_rate_value(cash.get("buy"))
            cash_sell = format_rate_value(cash.get("sell"))
            transfer_buy = format_rate_value(transfer.get("buy"))
            transfer_sell = format_rate_value(transfer.get("sell"))

            lines.append(f"{currency}:")
            lines.append(f"  Наличные: покупка {cash_buy}, продажа {cash_sell}")
            lines.append(f"  Переводы: покупка {transfer_buy}, продажа {transfer_sell}")

        # Пустая строка визуально отделяет банки друг от друга.
        lines.append("")

    return "\n".join(lines).strip()


def split_text_for_telegram(text: str, limit: int = SAFE_TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    # Telegram принимает максимум 4096 символов, поэтому используем запасной лимит 3900.
    if len(text) <= limit:
        return [text]

    parts = []
    current_lines = []
    current_length = 0

    for line in text.splitlines():
        line_length = len(line) + 1

        # Если следующая строка переполнит сообщение, закрываем текущую часть.
        if current_lines and current_length + line_length > limit:
            parts.append("\n".join(current_lines))
            current_lines = []
            current_length = 0

        # Очень длинную строку режем принудительно, иначе Telegram ее не примет.
        if line_length > limit:
            for start in range(0, len(line), limit):
                chunk = line[start:start + limit]
                if current_lines:
                    parts.append("\n".join(current_lines))
                    current_lines = []
                    current_length = 0
                parts.append(chunk)
            continue

        current_lines.append(line)
        current_length += line_length

    # Добавляем последнюю накопленную часть, если она не пустая.
    if current_lines:
        parts.append("\n".join(current_lines))

    return parts


async def send_scheduled_message(bot: Bot, chat_id: int, text: str):
    # Отправляем длинный текст несколькими Telegram-сообщениями.
    for message_part in split_text_for_telegram(text):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message_part,
                parse_mode="HTML",
            )
            logging.info("Scheduled message was sent")
        except Exception as exc:
            logging.error(f"Scheduled message sending failed: {exc}")
