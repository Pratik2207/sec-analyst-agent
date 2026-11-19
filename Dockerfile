# One image for the api (default CMD) and the Streamlit ui (compose overrides the command).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MODEL_CACHE_DIR=/app/data/models \
    HF_HOME=/app/data/models/hf

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first, so this layer is reused until pyproject.toml/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY config/ config/
COPY sql/ sql/
COPY src/ src/
COPY ui/ ui/
RUN mkdir -p /app/data/models && chown -R app:app /app/data

USER app
EXPOSE 8000 8501
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
