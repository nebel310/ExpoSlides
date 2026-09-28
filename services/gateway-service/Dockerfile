FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY proto ./proto
COPY services/gateway-service/app ./app

RUN uv run python -m grpc_tools.protoc \
    -Iproto \
    --python_out=/app \
    --grpc_python_out=/app \
    proto/file_service.proto

EXPOSE 1000

CMD ["uv", "run", "uvicorn", "app.main:asgi_app", "--host", "0.0.0.0", "--port", "1000"]