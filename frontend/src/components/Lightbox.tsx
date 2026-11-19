/** Просмотрщик изображений (лайтбокс, §8): полноэкранный оверлей с оригиналом,
 * переключение prev/next между картинками сообщения, Esc/клик по фону — закрыть.
 * Рендерится через createPortal в body — поверх ленты.
 */

import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useCallback, useEffect } from 'react'
import { createPortal } from 'react-dom'

export interface LightboxImage {
  /** Оригинал (presigned URL) — показываем всегда оригинал, не thumbnail. */
  url: string
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

  if (!img) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex flex-col bg-black/90"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      {/* шапка: имя + счётчик + закрыть; stopPropagation — клик не закрывает */}
      <div className="flex items-center gap-3 px-4 py-3 text-white" onClick={(e) => e.stopPropagation()}>
        <span className="min-w-0 flex-1 truncate text-sm">{img.name ?? ''}</span>
        {images.length > 1 && (
          <span className="text-xs text-white/60">
            {index + 1} / {images.length}
          </span>
        )}
        <button
          onClick={onClose}
          title="Закрыть (Esc)"
          className="rounded-full p-2 hover:bg-white/10"
        >
          <X className="size-5" />
        </button>
      </div>

      {/* картинка: клик по ней не закрывает, клик по фону вокруг — закрывает */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-2">
        {images.length > 1 && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              prev()
            }}
            title="Предыдущая (←)"
            className="absolute left-3 z-10 flex size-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
          >
            <ChevronLeft className="size-6" />
          </button>
        )}
        <img
          src={img.url}
          alt={img.name ?? ''}
          className="max-h-full max-w-full object-contain"
          onClick={(e) => e.stopPropagation()}
        />
        {images.length > 1 && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              next()
            }}
            title="Следующая (→)"
            className="absolute right-3 z-10 flex size-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
          >
            <ChevronRight className="size-6" />
          </button>
        )}
      </div>
    </div>,
    document.body,
  )
}
