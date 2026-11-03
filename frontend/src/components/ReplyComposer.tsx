import { useRef, useState } from "react";
import { newIdempotencyKey } from "../api";

interface Props {
  /** Черновик (AI или шаблон) — оператор правит его перед отправкой. */
  draft: string | null;
  note?: string | null;
  onSend: (text: string, idempotencyKey: string) => Promise<void>;
  label?: string;
}

/**
 * Поле ответа. Один ключ идемпотентности на один текст ответа: он живёт, пока ответ
 * не ушёл, и меняется после успеха или правки текста. Двойной клик и повтор после ошибки
 * идут с тем же ключом, и сервер не отправит второй ответ (BUG-01).
 */
export function ReplyComposer({ draft, note, onSend, label = "Отправить" }: Props) {
  const [text, setText] = useState(draft ?? "");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Ключ привязан к тексту: повтор того же текста — тот же ключ, правка после ошибки — новый.
  // Иначе сервер вернул бы старый ответ, а новый текст молча потерялся бы (CR-05).
  const keyRef = useRef<{ key: string; text: string } | null>(null);
  // state обновится только после перерисовки; второй клик в том же тике ловит ref
  const inFlight = useRef(false);

  // Новый черновик сверху (AI или шаблон) заменяет текст в поле.
  const [prevDraft, setPrevDraft] = useState(draft);
  if (draft !== prevDraft) {
    setPrevDraft(draft);
    if (draft !== null) setText(draft);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    setError(null);
    try {
      if (keyRef.current?.text !== value)
        keyRef.current = { key: newIdempotencyKey(), text: value };
      await onSend(value, keyRef.current.key);
      keyRef.current = null;
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отправить");
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      {note && (
        <p className="warning" role="alert">
          {note}
        </p>
      )}
      <label className="visually-hidden" htmlFor="reply-text">
        Текст ответа
      </label>
      <textarea
        id="reply-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="Ответ покупателю"
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" disabled={sending || !text.trim()}>
        {sending ? "Отправляем…" : label}
      </button>
    </form>
  );
}
