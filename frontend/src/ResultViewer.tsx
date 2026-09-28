import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { Job } from "./types";

export function ResultViewer({ job }: { job: Job }) {
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

  if (!variant) return <p className="empty-state">Презентация ещё не готова.</p>;

  return <section className="result-viewer" aria-label="Предпросмотр презентации"
    tabIndex={0} onKeyDown={navigate}>
    <div className="viewer-toolbar">
      <label className="variant-select">Вариант
        <select value={variant.id} onChange={event => {
          setVariantId(event.target.value);
          setSlideIndex(0);
          setFailedPreview(null);
        }}>
          {variants.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <div className="viewer-downloads">
        {variant.exports.pptx && <a className="primary" href={variant.exports.pptx} download>Скачать PPTX</a>}
        {variant.exports.pdf && <a className="secondary" href={variant.exports.pdf} download>PDF</a>}
      </div>
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
        <div className="viewer-canvas" style={{ aspectRatio: aspect }}>
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
  </section>;
}
