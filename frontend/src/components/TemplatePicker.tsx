import { useState } from "react";
import type { Template } from "../api";

interface Props {
  templates: Template[];
  onApply: (templateId: number) => Promise<void>;
}

export function TemplatePicker({ templates, onApply }: Props) {
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function apply() {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await onApply(Number(selected));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="template-picker">
      <label>
        Шаблон
        <select aria-label="Шаблон" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— выберите —</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="secondary" onClick={apply} disabled={!selected || busy}>
        Ответить шаблоном
      </button>
    </div>
  );
}
