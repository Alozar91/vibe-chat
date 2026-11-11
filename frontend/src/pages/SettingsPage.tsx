/** Настройки: профиль (персональные данные — в системе, §5), time_display/timezone;
 * платформенному админу — инвайты. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { usersApi } from '@/api/client'
import type { User } from '@/api/types'
import { InviteAdminSection } from '@/components/InviteAdminSection'

export function SettingsPage() {
  const me = useQuery({ queryKey: ['me'], queryFn: usersApi.me })
  const queryClient = useQueryClient()

  const [displayName, setDisplayName] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [timeDisplay, setTimeDisplay] = useState<User['time_display']>('browser')
  const [timezone, setTimezone] = useState('')

  useEffect(() => {
    if (me.data) {
      setDisplayName(me.data.display_name)
      setFirstName(me.data.first_name ?? '')
      setLastName(me.data.last_name ?? '')
      setEmail(me.data.email ?? '')
      setTimeDisplay(me.data.time_display)
      setTimezone(me.data.timezone ?? '')
    }
  }, [me.data])

  const save = useMutation({
    mutationFn: () =>
      usersApi.updateMe({
        display_name: displayName.trim(),
        first_name: firstName.trim() || null,
        last_name: lastName.trim() || null,
        email: email.trim() || null,
        time_display: timeDisplay,
        timezone: timezone.trim() || null,
      }),
    onSuccess: (user) => {
      queryClient.setQueryData(['me'], user)
      void queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })

  const inputCls =
    'w-full rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent'

  return (
    <div className="h-full overflow-y-auto px-8 py-6">
      <h1 className="mb-6 text-xl font-semibold">Настройки</h1>

      <section className="mb-8 max-w-md">
        <h2 className="mb-3 text-sm font-semibold text-muted">Профиль</h2>
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-panel p-4">
          <label className="text-xs text-muted">
            Имя пользователя (изменить нельзя)
            <input value={`@${me.data?.username ?? ''}`} disabled className={`${inputCls} mt-1 opacity-50`} />
          </label>
          <label className="text-xs text-muted">
            Отображаемое имя
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className={`${inputCls} mt-1`} />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-muted">
              Имя
              <input value={firstName} onChange={(e) => setFirstName(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
            <label className="text-xs text-muted">
              Фамилия
              <input value={lastName} onChange={(e) => setLastName(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
          </div>
          <label className="text-xs text-muted">
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={`${inputCls} mt-1`} />
          </label>
          <div className="text-[11px] text-muted/70">
            Персональные данные хранятся в системе; Keycloak знает только логин и пароль (§5).
          </div>
        </div>
      </section>

      <section className="mb-8 max-w-md">
        <h2 className="mb-3 text-sm font-semibold text-muted">Отображение времени</h2>
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-panel p-4">
          <label className="text-xs text-muted">
            Режим
            <select
              value={timeDisplay}
              onChange={(e) => setTimeDisplay(e.target.value as User['time_display'])}
              className={`${inputCls} mt-1`}
            >
              <option value="browser">Мой часовой пояс (браузер)</option>
              <option value="as_sent">Как отправлено (пояс отправителя)</option>
              <option value="fixed">Фиксированный пояс</option>
              <option value="utc">UTC</option>
            </select>
          </label>
          {timeDisplay === 'fixed' && (
            <label className="text-xs text-muted">
              Часовой пояс (IANA, например Europe/Moscow)
              <input value={timezone} onChange={(e) => setTimezone(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
          )}
        </div>
      </section>

      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-40"
      >
        {save.isPending ? 'Сохранение…' : 'Сохранить'}
      </button>
      {save.isError && (
        <div className="mt-3 max-w-md rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">
          Ошибка сохранения: {(save.error as Error).message}
          {String((save.error as { status?: number }).status) === '422' && ' (проверьте IANA-имя пояса)'}
        </div>
      )}
      {save.isSuccess && <div className="mt-3 text-sm text-emerald-400">Сохранено</div>}

      {me.data?.is_platform_admin && <InviteAdminSection />}
    </div>
  )
}
