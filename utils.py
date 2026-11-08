import re
from html import escape

SAFE_TELEGRAM_MESSAGE_LIMIT = 3900

# Фильтр банков, которые нужно показывать клиенту.

TARGET_BANK_ALIASES = (
    "spitamen",
    "imon",
    "humo",
    "eskhata",
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


def format_bank_rates_for_client(data: dict) -> str:
    # Собираем список строк, потом объединяем их в один HTML-текст для Telegram.
    lines = []
    for bank_name, bank_data in data.items():
        if not should_show_bank(bank_name):
            continue

        # Флаг США (US): региональные символы \U0001F1FA и \U0001F1F8
        flag_us = "\U0001F1FA\U0001F1F8"

        # Флаг России (RU): региональные символы \U0001F1F7
        flag_ru = "\U0001F1F7\U0001F1FA"
        flag_eu = "\U0001F1EA\U0001F1FA"

        # Наличные деньги (Пачка долларов с крылышками): код \U0001F4B8
        emoji_cash_wings = "\U0001F4B8"

        # Банковская карта (Кредитная карта): символ \u200D не нужен, код: \U0001F4B3
        emoji_card = "\U0001F4B3"


        rates = bank_data.get("rates", {})

        # Название банка выделяем жирным через HTML-тег <b>.
        # Шаблон: ищет открывающую кавычку, затем любые символы внутри, затем закрывающую
        match = re.search(r'"([^"]*)"', bank_name)
        display_name = match.group(1) if match else bank_name
        lines.append(f"<b>{escape(display_name[:200])}</b>")



        # Если по банку нет курсов, показываем понятное сообщение и идем дальше.
        if not rates:
            lines.append("маълумот муваққатан дастнорас аст")
            lines.append("")
            continue

        # Для каждой валюты выводим отдельно наличный и переводной курс.
        for currency, currency_data in rates.items():
            cash = currency_data.get("cash", {})
            transfer = currency_data.get("transfer", {})

            def scaled(value, factor):
                return f"{value * factor:.2f}" if value is not None else "-"

            if currency == "RUB":
                lines.append(f"Рубли Русия {currency}{flag_ru}:")
                # Добавляем:.2f внутрь фигурных скобок после математического действия
                lines.append(f"  Нақдӣ:{emoji_cash_wings} харид {scaled(cash.get('buy'), 1000)}, фурӯш {scaled(cash.get('sell'), 1000)}")
                lines.append(f"  Интиқол:{emoji_card} харид {scaled(transfer.get('buy'), 1000)}, фурӯш {scaled(transfer.get('sell'), 1000)}")

            elif currency in ("USD", "EUR"):
                label = f"Доллари Амрико USD{flag_us}" if currency == "USD" else f"Евро EUR{flag_eu}"
                lines.append(f"{label}:")
                lines.append(f"  Нақдӣ:{emoji_cash_wings} харид {scaled(cash.get('buy'), 100)}, фурӯш {scaled(cash.get('sell'), 100)}")
                lines.append(f"  Интиқол:{emoji_card} харид {scaled(transfer.get('buy'), 100)}, фурӯш {scaled(transfer.get('sell'), 100)}")

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
