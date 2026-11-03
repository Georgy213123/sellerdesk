import type { ChatStatus, Marketplace } from "./api";

export const MARKETPLACE_LABEL: Record<Marketplace, string> = {
  wildberries: "Wildberries",
  ozon: "Ozon",
  yandex_market: "Яндекс Маркет",
};

export const STATUS_LABEL: Record<ChatStatus, string> = {
  new: "Новый",
  in_progress: "В работе",
  answered: "Отвечен",
};

const fmt = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** Время с сервера всегда в UTC со смещением; показываем в зоне оператора. */
export function formatTime(iso: string, timeZone?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return timeZone
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone,
      }).format(d)
    : fmt.format(d);
}
