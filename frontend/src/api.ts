export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

function serverMessage(data: unknown): string {
  if (!data || typeof data !== "object") return "Не удалось выполнить запрос.";
  const body = data as Record<string, unknown>;
  if (typeof body.error === "string") return body.error;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) return body.detail.map(item => {
    const value = item as { msg?: string; loc?: string[] };
    return `${value.loc?.slice(1).join(" · ") || "Данные"}: ${value.msg || "неверное значение"}`;
  }).join("; ");
  return "Не удалось выполнить запрос. Попробуйте ещё раз.";
}

export class StudioApi {
  constructor(private transport: typeof fetch = globalThis.fetch.bind(globalThis)) {}

  async get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return this.request<T>(path, undefined, signal);
  }

  async post<T>(path: string, body: unknown = {}, signal?: AbortSignal): Promise<T> {
    // Не повторять POST автоматически: сервер мог уже начать работу.
    const session = await this.get<{ token: string }>("/api/session", signal);
    if (!session.token) throw new ApiError("Не удалось открыть сессию. Обновите страницу.", 403);
    return this.request<T>(path, body, signal, session.token);
  }

  private async request<T>(path: string, body?: unknown, signal?: AbortSignal, token?: string): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const timer = setTimeout(abort, 45000);
    try {
      const response = await this.transport(path, {
        method: body === undefined ? "GET" : "POST", credentials: "same-origin",
        headers: body === undefined ? {} : { "Content-Type": "application/json", "X-Session-Token": token! },
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      });
      let data: unknown;
      try { data = await response.json(); }
      catch { throw new ApiError("Сервер вернул неожиданный ответ. Обновите страницу.", response.status); }
      if (!response.ok) throw new ApiError(serverMessage(data), response.status);
      return data as T;
    } catch (error) {
      if (signal?.aborted) throw new DOMException("Запрос отменён", "AbortError");
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted) throw new ApiError(
        "Сервер отвечает дольше обычного. Состояние отправленного запроса неизвестно; не запускайте его повторно сразу.", 0,
      );
      throw new ApiError("Нет связи с сервером. Проверьте соединение; материалы сохранены в форме.", 0);
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
}

export const api = new StudioApi();
