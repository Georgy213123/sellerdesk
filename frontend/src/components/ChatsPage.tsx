import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey, type Chat, type ChatListItem, type Template } from "../api";
import { MARKETPLACE_LABEL, STATUS_LABEL, formatTime } from "../format";
import { ReplyComposer } from "./ReplyComposer";
import { TemplatePicker } from "./TemplatePicker";
import { UserText } from "./UserText";

interface Props {
  templates: Template[];
  refreshToken: number;
}

export function ChatsPage({ templates, refreshToken }: Props) {
  const [marketplace, setMarketplace] = useState("");
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<ChatListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const [chat, setChat] = useState<Chat | null>(null);
  const [draft, setDraft] = useState<{ text: string | null; note: string | null }>({
    text: null,
    note: null,
  });
  const [info, setInfo] = useState<string | null>(null);

  const [listVersion, setListVersion] = useState(0);
  const [chatVersion, setChatVersion] = useState(0);

  // Ответ, пришедший после переключения чата, к открытому чату не относится (CR-02).
  const openIdRef = useRef<number | null>(null);
  // Ключ ответа по шаблону живёт до подтверждённого ответа сервера: повтор после сетевой ошибки
  // идёт с тем же ключом (CR-04).
  const templateKeys = useRef(new Map<string, string>());

  useEffect(() => {
    let alive = true;
    void api.chats({ marketplace, status }).then((data) => {
      if (!alive) return;
      setItems(data.items);
      setTotal(data.total);
    });
    return () => {
      alive = false;
    };
  }, [marketplace, status, refreshToken, listVersion]);

  async function loadMore() {
    // Лента не обрезается первой страницей (CR-10).
    const data = await api.chats({ marketplace, status, offset: items.length });
    setItems((prev) => [...prev, ...data.items.filter((n) => !prev.some((p) => p.id === n.id))]);
    setTotal(data.total);
  }

  useEffect(() => {
    if (openId === null) return;
    let alive = true;
    void api.chat(openId).then((c) => {
      if (!alive) return;
      setChat(c);
      setDraft({ text: c.draft_text, note: c.draft_note });
    });
    return () => {
      alive = false;
    };
    // refreshToken: после синхронизации открытая переписка перечитывается (CR-09)
  }, [openId, chatVersion, refreshToken]);

  const loadList = async () => setListVersion((v) => v + 1);

  async function afterChange() {
    setChatVersion((v) => v + 1);
    await loadList();
  }

  function open(id: number | null) {
    setInfo(null);
    openIdRef.current = id;
    setOpenId(id);
  }

  const shown = chat !== null && chat.id === openId ? chat : null;

  async function requestDraft() {
    if (!shown) return;
    const chatId = shown.id;
    const d = await api.chatDraft(chatId);
    await loadList();
    if (openIdRef.current !== chatId) return; // черновик сохранён в карточке своего чата
    setDraft({ text: d.text, note: null });
    setInfo(d.note);
  }

  async function send(text: string, key: string) {
    if (!shown) return;
    await api.reply(shown.id, text, key);
    setInfo("Ответ отправлен");
    setDraft({ text: null, note: null });
    await afterChange();
  }

  async function applyTemplate(templateId: number) {
    if (!shown) return;
    const chatId = shown.id;
    const slot = `${chatId}:${templateId}`;
    const key = templateKeys.current.get(slot) ?? newIdempotencyKey();
    templateKeys.current.set(slot, key);
    let r;
    try {
      r = await api.chatTemplate(chatId, templateId, key);
    } catch (err) {
      setInfo(err instanceof Error ? `Не удалось: ${err.message}. Повторите.` : "Не удалось");
      return;
    }
    templateKeys.current.delete(slot);
    if (openIdRef.current !== chatId) {
      await loadList();
      return;
    }
    if (r.sent) {
      setInfo("Ответ по шаблону отправлен");
      setDraft({ text: null, note: null });
    } else {
      setDraft({ text: r.text, note: r.note });
      setInfo(null);
    }
    await afterChange();
  }

  return (
    <div className={`split ${openId !== null ? "has-open" : ""}`}>
      <section className="list-pane" aria-label="Лента чатов">
        <div className="filters">
          <label>
            Площадка
            <select
              aria-label="Площадка"
              value={marketplace}
              onChange={(e) => setMarketplace(e.target.value)}
            >
              <option value="">Все</option>
              {Object.entries(MARKETPLACE_LABEL).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Статус
            <select aria-label="Статус" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Все</option>
              {Object.entries(STATUS_LABEL).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <span className="muted" data-testid="chat-total">
            {total} чатов
          </span>
        </div>
        <ul className="feed">
          {items.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={`feed-item ${c.id === openId ? "active" : ""}`}
                onClick={() => open(c.id)}
                data-testid="chat-item"
                data-marketplace={c.marketplace}
              >
                <span className="feed-row">
                  <span className={`badge mp-${c.marketplace}`}>
                    {MARKETPLACE_LABEL[c.marketplace]}
                  </span>
                  <span className={`status st-${c.status}`} data-testid="chat-status">
                    {STATUS_LABEL[c.status]}
                  </span>
                  <time dateTime={c.last_message_at}>{formatTime(c.last_message_at)}</time>
                </span>
                <span className="feed-title">
                  {c.buyer_name ?? "Покупатель"} · {c.product_title ?? "без товара"}
                </span>
                <span className="feed-preview">{c.last_message_preview}</span>
              </button>
            </li>
          ))}
        </ul>
        {items.length < total && (
          <button type="button" className="secondary more" onClick={loadMore}>
            Показать ещё ({total - items.length})
          </button>
        )}
      </section>

      <section className="detail-pane" aria-label="Карточка чата">
        {shown ? (
          <>
            <button type="button" className="back link" onClick={() => open(null)}>
              ← К ленте
            </button>
            <header className="card-head">
              <h2>{shown.buyer_name ?? "Покупатель"}</h2>
              <p className="muted">
                {MARKETPLACE_LABEL[shown.marketplace]} · {shown.product_title ?? "без товара"}
                {shown.order_number ? ` · заказ ${shown.order_number}` : ""}
              </p>
              <p>
                Статус: <strong data-testid="card-status">{STATUS_LABEL[shown.status]}</strong>
              </p>
            </header>
            <ol className="messages">
              {shown.messages.map((m) => (
                <li key={m.id} className={`msg msg-${m.author}`}>
                  <UserText text={m.text} />
                  <time dateTime={m.created_at}>{formatTime(m.created_at)}</time>
                </li>
              ))}
            </ol>
            <div className="actions">
              <button type="button" className="secondary" onClick={requestDraft}>
                AI-черновик
              </button>
              <TemplatePicker templates={templates} onApply={applyTemplate} />
            </div>
            {info && (
              <p className="info" role="status">
                {info}
              </p>
            )}
            <ReplyComposer key={shown.id} draft={draft.text} note={draft.note} onSend={send} />
          </>
        ) : (
          <p className="muted placeholder">Выберите чат в ленте</p>
        )}
      </section>
    </div>
  );
}
