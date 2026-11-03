import { useEffect, useState } from "react";
import { api, type Feedback, type Template } from "../api";
import { MARKETPLACE_LABEL, formatTime } from "../format";
import { ReplyComposer } from "./ReplyComposer";
import { TemplatePicker } from "./TemplatePicker";
import { UserText } from "./UserText";

interface Props {
  templates: Template[];
  refreshToken: number;
}

export function FeedbackPage({ templates, refreshToken }: Props) {
  const [kind, setKind] = useState("");
  const [rating, setRating] = useState("");
  const [answered, setAnswered] = useState("");
  const [items, setItems] = useState<Feedback[]>([]);
  const [total, setTotal] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);

  const [version, setVersion] = useState(0);
  const load = async () => setVersion((v) => v + 1);

  useEffect(() => {
    let alive = true;
    void api.feedback({ kind, rating, answered }).then((data) => {
      if (!alive) return;
      setItems(data.items);
      setTotal(data.total);
    });
    return () => {
      alive = false;
    };
  }, [kind, rating, answered, refreshToken, version]);

  async function loadMore() {
    const data = await api.feedback({ kind, rating, answered, offset: items.length });
    setItems((prev) => [...prev, ...data.items.filter((n) => !prev.some((p) => p.id === n.id))]);
    setTotal(data.total);
  }

  return (
    <section aria-label="Отзывы и вопросы">
      <div className="filters">
        <label>
          Тип
          <select aria-label="Тип" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Все</option>
            <option value="review">Отзывы</option>
            <option value="question">Вопросы</option>
          </select>
        </label>
        <label>
          Оценка
          <select aria-label="Оценка" value={rating} onChange={(e) => setRating(e.target.value)}>
            <option value="">Любая</option>
            {[5, 4, 3, 2, 1].map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label>
          Ответ
          <select aria-label="Ответ" value={answered} onChange={(e) => setAnswered(e.target.value)}>
            <option value="">Все</option>
            <option value="false">Без ответа</option>
            <option value="true">С ответом</option>
          </select>
        </label>
      </div>
      <ul className="feedback-list">
        {items.map((f) => (
          <FeedbackItem
            key={f.id}
            item={f}
            open={openId === f.id}
            onToggle={() => setOpenId(openId === f.id ? null : f.id)}
            templates={templates}
            onChanged={load}
          />
        ))}
      </ul>
      {items.length < total && (
        <button type="button" className="secondary more" onClick={loadMore}>
          Показать ещё ({total - items.length})
        </button>
      )}
    </section>
  );
}

interface ItemProps {
  item: Feedback;
  open: boolean;
  onToggle: () => void;
  templates: Template[];
  onChanged: () => Promise<void>;
}

export function FeedbackItem({ item, open, onToggle, templates, onChanged }: ItemProps) {
  const [draft, setDraft] = useState<{ text: string | null; note: string | null }>({
    text: item.draft_text,
    note: item.draft_note,
  });

  async function requestDraft() {
    const d = await api.feedbackDraft(item.id);
    setDraft({ text: d.text, note: null });
  }

  async function applyTemplate(id: number) {
    const r = await api.feedbackTemplate(item.id, id);
    if (r.sent) await onChanged();
    else setDraft({ text: r.text, note: r.note });
  }

  async function send(text: string) {
    await api.answerFeedback(item.id, text);
    await onChanged();
  }

  return (
    <li className="feedback-card" data-testid="feedback-item">
      <div className="feed-row">
        <span className={`badge mp-${item.marketplace}`}>
          {MARKETPLACE_LABEL[item.marketplace]}
        </span>
        <span className="muted">{item.kind === "review" ? "Отзыв" : "Вопрос"}</span>
        {item.rating !== null && (
          <span className="rating" aria-label={`Оценка ${item.rating} из 5`}>
            {"★".repeat(item.rating)}
            {"☆".repeat(5 - item.rating)}
          </span>
        )}
        <time dateTime={item.created_at}>{formatTime(item.created_at)}</time>
      </div>
      <p className="feed-title">
        {item.buyer_name ?? "Покупатель"} · {item.product_title ?? "без товара"}
      </p>
      <UserText text={item.text} />
      {item.answer_text ? (
        <div className="answer" data-testid="feedback-answer">
          <span className="muted">Ответ продавца:</span>
          <UserText text={item.answer_text} />
        </div>
      ) : open ? (
        <div className="answer-form">
          <div className="actions">
            <button type="button" className="secondary" onClick={requestDraft}>
              AI-черновик
            </button>
            <TemplatePicker templates={templates} onApply={applyTemplate} />
          </div>
          <ReplyComposer draft={draft.text} note={draft.note} onSend={send} label="Ответить" />
        </div>
      ) : (
        <button type="button" className="link" onClick={onToggle}>
          Ответить
        </button>
      )}
    </li>
  );
}
