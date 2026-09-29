import { useEffect, useState } from "react";
import "./slide-game.css";

const palettes = [
  { name: "Терракота", hue: 14, saturation: 48 },
  { name: "Шалфей", hue: 95, saturation: 25 },
  { name: "Морской воздух", hue: 200, saturation: 38 },
  { name: "Сирень", hue: 275, saturation: 30 },
  { name: "Тёплый песок", hue: 36, saturation: 50 },
];
const lightness = [88, 76, 64, 52, 40, 28];

function shuffledShades(): number[] {
  const shades = lightness.map((_, index) => index);
  for (let index = shades.length - 1; index > 0; index--) {
    const other = Math.floor(Math.random() * (index + 1));
    [shades[index], shades[other]] = [shades[other], shades[index]];
  }
  if (shades.every((shade, index) => shade === index)) {
    [shades[0], shades[3]] = [shades[3], shades[0]];
  }
  return shades;
}

export function SlideGame() {
  const [round, setRound] = useState(0);
  const [shades, setShades] = useState(shuffledShades);
  const [selected, setSelected] = useState<number | null>(null);
  const [hidden, setHidden] = useState(false);
  const palette = palettes[round % palettes.length];
  const complete = shades.every((shade, index) => shade === index);

  useEffect(() => {
    if (!complete) return;
    const timeout = window.setTimeout(() => {
      setRound(value => value + 1);
      setShades(shuffledShades());
      setSelected(null);
    }, 650);
    return () => window.clearTimeout(timeout);
  }, [complete]);

  function choose(position: number) {
    if (complete) return;
    if (selected === null) { setSelected(position); return; }
    if (selected !== position) {
      setShades(current => {
        const next = [...current];
        [next[selected], next[position]] = [next[position], next[selected]];
        return next;
      });
    }
    setSelected(null);
  }

  return <section className="slide-game" aria-label="Мини-игра Соберите палитру">
    <div className="slide-game-heading">
      <div><span className="slide-game-eyebrow">Пока собираются слайды</span><h2>Соберите палитру</h2></div>
      <button type="button" className="text-button" aria-expanded={!hidden} onClick={() => setHidden(value => !value)}>{hidden ? "Поиграть" : "Свернуть"}</button>
    </div>
    {!hidden && <>
      <p className="slide-game-intro">Расставьте оттенки от светлого к тёмному. Нажмите на две карточки, чтобы поменять их местами.</p>
      <div className={`palette-board ${complete ? "is-complete" : ""}`}>
        <div className="palette-caption"><span>{palette.name}</span><span aria-hidden="true">{String(round + 1).padStart(2, "0")}</span></div>
        <div className="palette-direction" aria-hidden="true"><span>Светлее</span><span>→</span><span>Темнее</span></div>
        <div className="palette-shades" role="group" aria-label="Оттенки от светлого к тёмному">
          {shades.map((shade, position) => <button key={position} type="button"
            className={`palette-shade ${selected === position ? "is-selected" : ""}`}
            style={{ backgroundColor: `hsl(${palette.hue}, ${palette.saturation}%, ${lightness[shade]}%)` }}
            aria-label={`Позиция ${position + 1}, светлота ${lightness[shade]}%`}
            aria-pressed={selected === position} aria-disabled={complete}
            onClick={() => choose(position)}>
            <span className="palette-marker" aria-hidden="true">{selected === position ? "↔" : position + 1}</span>
          </button>)}
        </div>
      </div>
      <div className="slide-game-footer">
        <p role="status" aria-live="polite">{complete ? "Готово — красивый переход!" : selected !== null ? "Теперь выберите вторую карточку." : "Спокойно, в своём темпе."}</p>
      </div>
      <p className="slide-game-note">Без таймера. Когда презентация будет готова, она появится здесь.</p>
    </>}
  </section>;
}
