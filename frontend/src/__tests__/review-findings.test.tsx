// Регрессии по находкам ревью Codex (CR-NN, docs/04-ai-development.md).
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Chat, ChatListItem, Draft, SyncJob, TemplateReply } from "../api";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return {
    ...real,
    api: {
      chats: vi.fn(),
      chat: vi.fn(),
      chatDraft: vi.fn(),
      chatTemplate: vi.fn(),
      reply: vi.fn(),
      latestSync: vi.fn(),
      sync: vi.fn(),
      startSync: vi.fn(),
    },
  };
});

const { api } = await import("../api");
const { ChatsPage } = await import("../components/ChatsPage");
const { SyncButton } = await import("../components/SyncButton");
const { ReplyComposer } = await import("../components/ReplyComposer");
const mocked = vi.mocked(api);

function item(id: number, name: string): ChatListItem {
  return {
    id,
    marketplace: "ozon",
    buyer_name: name,
    product_title: "Торшер",
    order_number: null,
    status: "new",
    last_message_at: "2026-10-30T09:00:00Z",
    last_message_preview: "…",
  };
}

function chat(id: number, name: string): Chat {
  const { last_message_preview: _, ...rest } = item(id, name);
  void _;
  return {
    ...rest,
    external_id: `oz-${id}`,
    product_sku: null,
    draft_text: null,
    draft_note: null,
    messages: [],
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const TEMPLATES = [{ id: 7, name: "Статус заказа", body: "{{order_number}}", variables: [] }];

beforeEach(() => {
  vi.resetAllMocks();
  mocked.chats.mockResolvedValue({ items: [item(1, "Анна"), item(2, "Борис")], total: 2 });
  mocked.chat.mockImplementation(async (id: number) => chat(id, id === 1 ? "Анна" : "Борис"));
});

async function openChat(name: string) {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(name) }));
  await screen.findByRole("heading", { name });
}

describe("CR-02: поздний AI-черновик не попадает в другой чат", () => {
  it("черновик чата А, пришедший после открытия Б, в поле Б не появляется", async () => {
    const late = deferred<Draft>();
    mocked.chatDraft.mockReturnValue(late.promise);
    render(<ChatsPage templates={[]} refreshToken={0} />);
    await openChat("Анна");
    fireEvent.click(screen.getByRole("button", { name: "AI-черновик" }));
    await openChat("Борис");
    await act(async () => late.resolve({ text: "Черновик для Анны", provider: "stub", note: "" }));
    expect(screen.getByRole("textbox", { name: "Текст ответа" })).toHaveValue("");
  });
});

describe("CR-09: открытая карточка обновляется после синхронизации", () => {
  it("смена refreshToken перечитывает карточку", async () => {
    const { rerender } = render(<ChatsPage templates={[]} refreshToken={0} />);
    await openChat("Анна");
    const before = mocked.chat.mock.calls.length;
    rerender(<ChatsPage templates={[]} refreshToken={1} />);
    await waitFor(() => expect(mocked.chat.mock.calls.length).toBeGreaterThan(before));
  });
});

describe("CR-04: повтор шаблона после сетевой ошибки идёт с тем же ключом", () => {
  it("два нажатия после ошибки — один ключ", async () => {
    mocked.chatTemplate
      .mockRejectedValueOnce(new Error("сеть"))
      .mockResolvedValue({ sent: true, text: "ok", missing: [], note: null } as TemplateReply);
    render(<ChatsPage templates={TEMPLATES} refreshToken={0} />);
    await openChat("Анна");
    fireEvent.change(screen.getByLabelText("Шаблон"), { target: { value: "7" } });
    const button = screen.getByRole("button", { name: "Ответить шаблоном" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(mocked.chatTemplate).toHaveBeenCalledTimes(2));
    const [first, second] = mocked.chatTemplate.mock.calls.map((c) => c[2]);
    expect(first).toBe(second);
  });
});

describe("CR-10: лента не обрезается первой сотней", () => {
  it("«Показать ещё» запрашивает следующую страницу", async () => {
    const page1 = Array.from({ length: 100 }, (_, i) => item(i + 1, `Покупатель ${i + 1}`));
    mocked.chats
      .mockResolvedValueOnce({ items: page1, total: 101 })
      .mockResolvedValueOnce({ items: [item(101, "Последний")], total: 101 });
    render(<ChatsPage templates={[]} refreshToken={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /Показать ещё/ }));
    expect(await screen.findByRole("button", { name: /Последний/ })).toBeInTheDocument();
    expect(mocked.chats).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100 }));
  });
});

describe("CR-08: активная задача при загрузке страницы опрашивается", () => {
  it("кнопка разблокируется, когда задача завершилась", async () => {
    const running: SyncJob = {
      id: 5,
      status: "running",
      created_at: "2026-11-03T10:00:00Z",
      finished_at: null,
      chats_upserted: 0,
      messages_inserted: 0,
      feedback_upserted: 0,
      error: null,
    };
    mocked.latestSync.mockResolvedValue(running);
    mocked.sync.mockResolvedValue({
      ...running,
      status: "done",
      finished_at: "2026-11-03T10:01:00Z",
    });
    const onDone = vi.fn();
    render(<SyncButton onDone={onDone} />);
    expect(await screen.findByRole("button", { name: "Синхронизация…" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled(), {
      timeout: 3000,
    });
    expect(onDone).toHaveBeenCalled();
  });
});

describe("CR-05: правка текста после ошибки даёт новый ключ", () => {
  it("тот же текст — тот же ключ, другой текст — новый", async () => {
    const keys: string[] = [];
    const onSend = vi.fn(async (_t: string, k: string) => {
      keys.push(k);
      throw new Error("сеть");
    });
    const user = userEvent.setup();
    render(<ReplyComposer draft="Ответ A" onSend={onSend} />);
    const send = screen.getByRole("button", { name: "Отправить" });
    await user.click(send);
    await user.click(send);
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "Ответ B");
    await user.click(send);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
  });
});

describe("CR-13: два submit до перерисовки — один запрос", () => {
  it("синхронная защита, а не disabled, держит второй submit", () => {
    const onSend = vi.fn(() => new Promise<void>(() => {}));
    const { container } = render(<ReplyComposer draft="Ответ" onSend={onSend} />);
    const form = container.querySelector("form");
    if (!form) throw new Error("нет формы");
    act(() => {
      // оба события в одном act: React не перерисует кнопку между ними
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});
