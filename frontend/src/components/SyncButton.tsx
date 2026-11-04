import { useEffect, useRef, useState } from "react";
import { api, type SyncJob } from "../api";
import { formatTime } from "../format";

/** «Обновить» ставит задачу синхронизации и опрашивает её статус. Площадку не ждём. */
export function SyncButton({ onDone }: { onDone: () => void }) {
  const [job, setJob] = useState<SyncJob | null>(null);
  const [offline, setOffline] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  function poll(id: number, delay = 500) {
    timer.current = window.setTimeout(async () => {
      try {
        const j = await api.sync(id);
        setOffline(false);
        setJob(j);
        if (j.status === "queued" || j.status === "running") poll(id);
        else onDone();
      } catch {
        // Нет связи: задача на сервере живёт, опрос повторяем позже.
        setOffline(true);
        poll(id, 3000);
      }
    }, delay);
  }

  useEffect(() => {
    void api
      .latestSync()
      .then((j) => {
        setJob(j);
        // Страницу открыли во время синхронизации — продолжаем опрос, иначе кнопка
        // так и останется заблокированной.
        if (j && (j.status === "queued" || j.status === "running")) poll(j.id);
      })
      .catch(() => setOffline(true));
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- опрос запускается один раз при монтировании
  }, []);

  async function start() {
    try {
      const j = await api.startSync();
      setOffline(false);
      setJob(j);
      poll(j.id);
    } catch {
      setOffline(true);
    }
  }

  const busy = job?.status === "queued" || job?.status === "running";
  return (
    <div className="sync">
      <button type="button" className="secondary" onClick={start} disabled={busy}>
        {busy ? "Синхронизация…" : "Обновить"}
      </button>
      <span className="muted" data-testid="sync-status">
        {job?.status === "done" && job.finished_at && `Данные на ${formatTime(job.finished_at)}`}
        {job?.status === "failed" && "Ошибка синхронизации"}
        {busy && !offline && "Задача в очереди, лента читается из кэша"}
        {offline && "Нет связи, повторим"}
      </span>
    </div>
  );
}
