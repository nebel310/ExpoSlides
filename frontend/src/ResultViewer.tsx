import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { Job, Variant } from "./types";
import { canFix, overlayBox, selectedFixes } from "./model";

export function ResultViewer({ job, busy = false, onFix }: { job: Job; busy?: boolean;
  onFix?: (variant: Variant, ids: string[]) => Promise<void> }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focused, setFocused] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [variantId, setVariantId] = useState<string>();
  const [slideIndex, setSlideIndex] = useState(0);
  const [failedPreview, setFailedPreview] = useState<string | null>(null);
  const thumbnails = useRef<HTMLDivElement>(null);
  const variants = job.variants ?? [];
  const variant = variants.find(item => item.id === variantId) ?? variants[0];
  const previews = variant?.preview_urls ?? [];
  const current = Math.min(slideIndex, Math.max(0, previews.length - 1));
  const preview = previews[current];
  const title = job.story?.slides[current]?.title;
  const aspect = job.profile && job.profile.width > 0 && job.profile.height > 0
    ? job.profile.width / job.profile.height : 16 / 9;

  useEffect(() => {
    setVariantId(undefined);
    setSlideIndex(0);
    setFailedPreview(null);
  }, [job.id]);

  useEffect(() => {
    const strip = thumbnails.current;
    const selected = strip?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!strip || !selected) return;
    const viewport = strip.getBoundingClientRect();
    const item = selected.getBoundingClientRect();
    const left = item.left < viewport.left ? item.left - viewport.left
      : item.right > viewport.right ? item.right - viewport.right : 0;
    const top = item.top < viewport.top ? item.top - viewport.top
      : item.bottom > viewport.bottom ? item.bottom - viewport.bottom : 0;
    if (left || top) strip.scrollBy({ left, top, behavior: "auto" });
  }, [current, variant?.id]);

  useEffect(() => { setSelected(new Set()); setFocused(null); }, [job.id, variant?.id, variant?.revision]);

  function navigate(event: KeyboardEvent<HTMLElement>) {
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, select, [contenteditable=true]")
      || event.altKey || event.ctrlKey || event.metaKey || !previews.length) return;
    const next = event.key === "ArrowLeft" ? current - 1
      : event.key === "ArrowRight" ? current + 1
      : event.key === "Home" ? 0 : event.key === "End" ? previews.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    setSlideIndex(Math.max(0, Math.min(previews.length - 1, next)));
  }

  const issues = variant?.issues ?? [];
  const focusedIssue = issues.find(issue => issue.id === focused);
  const highlight = focusedIssue && overlayBox(focusedIssue, job.profile);
  const fixes = selectedFixes(issues, selected);

  if (!variant) return <p className="empty-state">Презентация ещё не готова.</p>;

  return <section className="result-viewer" aria-label="Предпросмотр презентации"
    tabIndex={0} onKeyDown={navigate}>
    <div className="viewer-toolbar">
      <div className="viewer-choice-heading"><h2>Выберите оформление</h2>
        <p>Сравните один и тот же слайд в разных вариантах.</p>
      </div>
      <div className="viewer-downloads">
        {variant.exports.pptx && <a className="primary" href={variant.exports.pptx} download>Скачать PPTX</a>}
        {variant.exports.pdf && <a className="secondary" href={variant.exports.pdf} download>PDF</a>}
        {variant.exports.html && <a className="secondary" href={variant.exports.html} download>HTML</a>}
      </div>
    </div>
    {issues.some(issue => issue.rule === "story_validation") && <p role="alert">
      Презентация готова с замечаниями. Не все факты, числа и полнота материалов прошли проверку.
      Проверьте содержание перед использованием; подробности — в проверке качества.
    </p>}
    <div className="viewer-variants" role="group" aria-label="Варианты оформления">
      {variants.map((item, index) => <button type="button" className="viewer-variant"
        key={item.id} aria-label={`Вариант ${index + 1}`} aria-pressed={item.id === variant.id}
        onClick={() => { setVariantId(item.id); setFailedPreview(null); }}>
        <span className="viewer-variant-preview" style={{ aspectRatio: aspect }}>
          <VariantPreview url={item.preview_urls[slideIndex]} />
        </span>
        <span className="viewer-variant-caption"><strong>Вариант {index + 1}</strong>
          <span>{item.id === variant.id ? "✓ Выбран" : "Посмотреть"}</span>
        </span>
      </button>)}
    </div>
    <div className="viewer-layout">
      {!!previews.length && <div className="viewer-thumbnails" ref={thumbnails} aria-label="Слайды">
        {previews.map((url, index) => <button type="button" className="thumbnail" key={`${variant.id}-${index}`}
          aria-label={`Открыть слайд ${index + 1}`} aria-current={index === current ? "true" : undefined}
          onClick={() => setSlideIndex(index)}>
          <span className="thumbnail-image" style={{ aspectRatio: aspect }}>
            <img src={url} alt="" loading="lazy" />
          </span>
          <span className="thumbnail-number">{index + 1}</span>
        </button>)}
      </div>}
      <div className="viewer-main">
        <div className="viewer-canvas" style={{ aspectRatio: aspect, position: "relative" }}>
          {auditOpen && highlight && (focusedIssue?.slide_index === current + 1) && <span className="audit-highlight" style={highlight} aria-label="Область замечания" />}
          {preview && failedPreview !== preview
            ? <img className="viewer-image" src={preview} alt={`Слайд ${current + 1}${title ? `: ${title}` : ""}`}
              onError={() => setFailedPreview(preview)} />
            : <div className="viewer-placeholder"><p>Предпросмотр недоступен.</p>
              {variant.exports.pptx && <p>Презентацию можно скачать и открыть на компьютере.</p>}
            </div>}
        </div>
        {!!previews.length && <div className="viewer-pagination">
          <button type="button" aria-label="Предыдущий слайд" disabled={current === 0}
            onClick={() => setSlideIndex(current - 1)}>←</button>
          <span aria-live="polite" aria-atomic="true">{current + 1} / {previews.length}</span>
          <button type="button" aria-label="Следующий слайд" disabled={current === previews.length - 1}
            onClick={() => setSlideIndex(current + 1)}>→</button>
        </div>}
      </div>
    </div>
    {onFix && <details className="workflow-audit" onToggle={event => setAuditOpen(event.currentTarget.open)}>
      <summary>Проверка качества · {issues.length} замечаний · версия {variant.revision}</summary>
      {!issues.length && <p>Замечаний нет.</p>}
      {issues.map(issue => <article className="workflow-issue" key={issue.id}>
        <button type="button" className="text-button" onClick={() => {
          setFocused(issue.id);
          if (issue.slide_index) setSlideIndex(Math.max(0, Math.min(previews.length - 1, issue.slide_index - 1)));
        }}>Слайд {issue.slide_index ?? "—"}: {issue.message}</button>
        {canFix(issue) ? <label><input type="checkbox" checked={selected.has(issue.id)} disabled={busy}
          onChange={() => setSelected(old => { const next = new Set(old); next.has(issue.id) ? next.delete(issue.id) : next.add(issue.id); return next; })} /> Исправить</label>
          : <p>Требуется ручная проверка или правка.</p>}
      </article>)}
      {issues.some(canFix) && <>
        <button type="button" className="primary" disabled={busy || !fixes.length || job.status !== "completed"}
          onClick={() => void onFix(variant, fixes)}>Исправить выбранное ({fixes.length})</button>
        <p>Будет создана новая версия. Предыдущие файлы сохранятся.</p>
      </>}
      {variant.revision > 1 && <details><summary>Предыдущие версии</summary>
        {Array.from({ length: variant.revision - 1 }, (_, index) => index + 1).map(revision => <div key={revision}>
          <span>Версия {revision}: </span>{Object.entries(variant.exports).map(([format, url]) =>
            <a className="text-button" key={format} href={url.replace(/\/files\/\d+\//, `/files/${revision}/`)} download> {format.toUpperCase()} </a>)}
        </div>)}
      </details>}
    </details>}
  </section>;
}

function VariantPreview({ url }: { url?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  return url && failed !== url
    ? <img src={url} alt="" onError={() => setFailed(url)} />
    : <span className="viewer-variant-unavailable">Предпросмотр недоступен</span>;
}
