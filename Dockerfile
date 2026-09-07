FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /app

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && python -m venv "$VIRTUAL_ENV"

COPY requirements.txt ./
RUN pip install --no-compile --retries 10 --timeout 120 --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY --chown=appuser:appuser config.py main.py sync_script.py utils.py ./
COPY --chown=appuser:appuser handlers ./handlers
COPY --chown=appuser:appuser keyboards ./keyboards
COPY --chown=appuser:appuser lexicon ./lexicon

USER appuser

CMD ["python", "main.py"]
