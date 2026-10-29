import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { authApi, meApi } from "../api/endpoints";
import { ApiError, redirectToKeycloakLogin } from "../api/client";
import { queryClient } from "../app/query";
import { Button, Field, Input, Spinner } from "../components/ui";

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = sanitizeNext(searchParams.get("next"));
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => meApi.get(),
    retry: false,
    staleTime: 60_000,
  });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me.isSuccess) navigate(next, { replace: true });
  }, [me.isSuccess, navigate, next]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError(null);
    if (!username.trim() || !password) {
      setError("Введите логин и пароль");
      return;
    }
    setBusy(true);
    try {
      const user = await authApi.directLogin(username.trim(), password);
      queryClient.setQueryData(["me"], user);
      navigate(next, { replace: true });
    } catch (loginError) {
      if (loginError instanceof ApiError && loginError.code === "rate_limited" && loginError.retryAfter) {
        setError(`Слишком много попыток входа — подождите ${loginError.retryAfter} с`);
      } else if (loginError instanceof ApiError && loginError.status >= 502) {
        setError("Сервис авторизации недоступен, попробуйте позже");
      } else {
        setError(loginError instanceof Error ? loginError.message : "Не удалось войти");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <img src="/favicon.svg" alt="" width={44} height={44} style={{ borderRadius: 10 }} />
        <h2>Вайб.Chat</h2>
        <p className="login-sub">Вход по учётной записи организации</p>

        {me.isPending ? (
          <div style={{ padding: 20 }}>
            <Spinner />
          </div>
        ) : (
          <>
            <Field label="Логин">
              <Input
                autoFocus
                autoComplete="username"
                value={username}
                maxLength={64}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="например, ivanov"
              />
            </Field>
            <Field label="Пароль">
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                maxLength={256}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Пароль"
              />
            </Field>
            {error ? <div className="field-error" style={{ marginBottom: 10 }}>{error}</div> : null}
            <Button type="submit" variant="primary" disabled={busy} style={{ width: "100%" }}>
              {busy ? "Вход…" : "Войти"}
            </Button>
            <button
              type="button"
              className="btn ghost"
              style={{ width: "100%", marginTop: 8 }}
              onClick={() => redirectToKeycloakLogin()}
              title="Если включена двухфакторная аутентификация или требуется смена пароля"
            >
              Войти через страницу Keycloak
            </button>
            <p className="login-hint">
              Если включена двухфакторная аутентификация или требуется смена пароля — используйте вход через Keycloak.
            </p>
          </>
        )}
      </form>
    </div>
  );
}

function sanitizeNext(value: string | null): string {
  if (!value) return "/";
  if (!value.startsWith("/") || value.startsWith("//")) return "/";
  if (value.startsWith("/login")) return "/";
  return value;
}
