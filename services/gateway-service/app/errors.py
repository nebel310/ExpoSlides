class GatewayError(RuntimeError):
    """Базовая ошибка gateway-service"""


class SessionNotFoundError(GatewayError):
    """Сессия не найдена или истекла"""


class TaskNotFoundError(GatewayError):
    """Задача не найдена"""


class FileServiceError(GatewayError):
    """Ошибка взаимодействия с file-service"""


class KafkaPublishError(GatewayError):
    """Ошибка публикации в Kafka"""