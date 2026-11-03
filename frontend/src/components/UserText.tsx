/**
 * Текст покупателя (сообщение, отзыв, вопрос). Только текстовый узел: React экранирует
 * разметку сам, переносы строк — через CSS `white-space: pre-line`.
 *
 * Раньше отзыв выводился через dangerouslySetInnerHTML, чтобы сохранить переносы `<br>`,
 * и `<img onerror>` из текста отзыва выполнялся в карточке (BUG-04).
 */
export function UserText({ text, className }: { text: string; className?: string }) {
  return <p className={["user-text", className].filter(Boolean).join(" ")}>{text}</p>;
}
