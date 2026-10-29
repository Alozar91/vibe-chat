import { useEffect, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMe, isAdmin } from "../features/auth/queries";
import { Button, EmptyState, Spinner } from "../components/ui";

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const navigate = useNavigate();

  useEffect(() => {
    if (me.isError) {
      navigate(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`, {
        replace: true,
      });
    }
  }, [me.isError, navigate]);

  if (me.isPending) {
    return (
      <div className="auth-splash">
        <img src="/favicon.svg" alt="" width={48} height={48} />
        <Spinner />
        <div>Загрузка…</div>
      </div>
    );
  }

  if (me.isError || !me.data) {
    return (
      <div className="auth-splash">
        <div>Проверяем авторизацию…</div>
        <Button onClick={() => navigate("/login")}>Войти</Button>
      </div>
    );
  }

  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const me = useMe();
  if (!isAdmin(me.data)) {
    return <EmptyState icon="🔒" title="Недостаточно прав" hint="Раздел доступен администраторам организации." />;
  }
  return <>{children}</>;
}
