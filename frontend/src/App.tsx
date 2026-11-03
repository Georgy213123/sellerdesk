import { useEffect, useState } from "react";
import { api, getToken, setToken, type Operator, type Template } from "./api";
import { ChatsPage } from "./components/ChatsPage";
import { FeedbackPage } from "./components/FeedbackPage";
import { LoginForm } from "./components/LoginForm";
import { SyncButton } from "./components/SyncButton";
import { TemplatesPage } from "./components/TemplatesPage";

type Tab = "chats" | "feedback" | "templates";

const TABS: [Tab, string][] = [
  ["chats", "Сообщения"],
  ["feedback", "Отзывы и вопросы"],
  ["templates", "Шаблоны"],
];

export function App() {
  const [operator, setOperator] = useState<Operator | null>(null);
  const [checked, setChecked] = useState(() => !getToken());
  const [tab, setTab] = useState<Tab>("chats");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then(setOperator)
      .catch(() => setToken(null))
      .finally(() => setChecked(true));
  }, []);

  const [templatesVersion, setTemplatesVersion] = useState(0);
  const reloadTemplates = async () => setTemplatesVersion((v) => v + 1);

  useEffect(() => {
    if (operator) void api.templates().then(setTemplates);
  }, [operator, templatesVersion]);

  if (!checked) return null;
  if (!operator) return <LoginForm onLogin={setOperator} />;

  return (
    <div className="app">
      <header className="topbar">
        <strong className="logo">SellerDesk</strong>
        <nav aria-label="Разделы">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`tab ${tab === id ? "active" : ""}`}
              aria-current={tab === id ? "page" : undefined}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        <SyncButton onDone={() => setRefreshToken((n) => n + 1)} />
        <span className="muted operator">{operator.display_name}</span>
        <button
          type="button"
          className="link"
          onClick={() => {
            setToken(null);
            setOperator(null);
          }}
        >
          Выйти
        </button>
      </header>
      <main>
        {tab === "chats" && <ChatsPage templates={templates} refreshToken={refreshToken} />}
        {tab === "feedback" && <FeedbackPage templates={templates} refreshToken={refreshToken} />}
        {tab === "templates" && <TemplatesPage templates={templates} onCreated={reloadTemplates} />}
      </main>
    </div>
  );
}
