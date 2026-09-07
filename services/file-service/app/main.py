import asyncio

import grpc

from file_service_pb2_grpc import add_FileServiceServicer_to_server

from .minio_storage import MinioStorage
from .service import FileService


async def serve() -> None:
    """Запустить gRPC сервер"""
    await MinioStorage.ensure_bucket()

    server = grpc.aio.server()
    add_FileServiceServicer_to_server(FileService(), server)
    server.add_insecure_port("[::]:50051")
    await server.start()
    print("File service gRPC server started on port 50051")
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())