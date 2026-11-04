import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type AgentRun, type AgentRunStatus, type Proposal } from "../api";
import { formatTime } from "../format";
import { UserText } from "./UserText";

const STATUS_LABEL: Record<AgentRunStatus, string> = {
  queued: "в очереди",
  running: "идёт",
  succeeded: "готово",
  failed: "ошибка",
  budget_exhausted: "остановлен по лимиту",
};

const KIND_LABEL: Record<Proposal["kind"], string> = {
  reply_template: "Шаблон ответа",
  card_edit: "Правка карточки",
};

const POLL_MS = 1000;

const fetchAll = () => Promise.all([api.agentRuns(), api.agentProposals("pending")]);

function numbers(prefix: string, ids: number[]): string | null {
  return ids.length ? `${prefix}: ${ids.map((id) => `№${id}`).join(", ")}` : null;
}

/** Раз в неделю агент разбирает обращения и кладёт предложения сюда. Решает оператор. */
export function AgentPage({ onTemplateCreated }: { onTemplateCreated: () => Promise<void> }) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [r, p] = await fetchAll();
    setRuns(r);
    setProposals(p);
  }, []);

  const latest = runs[0];
  const active = latest?.status === "queued" || latest?.status === "running";
  // Аренда истекла: владельца нет, опрашивать нечего, прогон надо подхватить.
  const abandoned = active && latest.abandoned;
  const polling = active && !abandoned;

  useEffect(() => {
    let alive = true;
    void fetchAll().then(([r, p]) => {
      if (!alive) return;
      setRuns(r);
      setProposals(p);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!polling) return;
    let alive = true;
    let timer: number | undefined;
    // Следующий опрос планируется после каждого запроса, в том числе неудачного.
    const schedule = () => {
      timer = window.setTimeout(async () => {
        await load().catch(() => undefined);
        if (alive) schedule();
      }, POLL_MS);
    };
    schedule();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [polling, load]);

  async function act(action: () => Promise<unknown>, after?: () => Promise<void>) {
    setError(null);
    try {
      await action();
      await after?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось выполнить действие");
    }
    await load().catch(() => undefined);
  }

  return (
    <section aria-label="Агент" className="agent">
      <div className="agent-head">
        <p className="muted">
          Раз в неделю агент разбирает отзывы, вопросы и чаты и находит повторяющиеся претензии. Сам
          ничего не публикует: предложения ждут вашего решения.
        </p>
        <button type="button" disabled={polling} onClick={() => void act(api.startAgentRun)}>
          {abandoned ? "Продолжить разбор" : polling ? "Идёт разбор…" : "Запустить разбор"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <h2>Последние разборы</h2>
      {runs.length === 0 && <p className="muted">Разборов ещё не было.</p>}
      <ul className="run-list">
        {runs.map((run) => (
          <li key={run.id} data-testid="agent-run" data-status={run.status}>
            <strong className={`run-${run.status}`}>
              №{run.id}: {run.abandoned ? "прервался" : STATUS_LABEL[run.status]}
            </strong>
            <span>
              Период {formatTime(run.period_from)} – {formatTime(run.period_to)}
            </span>
            <span>
              Шаги {run.steps_done} из {run.max_steps}
            </span>
            <span>
              Токены {run.tokens_used} из {run.token_budget}
            </span>
            {run.error && <span className="error">{run.error}</span>}
          </li>
        ))}
      </ul>

      <h2>Предложения на согласование</h2>
      {proposals.length === 0 && <p className="muted">Предложений на согласование нет.</p>}
      <ul className="proposal-list">
        {proposals.map((p) => (
          <li key={p.id} data-testid="proposal" data-kind={p.kind}>
            <span className="badge">{KIND_LABEL[p.kind]}</span>
            <h3>{p.title}</h3>
            <UserText text={p.body} />
            <p className="muted">
              Случаев: {p.evidence.cases}.{" "}
              {[
                numbers("Отзывы и вопросы", p.evidence.feedback_ids),
                numbers("Сообщения", p.evidence.message_ids),
              ]
                .filter(Boolean)
                .join(". ")}
            </p>
            <div className="actions">
              <button
                type="button"
                onClick={() =>
                  void act(
                    () => api.approveProposal(p.id),
                    p.kind === "reply_template" ? onTemplateCreated : undefined,
                  )
                }
              >
                Одобрить
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void act(() => api.rejectProposal(p.id))}
              >
                Отклонить
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
