import { useToastStore } from "../stores/ui";

export function Toasts() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);
  if (!toasts.length) return null;
  return (
    <div className="toasts">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast ${toast.kind}`}
          role="status"
          onClick={() => {
            toast.onClick?.();
            dismiss(toast.id);
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="t-title">{toast.title}</div>
            {toast.body ? <div className="t-body">{toast.body}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
