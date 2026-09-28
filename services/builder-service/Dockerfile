FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY proto ./proto
COPY services/builder-service/app ./app
RUN uv run --no-sync python -m grpc_tools.protoc -Iproto \
    --python_out=/app --grpc_python_out=/app proto/file_service.proto
CMD ["uv", "run", "--no-sync", "python", "-m", "app.network"]
