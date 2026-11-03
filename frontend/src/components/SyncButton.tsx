import { useEffect, useRef, useState } from "react";
import { api, type SyncJob } from "../api";
import { formatTime } from "../format";

/** «Обновить» ставит задачу синхронизации и опрашивает её статус. Площадку не ждём. */
export function SyncButton({ onDone }: { onDone: () => void }) {
  const [job, setJob] = useState<SyncJob | null>(null);
  const timer = useRef<number | undefined>(undefined);

  function poll(id: number) {
    timer.current = window.setTimeout(async () => {
      const j = await api.sync(id);
      setJob(j);
      if (j.status === "queued" || j.status === "running") poll(id);
      else onDone();
    }, 500);
  }

  useEffect(() => {
    void api.latestSync().then((j) => {
      setJob(j);
      // Страницу открыли во время синхронизации — продолжаем опрос, иначе кнопка
      // так и останется заблокированной (CR-08).
      if (j && (j.status === "queued" || j.status === "running")) poll(j.id);
    });
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- опрос запускается один раз при монтировании
  }, []);

  async function start() {
    const j = await api.startSync();
    setJob(j);
    poll(j.id);
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
        {busy && "Задача в очереди, лента читается из кэша"}
      </span>
    </div>
  );
}
