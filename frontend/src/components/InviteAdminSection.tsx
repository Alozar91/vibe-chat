/** Админ-секция инвайтов (§5): создание multi-use инвайтов-ссылок, список, деактивация. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Link2, Plus } from 'lucide-react'
import { useState } from 'react'
import { invitesApi } from '@/api/client'
import { fmtDateTime } from '@/lib/format'

/** Ссылка регистрации с предзаполненным кодом (/register?code=…, §5). */
function inviteLink(code: string): string {
  return `${window.location.origin}/register?code=${encodeURIComponent(code)}`
}

export function InviteAdminSection() {
  const queryClient = useQueryClient()
  const [createdCode, setCreatedCode] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [maxUses, setMaxUses] = useState('') // пусто = безлимит

  const invites = useQuery({ queryKey: ['invites'], queryFn: invitesApi.list })

  const create = useMutation({
    mutationFn: () => invitesApi.create(maxUses ? Number(maxUses) : undefined),
    onSuccess: (inv) => {
      setCreatedCode(inv.code)
      setCopied(false)
      void queryClient.invalidateQueries({ queryKey: ['invites'] })
    },
  })

  const deactivate = useMutation({
    mutationFn: (id: string) => invitesApi.deactivate(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['invites'] }),
  })

  const copyLink = async (code: string) => {
    await navigator.clipboard.writeText(inviteLink(code))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section className="mt-10 max-w-xl">
      <h2 className="mb-3 text-sm font-semibold text-muted">Инвайты (платформенный админ)</h2>

      <div className="mb-4 flex items-center gap-2 rounded-xl border border-border bg-panel p-4">
        <input
          value={maxUses}
          onChange={(e) => setMaxUses(e.target.value.replace(/\D/g, ''))}
          placeholder="Лимит использований (пусто = безлимит)"
          className="flex-1 rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          onClick={() => create.mutate()}
          disabled={create.isPending}
          className="flex items-center gap-1 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-40"
        >
          <Plus className="size-4" /> Создать
        </button>
      </div>

      {createdCode && (
        <div className="mb-4 rounded-xl border border-accent/40 bg-accent/10 p-4">
          <div className="mb-2 flex items-center gap-1.5 text-xs text-muted">
            <Link2 className="size-3.5" />
            Инвайт-ссылка создана — отправьте её тем, кто должен зарегистрироваться. Больше она не
            отобразится:
          </div>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-panel-2 px-2.5 py-1.5 text-xs select-all text-accent">
              {inviteLink(createdCode)}
            </code>
            <button
              onClick={() => void copyLink(createdCode)}
              title="Скопировать ссылку"
              className="flex shrink-0 items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? 'Скопировано' : 'Копировать'}
            </button>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-border bg-panel">
        {invites.isLoading ? (
          <div className="p-4 text-sm text-muted">Загрузка…</div>
        ) : (invites.data ?? []).length === 0 ? (
          <div className="p-4 text-sm text-muted">Инвайтов ещё нет</div>
        ) : (
          (invites.data ?? []).map((inv) => (
            <div key={inv.id} className="flex items-center gap-3 border-b border-border px-4 py-2.5 text-sm last:border-0">
              <span className="flex-1">
                Использований: {inv.uses_count}
                {inv.max_uses !== null ? ` / ${inv.max_uses}` : ' (безлимит)'}
              </span>
              <span className="text-xs text-muted">создан {fmtDateTime(inv.created_at, 'browser', null)}</span>
              {inv.expires_at && <span className="text-xs text-amber-400">до {fmtDateTime(inv.expires_at, 'browser', null)}</span>}
              {inv.deactivated_at ? (
                <span className="text-xs text-red-400">отключён</span>
              ) : (
                <button
                  onClick={() => deactivate.mutate(inv.id)}
                  className="text-xs text-muted underline hover:text-text"
                >
                  отключить
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  )
}
