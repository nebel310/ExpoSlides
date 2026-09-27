import { ApiError, StudioApi } from "./api";
import type { Job } from "./types";

export const SAVED_JOB_KEY = "exposlides-studio-job";

/** Ошибка связи и отмена эффекта не означают, что сохранённая работа исчезла. */
export async function restoreJob(api: StudioApi, storage: Pick<Storage, "getItem" | "removeItem">, signal: AbortSignal): Promise<Job | null> {
  const saved = storage.getItem(SAVED_JOB_KEY);
  if (!saved) return null;
  try {
    return await api.get<Job>(`/api/design/jobs/${encodeURIComponent(saved)}`, signal);
  } catch (error) {
    if (!signal.aborted && error instanceof ApiError && error.status === 404) {
      if (storage.getItem(SAVED_JOB_KEY) === saved) storage.removeItem(SAVED_JOB_KEY);
      return null;
    }
    throw error;
  }
}

export function jobView(job: Job): "materials" | "outline" | "results" {
  if (job.variants?.length) return "results";
  if (job.story) return "outline";
  return "materials";
}

export function jobError(job: Job): string {
  return job.error || (job.status === "failed" ? "Не удалось завершить работу. Материалы можно исправить и отправить снова." : "");
}

export function recentJobLabel(job: Job): string {
  const count = job.variants?.length ?? 0;
  if (job.status === "failed") return count ? `Ошибка · готово ${count} из 3` : "Не удалось завершить";
  if (job.status === "cancelled") return count ? `Остановлено · готово ${count} из 3` : "Остановлено";
  if (job.status === "completed") return count === 3 ? "Три варианта готовы" : `Доступно вариантов: ${count}`;
  if (job.status === "awaiting_review") return "План ожидает проверки";
  return "В работе";
}
