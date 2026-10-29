import dayjs from "dayjs";
import "dayjs/locale/ru";

dayjs.locale("ru");

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return dayjs(iso).format("HH:mm");
}

export function formatDay(iso: string): string {
  const d = dayjs(iso);
  const today = dayjs();
  if (d.isSame(today, "day")) return "Сегодня";
  if (d.isSame(today.subtract(1, "day"), "day")) return "Вчера";
  if (d.isSame(today, "year")) return d.format("D MMMM");
  return d.format("D MMMM YYYY");
}

export function formatListTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = dayjs(iso);
  const today = dayjs();
  if (d.isSame(today, "day")) return d.format("HH:mm");
  if (d.isSame(today, "year")) return d.format("DD.MM");
  return d.format("DD.MM.YYYY");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dayjs(iso).format("DD.MM.YYYY HH:mm");
}

export function lastSeenLabel(online: boolean, at: string | null | undefined): string {
  if (online) return "в сети";
  if (!at) return "не в сети";
  const d = dayjs(at);
  const today = dayjs();
  if (d.isSame(today, "day")) return `был(а) в ${d.format("HH:mm")}`;
  return `был(а) ${d.format("DD.MM HH:mm")}`;
}
