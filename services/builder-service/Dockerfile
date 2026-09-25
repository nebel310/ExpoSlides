FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY proto ./proto
COPY services/builder-service/app ./app

RUN uv run python -m grpc_tools.protoc \
    -Iproto \
    --python_out=/app \
    --grpc_python_out=/app \
    proto/file_service.proto

CMD ["uv", "run", "python", "-m", "app.network"]