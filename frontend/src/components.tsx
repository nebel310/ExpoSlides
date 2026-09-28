import { useEffect, useState } from "react";
import { canFix, moveSlide, overlayBox, selectedFixes } from "./model";
import { recentJobLabel } from "./jobs";
import type { Dataset, Issue, Job, Profile, Story, StorySlide, Variant, Visual } from "./types";

export function RecentJobs({ jobs, loading, error, currentId, busy, onOpen, onRefresh }: {
  jobs: Job[]; loading: boolean; error: string; currentId?: string; busy: boolean;
  onOpen: (id: string) => void; onRefresh: () => void;
}) {
  return <section className="recent-panel" id="recent-jobs" aria-labelledby="recent-heading">
    <div className="recent-heading"><h2 id="recent-heading">Предыдущие работы</h2><button className="text-button" onClick={onRefresh} disabled={loading}>Обновить</button></div>
    {loading && <p role="status">Загружаем список…</p>}
    {error && <p className="recent-error" role="alert">{error}</p>}
    {!loading && !error && !jobs.length && <p>Работ пока нет.</p>}
    <div className="recent-list">{jobs.map(job => <button key={job.id} className={`recent-job ${job.id === currentId ? "active" : ""}`} disabled={busy} aria-current={job.id === currentId ? "true" : undefined} onClick={() => onOpen(job.id)}>
      <div><strong>{job.story?.title || job.template?.name || "Презентация"}</strong><span>{job.template?.name || "PPTX-шаблон"}{job.created_at ? ` · ${new Date(job.created_at * 1000).toLocaleDateString("ru-RU")}` : ""}</span></div><span className={job.status === "failed" ? "recent-failed" : ""}>{recentJobLabel(job)}{job.id === currentId ? " · открыто" : ""}</span>
    </button>)}</div>
    {busy && <p>Дождитесь завершения текущей операции.</p>}
  </section>;
}

export function ProfileCard({ profile }: { profile: Profile }) {
  const fonts = [...new Set(profile.patterns.map(p => p.font))];
  const colors = [...new Set(profile.patterns.flatMap(p => p.palette))].slice(0, 8);
  return <section className="profile-card" aria-label="Правила шаблона">
    <dl className="profile-details">
      <dt>Образцы</dt><dd>{profile.patterns.length}</dd>
      <dt>Шрифты</dt><dd>{fonts.join(", ")}</dd>
      <dt>Формат</dt><dd>{(profile.width / profile.height).toFixed(2)}:1</dd>
      <dt>Палитра</dt><dd><div className="swatches">{colors.map(color => <span key={color} title={`#${color}`} style={{ background: `#${color}` }} />)}</div></dd>
    </dl>
    {!!profile.warnings.length && <details><summary>Особенности шаблона ({profile.warnings.length})</summary>
      <ul>{profile.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>
    </details>}
  </section>;
}

export function StoryEditor({ story, datasets, onChange, onBuild, busy, profile }: {
  story: Story; datasets: Dataset[]; onChange: (story: Story) => void; onBuild: () => void; busy: boolean;
  profile?: Profile;
}) {
  function update(index: number, patch: Partial<StorySlide>) {
    onChange({ ...story, slides: story.slides.map((s, i) => i === index ? { ...s, ...patch } : s) });
  }
  function chooseVisual(index: number, kind: string) {
    const slide = story.slides[index];
    const visual: Visual | null = !kind ? null : {
      kind: kind as Visual["kind"], labels: ["process", "comparison", "smartart"].includes(kind)
        ? slide.paragraphs.slice(0, 4) : [],
      dataset_id: ["table", "bar", "line", "pie"].includes(kind) ? datasets[0]?.id : null,
    };
    update(index, { visual });
  }
  return <section className="outline" aria-labelledby="outline-heading">
    <div className="section-top"><div><h1 id="outline-heading">План</h1><p>Проверьте содержание и порядок. План общий для трёх вариантов.</p></div>
      <span className="slide-count">Слайдов: {story.slides.length}</span></div>
    <label className="field">Название презентации<input value={story.title} onChange={e => onChange({ ...story, title: e.target.value })} disabled={busy} /></label>
    <div className="outline-slides">{story.slides.map((slide, index) => <article key={slide.id} className="outline-slide">
      <div className="outline-number">{index + 1}</div>
      <div className="outline-content">
        <label className="field">Заголовок слайда {index + 1}<input aria-label={`Заголовок слайда ${index + 1}`} value={slide.title} maxLength={180} disabled={busy} onChange={e => update(index, { title: e.target.value })} /></label>
        <label className="field">Содержание<textarea aria-label={`Содержание слайда ${index + 1}`} rows={Math.max(3, slide.paragraphs.length + 1)} disabled={busy}
          value={slide.paragraphs.join("\n")} onChange={e => update(index, { paragraphs: e.target.value.split("\n") })} /></label>
        {slide.visual && ["process", "comparison", "smartart"].includes(slide.visual.kind) && <label className="field">Подписи элементов схемы<textarea aria-label={`Подписи схемы слайда ${index + 1}`} rows={Math.max(2, slide.visual.labels.length)} disabled={busy}
          value={slide.visual.labels.join("\n")} onChange={e => update(index, { visual: { ...slide.visual!, labels: e.target.value.split("\n").slice(0, 8) } })} /><span className="mode-hint">Одна подпись на строку; используйте формулировки из материалов.</span></label>}
        <div className="outline-bottom"><span className="source-tag" title={slide.source_ids.join(", ")}>Источников: {slide.source_ids.length}</span>
          <label>Представление <select aria-label={`Представление слайда ${index + 1}`} value={slide.visual?.kind ?? ""} disabled={busy} onChange={e => chooseVisual(index, e.target.value)}>
            <option value="">Текст</option><option value="process" disabled={slide.paragraphs.length < 2}>Этапы</option>
            <option value="comparison" disabled={slide.paragraphs.length < 2}>Сравнение</option>
            <option value="icon">Значок</option>
            {(slide.visual?.kind === "smartart" || profile?.patterns.some(p => p.visual_shape_ids?.smartart?.length)) && <option value="smartart" disabled={slide.paragraphs.length < 2}>SmartArt из шаблона</option>}
            {!!datasets.length && <><option value="table">Таблица</option><option value="bar">Столбцы</option><option value="line">Линия</option><option value="pie">Доли</option></>}
          </select></label>
          {slide.visual?.kind === "icon" && <label>Значок <select aria-label={`Значок слайда ${index + 1}`} value={slide.visual.icon ?? "arrow"} disabled={busy} onChange={e => update(index, { visual: { ...slide.visual!, icon: e.target.value as Visual["icon"] } })}><option value="arrow">Стрелка</option><option value="check">Галочка</option><option value="info">Информация</option></select></label>}
          {slide.visual?.dataset_id && <label>Данные <select aria-label={`Данные слайда ${index + 1}`} value={slide.visual.dataset_id} disabled={busy}
            onChange={e => update(index, { visual: { ...slide.visual!, dataset_id: e.target.value } })}>
            {datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select></label>}
        </div>
      </div>
      <div className="reorder"><button type="button" aria-label={`Поднять слайд ${index + 1}`} disabled={busy || index === 0} onClick={() => onChange(moveSlide(story, index, -1))}>↑</button>
        <button type="button" aria-label={`Опустить слайд ${index + 1}`} disabled={busy || index === story.slides.length - 1} onClick={() => onChange(moveSlide(story, index, 1))}>↓</button></div>
    </article>)}</div>
    <div className="sticky-action"><button className="primary" onClick={onBuild} disabled={busy}>Собрать три варианта</button></div>
  </section>;
}

function IssueItem({ issue, selected, focused, onSelect, onFocus, busy }: {
  issue: Issue; selected: boolean; focused: boolean; onSelect: () => void; onFocus: () => void; busy: boolean;
}) {
  return <article className={`issue ${focused ? "focused" : ""}`}>
    <div className="issue-top"><span className={`severity ${issue.severity}`}>{issue.severity === "error" ? "Ошибка" : issue.severity === "warning" ? "Замечание" : "Информация"}</span>
      <span>Слайд {issue.slide_index ?? "—"}</span></div>
    <button className="issue-focus" onClick={onFocus}>{issue.message}</button>
    <div className="issue-meta">{issue.check_type === "contextual" ? "Оценка содержания" : "Проверка по правилам"}</div>
    {issue.evidence && <details><summary>Обоснование</summary><p>{issue.evidence}</p></details>}
    {canFix(issue) ? <label className="check-label"><input type="checkbox" checked={selected} onChange={onSelect} disabled={busy} /> Исправить это замечание</label>
      : <span className="manual-note">Требует проверки содержания или ручной правки</span>}
  </article>;
}

export function VariantWorkspace({ variants, profile, busy, onFix, fixUnavailableReason }: {
  variants: Variant[]; profile?: Profile; busy: boolean;
  onFix: (variant: Variant, ids: string[]) => Promise<void>;
  fixUnavailableReason?: string;
}) {
  const [variantId, setVariantId] = useState(variants[0]?.id);
  const [slide, setSlide] = useState(0);
  const [selected, setSelected] = useState(new Set<string>());
  const [focused, setFocused] = useState<string | null>(null);
  const [showIssues, setShowIssues] = useState(true);
  const [onlySlide, setOnlySlide] = useState(false);
  const [previous, setPrevious] = useState<Variant | null>(null);
  const [showPrevious, setShowPrevious] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const variant = variants.find(v => v.id === variantId) ?? variants[0];
  useEffect(() => { setSelected(new Set()); setFocused(null); setShowPrevious(false); }, [variant.id, variant.revision]);
  useEffect(() => setImageFailed(false), [variant.id, variant.revision, slide, showPrevious]);
  const displayed = showPrevious && previous?.id === variant.id ? previous : variant;
  const issues = displayed.issues ?? [];
  const limitations = displayed.limitations ?? displayed.audit?.limitations ?? [];
  const contextual = displayed.contextual_status ?? displayed.audit?.contextual_status;
  const visibleIssues = onlySlide ? issues.filter(i => i.slide_index === slide + 1) : issues;
  const fixes = selectedFixes(variant.issues ?? [], selected);
  function choose(v: Variant) { setVariantId(v.id); setSlide(0); setShowPrevious(false); }
  async function fix() { setPrevious(structuredClone(variant)); await onFix(variant, fixes); }
  function focusIssue(issue: Issue) { if (issue.slide_index) setSlide(issue.slide_index - 1); setFocused(issue.id); setShowIssues(true); }
  return <section className="results" aria-labelledby="results-heading">
    <div className="section-top"><div><h1 id="results-heading">Презентация</h1>{variants.length !== 3 && <p>Доступно вариантов: {variants.length} из 3</p>}</div></div>
    <div className="variant-grid" role="group" aria-label="Варианты верстки">{variants.map(v => <button className={`variant-card ${v.id === variant.id ? "active" : ""}`} key={v.id} onClick={() => choose(v)} aria-pressed={v.id === variant.id}>
      <div className="variant-copy"><strong>{v.name}</strong></div>
    </button>)}</div>
    <div className="review-layout"><div className="review-main">
      <div className="canvas-toolbar"><div className="canvas-meta"><span>Версия {displayed.revision}</span>
        <label className="check-label"><input type="checkbox" checked={showIssues} onChange={e => setShowIssues(e.target.checked)} /> Замечания на слайде</label></div>
        <div className="export-buttons" role="group" aria-label="Скачать презентацию">{(["pptx", "pdf", "html"] as const).map(format => displayed.exports?.[format]
          ? <a className={format === "pptx" ? "primary" : "secondary"} download href={displayed.exports[format]} key={format}>{format.toUpperCase()}</a>
          : <span className="export-unavailable" key={format}>{format.toUpperCase()} недоступен</span>)}</div>
      </div>
      <div className="slide-surface" style={{ aspectRatio: profile ? profile.width / profile.height : 16 / 9 }}>
        {displayed.preview_urls?.[slide] && !imageFailed ? <img className="slide-image" src={displayed.preview_urls[slide]} alt={`Слайд ${slide + 1}, ${displayed.name}`} onError={() => setImageFailed(true)} />
          : <div className="no-preview"><h3>Предпросмотр недоступен</h3><p>Скачайте файл для проверки в PowerPoint.</p></div>}
        {showIssues && !showPrevious && issues.filter(i => i.slide_index === slide + 1).map(issue => {
          const box = overlayBox(issue, profile);
          return box && <button key={issue.id} className={`issue-overlay ${issue.severity} ${focused === issue.id ? "focused" : ""}`} style={box}
            title={issue.message} aria-label={`Показать замечание: ${issue.message}`} onClick={() => setFocused(issue.id)}><span>!</span></button>;
        })}
      </div>
      <div className="slide-controls"><button aria-label="Предыдущий слайд" disabled={slide === 0} onClick={() => setSlide(slide - 1)}>←</button>
        <span>Слайд {slide + 1} из {Math.max(1, displayed.preview_urls?.length ?? 0)}</span>
        <button aria-label="Следующий слайд" disabled={slide >= (displayed.preview_urls?.length ?? 0) - 1} onClick={() => setSlide(slide + 1)}>→</button>
        {previous?.id === variant.id && previous.revision !== variant.revision && <button className="text-button history" onClick={() => setShowPrevious(!showPrevious)}>{showPrevious ? "После исправления" : "До исправления"}</button>}
      </div>
      <div className="slide-strip" aria-label="Навигация по слайдам">{displayed.preview_urls?.map((url, i) => <button className={i === slide ? "active" : ""} key={`${url}-${i}`} onClick={() => setSlide(i)} aria-label={`Открыть слайд ${i + 1}`} aria-pressed={i === slide}>
        <img src={url} alt="" loading="lazy" /><span>{i + 1}</span></button>)}</div>
      {!!limitations.length && <details className="limitations"><summary>Границы проверки и экспорта ({limitations.length})</summary><ul>{limitations.map((text, i) => <li key={i}>{text}</li>)}</ul></details>}
    </div><aside className="audit-panel" aria-labelledby="audit-heading">
      <div className="audit-heading"><h2 id="audit-heading">Аудит</h2><span>Замечаний: {issues.length}</span></div>
      {contextual && contextual !== "completed" && <p className="audit-coverage">{contextual === "failed" ? "Проверка изображений моделью не завершена." : "Проверка изображений моделью отключена."} Проверки по правилам выполнены.</p>}
      <label className="check-label only-slide"><input type="checkbox" checked={onlySlide} onChange={e => setOnlySlide(e.target.checked)} /> Только этот слайд</label>
      <div className="issue-list">{visibleIssues.map(issue => <IssueItem key={issue.id} issue={issue} selected={selected.has(issue.id)} focused={focused === issue.id}
        busy={busy || showPrevious || !!fixUnavailableReason} onFocus={() => focusIssue(issue)} onSelect={() => setSelected(old => { const next = new Set(old); next.has(issue.id) ? next.delete(issue.id) : next.add(issue.id); return next; })} />)}
        {!visibleIssues.length && <p className="audit-clear">{issues.length ? "На этом слайде замечаний нет" : "Замечаний нет"}</p>}</div>
      {(issues.some(canFix) || fixUnavailableReason) && <div className="audit-actions"><button className="primary" disabled={busy || !fixes.length || showPrevious || !!fixUnavailableReason} onClick={fix}>Исправить выбранное {fixes.length > 0 && `(${fixes.length})`}</button>
        <span>{fixUnavailableReason || "Исправления сохранятся в новой версии."}</span></div>}
    </aside></div>
  </section>;
}
