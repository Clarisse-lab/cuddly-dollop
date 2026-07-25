FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY plugins/govdata-transparencia ./plugins/govdata-transparencia
COPY plugins/govdata-pncp ./plugins/govdata-pncp
COPY plugins/govdata-transferegov ./plugins/govdata-transferegov

RUN python -m pip install ".[api,postgres]" \
    && python -m pip install ./plugins/govdata-transparencia \
    && python -m pip install ./plugins/govdata-pncp \
    && python -m pip install ./plugins/govdata-transferegov

EXPOSE 8000

CMD ["govdata-api"]
