import { useUiStore } from "../stores/ui";
import { Button } from "./ui";
import { useEffect } from "react";

export function Lightbox() {
  const lightbox = useUiStore((state) => state.lightbox);
  const close = useUiStore((state) => state.closeLightbox);
  const step = useUiStore((state) => state.lightboxStep);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key === "ArrowRight") step(1);
      if (event.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox, close, step]);

  if (!lightbox) return null;
  const item = lightbox.items[lightbox.index];
  if (!item) return null;

  return (
    <div className="lightbox" onMouseDown={(event) => event.target === event.currentTarget && close()}>
      <Button variant="ghost" className="lb-close" onClick={close} aria-label="Закрыть">
        ✕
      </Button>
      {lightbox.items.length > 1 ? (
        <button className="lb-nav prev" onClick={() => step(-1)} aria-label="Назад">
          ‹
        </button>
      ) : null}
      {item.url.match(/\.(mp4|webm|mov)(\?|$)/i) ? (
        <video src={item.url} controls autoPlay />
      ) : (
        <img src={item.url} alt={item.name} />
      )}
      {lightbox.items.length > 1 ? (
        <button className="lb-nav next" onClick={() => step(1)} aria-label="Вперёд">
          ›
        </button>
      ) : null}
      <div className="lb-caption">
        {item.name} ({lightbox.index + 1} из {lightbox.items.length})
      </div>
    </div>
  );
}
