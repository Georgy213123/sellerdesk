// BUG-11: статус в карточке расходился с бейджем в ленте после AI-черновика.
import { fireEvent, render, screen } from "@testing-library/react";
import type { Chat, ChatListItem, ChatStatus } from "../api";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { chats: vi.fn(), chat: vi.fn(), chatDraft: vi.fn() } };
});

const { api } = await import("../api");
const { ChatsPage } = await import("../components/ChatsPage");
const mocked = vi.mocked(api);

let status: ChatStatus = "new";

function item(): ChatListItem {
  return {
    id: 1,
    marketplace: "ozon",
    buyer_name: "Анна",
    product_title: "Торшер",
    order_number: null,
    status,
    last_message_at: "2026-10-30T09:00:00Z",
    last_message_preview: "…",
  };
}

function chat(): Chat {
  const { last_message_preview: _, ...rest } = item();
  void _;
  return {
    ...rest,
    external_id: "oz-1",
    product_sku: null,
    draft_text: null,
    draft_note: null,
    messages: [],
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  status = "new";
  mocked.chats.mockImplementation(async () => ({ items: [item()], total: 1 }));
  mocked.chat.mockImplementation(async () => chat());
  mocked.chatDraft.mockImplementation(async () => {
    status = "in_progress"; // сервер переводит чат в работу, сохраняя черновик
    return { text: "Черновик", provider: "stub", note: "" };
  });
});

describe("BUG-11: статус карточки после AI-черновика", () => {
  it("карточка и лента показывают «В работе»", async () => {
    render(<ChatsPage templates={[]} refreshToken={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /Анна/ }));
    expect(await screen.findByTestId("card-status")).toHaveTextContent("Новый");
    fireEvent.click(screen.getByRole("button", { name: "AI-черновик" }));
    expect(await screen.findByRole("textbox", { name: "Текст ответа" })).toHaveValue("Черновик");
    expect(
      await screen.findByText("В работе", { selector: "[data-testid=chat-status]" }),
    ).toBeVisible();
    expect(
      await screen.findByText("В работе", { selector: "[data-testid=card-status]" }),
    ).toBeVisible();
  });
});
