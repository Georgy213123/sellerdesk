import { useState } from "react";
import { ApiError, api, type Template } from "../api";

interface Props {
  templates: Template[];
  onCreated: () => Promise<void>;
}

export function TemplatesPage({ templates, onCreated }: Props) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createTemplate(name, body);
      setName("");
      setBody("");
      await onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить");
    }
  }

  return (
    <section aria-label="Шаблоны" className="templates">
      <p className="muted">
        Переменные: {"{{buyer_name}}"}, {"{{product}}"}, {"{{order_number}}"}, {"{{marketplace}}"},{" "}
        {"{{operator_name}}"}. Если значение не нашлось, ответ не уйдёт покупателю, а останется
        черновиком с причиной.
      </p>
      <ul className="template-list">
        {templates.map((t) => (
          <li key={t.id}>
            <h3>{t.name}</h3>
            <p className="user-text">{t.body}</p>
          </li>
        ))}
      </ul>
      <form className="template-form" onSubmit={submit}>
        <h3>Новый шаблон</h3>
        <label>
          Название
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Текст
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={4} required />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit">Сохранить</button>
      </form>
    </section>
  );
}
