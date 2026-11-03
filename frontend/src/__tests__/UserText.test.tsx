import { render, screen } from "@testing-library/react";
import { FeedbackItem } from "../components/FeedbackPage";
import type { Feedback } from "../api";

const xss = "Отличная лампа <img src=x onerror=alert('xss')> всем советую";

const review: Feedback = {
  id: 1,
  marketplace: "ozon",
  kind: "review",
  product_title: "Торшер «Дуга»",
  buyer_name: "Анна",
  rating: 5,
  text: xss,
  created_at: "2026-10-30T09:00:00Z",
  answer_text: null,
  answered_at: null,
  draft_text: null,
  draft_note: null,
};

describe("BUG-04: текст отзыва не исполняется как HTML (US-04)", () => {
  it("показывает разметку буквально и не создаёт <img>", () => {
    const { container } = render(
      <ul>
        <FeedbackItem
          item={review}
          open={false}
          onToggle={() => {}}
          templates={[]}
          onChanged={async () => {}}
        />
      </ul>,
    );
    expect(screen.getByText(xss)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("сохраняет переносы строк без <br>", () => {
    const { container } = render(
      <ul>
        <FeedbackItem
          item={{ ...review, text: "строка 1\nстрока 2" }}
          open={false}
          onToggle={() => {}}
          templates={[]}
          onChanged={async () => {}}
        />
      </ul>,
    );
    expect(container.querySelector("br")).toBeNull();
    expect(container.querySelector(".user-text")?.textContent).toBe("строка 1\nстрока 2");
  });
});
