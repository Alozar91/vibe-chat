import type { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { avatarColor, initials } from "../lib/format";
import { useMediaUrl } from "../features/media/useMediaUrl";
import { appNavigate } from "../realtime/navigator";

export function Button({
  variant = "default",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "danger" | "ghost" }) {
  const variantClass = variant === "default" ? "" : ` ${variant}`;
  return (
    <button className={`btn${variantClass} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`input ${className}`} {...rest} />;
}

export function Textarea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`textarea ${className}`} {...rest} />;
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={`select ${className}`} {...rest}>
      {children}
    </select>
  );
}

export function Spinner() {
  return <div className="spinner" role="status" aria-label="Загрузка" />;
}

export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {error ? <div className="field-error">{error}</div> : null}
    </div>
  );
}

export function Pill({ tone, children }: { tone?: "green" | "red" | "yellow"; children: ReactNode }) {
  return <span className={`pill${tone ? ` ${tone}` : ""}`}>{children}</span>;
}

export function Badge({ value }: { value: number }) {
  if (value <= 0) return null;
  return <span className="badge">{value > 99 ? "99+" : value}</span>;
}

export function EmptyState({ icon, title, hint, children }: { icon?: string; title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      {icon ? <div style={{ fontSize: 40 }}>{icon}</div> : null}
      <div style={{ fontWeight: 700, color: "var(--text-2)", fontSize: 16 }}>{title}</div>
      {hint ? <div style={{ maxWidth: 380 }}>{hint}</div> : null}
      {children}
    </div>
  );
}

export function Avatar({
  name,
  url,
  size = 40,
  seed,
}: {
  name: string;
  url?: string | null;
  size?: number;
  seed?: string;
}) {
  const resolvedUrl = useMediaUrl(url || null);
  const style: CSSProperties = {
    width: size,
    height: size,
    fontSize: Math.max(11, Math.round(size * 0.38)),
    background: avatarColor(seed || name),
  };
  if (resolvedUrl) {
    return (
      <span className="avatar" style={style}>
        <img src={resolvedUrl} alt={name} loading="lazy" />
      </span>
    );
  }
  return (
    <span className="avatar" style={style}>
      {initials(name)}
    </span>
  );
}

export function PageBack() {
  return (
    <Button
      variant="ghost"
      className="icon mobile-only"
      onClick={() => appNavigate("/")}
      aria-label="Назад"
      style={{ marginBottom: 6 }}
    >
      ‹
    </Button>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true">
        <div className="modal-header">
          {title}
          <span className="spacer" />
          <Button variant="ghost" onClick={onClose} aria-label="Закрыть">
            ✕
          </Button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-footer">{footer}</div> : null}
      </div>
    </div>
  );
}
