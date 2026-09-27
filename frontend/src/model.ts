import type { Dataset, DesignRequest, Issue, Profile, Story } from "./types";

export const activeStatus = (status: string) =>
  ["queued", "planning", "running", "building", "rendering", "auditing", "fixing", "cancelling"].includes(status);

export function moveSlide(story: Story, index: number, delta: number): Story {
  const target = index + delta;
  if (target < 0 || target >= story.slides.length) return story;
  const slides = [...story.slides];
  [slides[index], slides[target]] = [slides[target], slides[index]];
  return { ...story, slides };
}

export function overlayBox(issue: Issue, profile?: Profile) {
  const raw = issue.bbox ?? (issue.box && profile ? {
    x: issue.box.left / profile.width, y: issue.box.top / profile.height,
    width: issue.box.width / profile.width, height: issue.box.height / profile.height,
  } : null);
  if (!raw || !Object.values(raw).every(Number.isFinite)) return null;
  const x = Math.max(0, Math.min(1, raw.x));
  const y = Math.max(0, Math.min(1, raw.y));
  const width = Math.min(1 - x, raw.x + raw.width - x);
  const height = Math.min(1 - y, raw.y + raw.height - y);
  if (width <= 0 || height <= 0) return null;
  const percent = (value: number) => `${Math.round(value * 1000000) / 10000}%`;
  return {
    left: percent(x), top: percent(y),
    width: percent(Math.min(1 - x, Math.max(0.01, width))),
    height: percent(Math.min(1 - y, Math.max(0.01, height))),
  };
}

export function canFix(issue: Issue): boolean {
  return issue.fix_available ?? (!!issue.fix && issue.fix !== "none");
}

export function selectedFixes(issues: Issue[], selected: Set<string>): string[] {
  return issues.filter(issue => selected.has(issue.id) && canFix(issue)).map(issue => issue.id);
}

export function validateStory(story: Story): string | null {
  if (!story.slides.length) return "В плане должен остаться хотя бы один слайд.";
  for (const [index, slide] of story.slides.entries()) {
    if (!slide.title.trim()) return `Добавьте заголовок слайда ${index + 1}.`;
    if (!slide.paragraphs.some(p => p.trim())) return `Добавьте содержание слайда ${index + 1}.`;
    if (slide.title.length > 180) return `Сократите заголовок слайда ${index + 1} до 180 символов.`;
    if (slide.visual && ["process", "comparison", "smartart"].includes(slide.visual.kind) && (slide.visual.labels.length < 2 || slide.visual.labels.some(label => !label.trim())))
      return `Добавьте не менее двух непустых подписей схемы слайда ${index + 1}.`;
  }
  return null;
}

/** CSV с кавычками и переносами; структура проверяется до отправки в генерацию. */
export function parseDataset(text: string, name: string, id: string): Dataset {
  const clean = text.replace(/^\uFEFF/, "");
  const delimiter = clean.split(/\r?\n/, 1)[0].includes(";") ? ";" : ",";
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < clean.length; i++) {
    const char = clean[i];
    if (char === '"') {
      if (quoted && clean[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (char === delimiter && !quoted) { row.push(cell.trim()); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && clean[i + 1] === "\n") i++;
      row.push(cell.trim()); if (row.some(Boolean)) rows.push(row); row = []; cell = "";
    } else cell += char;
  }
  if (quoted) throw new Error("В CSV не закрыта кавычка. Проверьте файл.");
  row.push(cell.trim()); if (row.some(Boolean)) rows.push(row);
  const columns = rows.shift();
  if (!columns || columns.length < 2 || columns.length > 20 || !rows.length)
    throw new Error("CSV должен содержать заголовок, 2–20 столбцов и хотя бы одну строку данных.");
  if (columns.some(c => !c) || new Set(columns).size !== columns.length)
    throw new Error("Заголовки столбцов должны быть непустыми и различаться.");
  if (rows.length > 200 || rows.some(r => r.length !== columns.length))
    throw new Error("В CSV допускается до 200 строк с одинаковым числом столбцов.");
  return {
    id, name: name.replace(/\.csv$/i, ""), columns, source: name, unit: "",
    rows: rows.map(r => r.map(value => {
      const normalized = delimiter === ";" ? value.replace(",", ".") : value;
      return /^-?\d+(\.\d+)?$/.test(normalized) && Math.abs(Number(normalized)) <= Number.MAX_SAFE_INTEGER
        ? Number(normalized) : value;
    })),
  };
}

export type ContentPack = Pick<DesignRequest, "script" | "required_messages" | "datasets"> & Partial<Pick<DesignRequest, "purpose" | "audience">>;

/** Импортирует только материалы; файл не может включить внешние вызовы или сменить режим. */
export function parseContentPack(text: string): ContentPack {
  let value: unknown;
  try { value = JSON.parse(text.replace(/^\uFEFF/, "")); }
  catch { throw new Error("Файл не содержит корректный JSON."); }
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  if (!record(value)) throw new Error("Пакет материалов должен быть объектом JSON.");
  const unknown = Object.keys(value).filter(key => !["script", "required_messages", "datasets", "purpose", "audience"].includes(key));
  if (unknown.length) throw new Error(`Неизвестные поля пакета: ${unknown.join(", ")}. Проверьте описание формата.`);
  if (typeof value.script !== "string" || !value.script.trim() || value.script.length > 100000)
    throw new Error("Поле script должно содержать от 1 до 100 000 символов текста.");
  const required = value.required_messages ?? [];
  if (!Array.isArray(required) || required.length > 50 || required.some(v => typeof v !== "string" || !v.trim()))
    throw new Error("required_messages — список максимум из 50 непустых тезисов.");
  const datasets = value.datasets ?? [];
  if (!Array.isArray(datasets) || datasets.length > 20) throw new Error("datasets — список максимум из 20 наборов данных.");
  const ids = new Set<string>();
  const normalized = datasets.map((item, index): Dataset => {
    const prefix = `Набор данных ${index + 1}: `;
    if (!record(item)) throw new Error(prefix + "ожидается объект.");
    if (Object.keys(item).some(key => !["id", "name", "columns", "rows", "source", "unit"].includes(key)))
      throw new Error(prefix + "обнаружены неизвестные поля.");
    if (typeof item.id !== "string" || !/^[a-zA-Z0-9_-]{1,80}$/.test(item.id) || ids.has(item.id))
      throw new Error(prefix + "id должен быть уникальным и содержать латинские буквы, цифры, _ или -.");
    ids.add(item.id);
    if (typeof item.name !== "string" || typeof item.source !== "string" || !item.source.trim())
      throw new Error(prefix + "укажите name и непустой source.");
    if (!Array.isArray(item.columns) || item.columns.length < 2 || item.columns.length > 20 || item.columns.some(v => typeof v !== "string" || !v.trim()) || new Set(item.columns).size !== item.columns.length)
      throw new Error(prefix + "нужны 2–20 различных непустых названий columns.");
    const columns = item.columns as string[];
    if (!Array.isArray(item.rows) || !item.rows.length || item.rows.length > 200 || item.rows.some(row => !Array.isArray(row) || row.length !== columns.length || row.some(cell => typeof cell !== "string" && (typeof cell !== "number" || !Number.isFinite(cell)))))
      throw new Error(prefix + "rows должен содержать 1–200 строк из строковых или числовых ячеек по числу столбцов.");
    if (item.unit !== undefined && typeof item.unit !== "string") throw new Error(prefix + "unit должен быть строкой.");
    return { id: item.id, name: item.name, source: item.source, columns, rows: item.rows as (string | number)[][], unit: item.unit as string ?? "" };
  });
  const result: ContentPack = { script: value.script, required_messages: required as string[], datasets: normalized };
  for (const [key, max] of [["purpose", 1000], ["audience", 500]] as const) {
    if (value[key] === undefined) continue;
    if (typeof value[key] !== "string" || value[key].length > max) throw new Error(`${key} должен быть строкой до ${max} символов.`);
    result[key] = value[key];
  }
  return result;
}
