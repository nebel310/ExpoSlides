import { useEffect, useRef, useState } from "react";
import { parseDataset } from "./model";
import type { Dataset } from "./types";
import "./datasets.css";

export function chartData(text: string, name: string, id: string): Dataset {
  const data = parseDataset(text, name, id);
  for (const [index, row] of data.rows.entries()) {
    if (!String(row[0]).trim()) throw new Error(`Строка ${index + 2}: укажите подпись в первом столбце.`);
    for (let column = 1; column < row.length; column++) {
      if (typeof row[column] !== "number" || !Number.isFinite(row[column]))
        throw new Error(`Строка ${index + 2}, «${data.columns[column]}»: нужно число без единиц и разделителей тысяч. Пустая ячейка не считается нулём.`);
    }
  }
  return data;
}

export function DatasetInput({ datasets, onChange, disabled, onPending }: {
  datasets: Dataset[]; onChange: (datasets: Dataset[]) => void; disabled: boolean;
  onPending: (pending: boolean) => void;
}) {
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const importVersion = useRef(0);
  useEffect(() => () => { importVersion.current++; }, []);
  useEffect(() => {
    onPending(reading);
    return () => onPending(false);
  }, [reading, onPending]);
  const locked = disabled || reading;
  function append(items: Dataset[]) {
    if (datasets.length + items.length > 20) throw new Error("Можно добавить не более 20 таблиц.");
    const next = [...datasets];
    for (const data of items) {
      let index = 1;
      while (next.some(item => item.id === `data-${index}`)) index++;
      next.push({ ...data, id: `data-${index}` });
    }
    onChange(next);
  }
  async function importFiles(files: File[]) {
    if (!files.length || locked) return;
    const version = ++importVersion.current;
    setReading(true); setError("");
    try {
      if (datasets.length + files.length > 20) throw new Error("Можно добавить не более 20 таблиц.");
      const items: Dataset[] = [];
      for (const file of files) {
        if (!/\.(csv|tsv)$/i.test(file.name) || !file.size || file.size > 400000)
          throw new Error("Выберите CSV или TSV в UTF-8 размером до 400 КБ каждый.");
        const bytes = await file.arrayBuffer();
        if (version !== importVersion.current) return;
        const value = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        items.push(chartData(value, file.name, "import"));
      }
      append(items);
    } catch (value) {
      if (version !== importVersion.current) return;
      setError(value instanceof TypeError ? "Не удалось прочитать UTF-8. Сохраните CSV в UTF-8." : (value as Error).message);
    } finally {
      if (version === importVersion.current) {
        setReading(false);
        if (fileRef.current) fileRef.current.value = "";
      }
    }
  }
  return <section className="dataset-input" aria-label="Таблицы">
    <input ref={fileRef} hidden type="file" multiple accept=".csv,.tsv" aria-label="Файл с данными"
      disabled={locked} onChange={event => void importFiles(Array.from(event.target.files ?? []))} />
    <button className="dataset-upload" type="button" disabled={locked || datasets.length >= 20}
      title="Таблицы Excel сохраните в CSV (UTF-8)."
      onClick={() => fileRef.current?.click()}>{reading ? "Читаем таблицы…" : "Добавить таблицы Excel/CSV"}</button>
    {datasets.map(data => <div className="dataset-file" key={data.id}>
      <span>{data.source}</span><button className="text-button" type="button" disabled={locked}
        aria-label={`Удалить ${data.name}`} onClick={() => onChange(datasets.filter(item => item.id !== data.id))}>×</button>
    </div>)}
    {error && <p className="error-message" role="alert">{error}</p>}
  </section>;
}
