/** Просмотрщик изображений (лайтбокс, §8): полноэкранный оверлей с оригиналом.
 * Навигация по ВСЕМ картинкам ленты (не только одного сообщения), лента
 * превью внизу, Esc/клик по фону — закрыть. Рендерится в body через портал.
 */

import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

export interface LightboxImage {
  /** Оригинал (presigned URL) — показываем всегда оригинал, не thumbnail. */
  url: string
  /** Превью для ленты внизу (thumb_url). */
  thumbUrl?: string
  name?: string | null
}

interface Props {
  images: LightboxImage[]
  index: number
  onClose: () => void
  onNavigate: (index: number) => void
}

export function Lightbox({ images, index, onClose, onNavigate }: Props) {
  const img = images[index]
  // автоскролл ленты превью к активной миниатюре
  const thumbsRef = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLButtonElement>(null)

  const prev = useCallback(() => {
    onNavigate((index - 1 + images.length) % images.length)
  }, [index, images.length, onNavigate])

  const next = useCallback(() => {
    onNavigate((index + 1) % images.length)
  }, [index, images.length, onNavigate])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && images.length > 1) prev()
      if (e.key === 'ArrowRight' && images.length > 1) next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, prev, next, images.length])

  // активная миниатюра в видимую область ленты превью
  useEffect(() => {
    activeRef.current?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
  }, [index])

  if (!img) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex flex-col bg-black/95"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      {/* шапка: имя + счётчик + закрыть */}
      <div className="flex items-center gap-3 px-4 py-3 text-white" onClick={(e) => e.stopPropagation()}>
        <span className="min-w-0 flex-1 truncate text-sm">{img.name ?? ''}</span>
        <span className="text-xs text-white/60">
          {index + 1} / {images.length}
        </span>
        <button onClick={onClose} title="Закрыть (Esc)" className="rounded-full p-2 hover:bg-white/10">
          <X className="size-5" />
        </button>
      </div>

      {/* картинка: вписана в окно (объект-contain), клик по ней не закрывает */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center">
        <button
          onClick={(e) => {
            e.stopPropagation()
            prev()
          }}
          title="Предыдущая (←)"
          className="absolute left-3 z-10 flex size-12 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
        >
          <ChevronLeft className="size-7" />
        </button>
        <img
          src={img.url}
          alt={img.name ?? ''}
          className="max-h-full max-w-full object-contain"
          onClick={(e) => e.stopPropagation()}
        />
        <button
          onClick={(e) => {
            e.stopPropagation()
            next()
          }}
          title="Следующая (→)"
          className="absolute right-3 z-10 flex size-12 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
        >
          <ChevronRight className="size-7" />
        </button>
      </div>

      {/* лента превью: все картинки ленты; клик не закрывает оверлей */}
      {images.length > 1 && (
        <div
          ref={thumbsRef}
          className="flex shrink-0 gap-2 overflow-x-auto px-4 py-3"
          onClick={(e) => e.stopPropagation()}
        >
          {images.map((im, i) => (
            <button
              key={im.url ?? i}
              ref={i === index ? activeRef : undefined}
              onClick={() => onNavigate(i)}
              className={`h-16 w-24 shrink-0 overflow-hidden rounded-md border-2 ${
                i === index ? 'border-white' : 'border-transparent opacity-50 hover:opacity-90'
              }`}
            >
              <img src={im.thumbUrl ?? im.url} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>,
    document.body,
  )
}
