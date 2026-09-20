FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY proto ./proto
COPY services/file-service/app ./app

RUN uv run python -m grpc_tools.protoc \
    -Iproto \
    --python_out=/app \
    --grpc_python_out=/app \
    proto/file_service.proto

EXPOSE 50051

CMD ["uv", "run", "python", "-m", "app.main"]