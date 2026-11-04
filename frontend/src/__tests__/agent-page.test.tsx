// Вкладка «Агент»: прогоны, предложения на согласование, кнопки вызывают API.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AgentRun, Proposal } from "../api";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return {
    ...real,
    api: {
      agentRuns: vi.fn(),
      agentProposals: vi.fn(),
      startAgentRun: vi.fn(),
      approveProposal: vi.fn(),
      rejectProposal: vi.fn(),
    },
  };
});

const real = await import("../api");
const { api } = real;
const { AgentPage } = await import("../components/AgentPage");
const mocked = vi.mocked(api);

function run(over: Partial<AgentRun> = {}): AgentRun {
  return {
    id: 3,
    status: "succeeded",
    period_from: "2026-10-23T09:00:00Z",
    period_to: "2026-10-30T09:00:00Z",
    steps_done: 9,
    max_steps: 40,
    tokens_used: 1234,
    token_budget: 60000,
    error: null,
    created_at: "2026-10-30T09:00:00Z",
    finished_at: "2026-10-30T09:01:00Z",
    ...over,
  };
}

function proposal(over: Partial<Proposal> = {}): Proposal {
  return {
    id: 11,
    run_id: 3,
    theme_key: "delivery",
    kind: "reply_template",
    title: "Задержка доставки",
    body: "Заказ в пути.",
    evidence: { cases: 4, feedback_ids: [5, 8], message_ids: [21] },
    status: "pending",
    created_at: "2026-10-30T09:01:00Z",
    ...over,
  };
}

async function cardAt(index: number): Promise<HTMLElement> {
  const card = (await screen.findAllByTestId("proposal"))[index];
  if (!card) throw new Error(`нет предложения №${index}`);
  return card;
}

const onTemplateCreated = vi.fn(async () => undefined);

beforeEach(() => {
  vi.resetAllMocks();
  mocked.agentRuns.mockResolvedValue([run()]);
  mocked.agentProposals.mockResolvedValue([
    proposal(),
    proposal({
      id: 12,
      kind: "card_edit",
      title: "Уточнить цвет",
      evidence: { cases: 2, feedback_ids: [1], message_ids: [] },
    }),
  ]);
});

describe("вкладка «Агент»", () => {
  it("показывает прогоны с шагами и токенами и предложения с доказательствами", async () => {
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);

    const item = await screen.findByTestId("agent-run");
    expect(item).toHaveTextContent("готово");
    expect(item).toHaveTextContent("Шаги 9 из 40");
    expect(item).toHaveTextContent("Токены 1234 из 60000");

    const cards = await screen.findAllByTestId("proposal");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("Шаблон ответа");
    expect(cards[0]).toHaveTextContent("Случаев: 4");
    expect(cards[0]).toHaveTextContent("Отзывы и вопросы: №5, №8");
    expect(cards[0]).toHaveTextContent("Сообщения: №21");
    expect(cards[1]).toHaveTextContent("Правка карточки");
  });

  it("«Запустить разбор» ставит прогон и перечитывает список", async () => {
    mocked.startAgentRun.mockResolvedValue(run({ id: 4, status: "queued" }));
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);
    await screen.findByTestId("agent-run");

    await userEvent.click(screen.getByRole("button", { name: "Запустить разбор" }));

    expect(mocked.startAgentRun).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(mocked.agentRuns).toHaveBeenCalledTimes(2));
  });

  it("пока прогон идёт, кнопка заблокирована", async () => {
    mocked.agentRuns.mockResolvedValue([run({ status: "running" })]);
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);

    expect(await screen.findByRole("button", { name: "Идёт разбор…" })).toBeDisabled();
  });

  it("«Одобрить» шаблон вызывает API и обновляет список шаблонов", async () => {
    mocked.approveProposal.mockResolvedValue(proposal({ status: "approved" }));
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);
    const card = await cardAt(0);

    await userEvent.click(within(card).getByRole("button", { name: "Одобрить" }));

    expect(mocked.approveProposal).toHaveBeenCalledWith(11);
    await waitFor(() => expect(onTemplateCreated).toHaveBeenCalledTimes(1));
  });

  it("одобрение правки карточки не трогает шаблоны", async () => {
    mocked.approveProposal.mockResolvedValue(proposal({ id: 12, status: "approved" }));
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);
    const card = await cardAt(1);

    await userEvent.click(within(card).getByRole("button", { name: "Одобрить" }));

    expect(mocked.approveProposal).toHaveBeenCalledWith(12);
    await waitFor(() => expect(mocked.agentProposals).toHaveBeenCalledTimes(2));
    expect(onTemplateCreated).not.toHaveBeenCalled();
  });

  it("«Отклонить» вызывает API", async () => {
    mocked.rejectProposal.mockResolvedValue(proposal({ status: "rejected" }));
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);
    const card = await cardAt(0);

    await userEvent.click(within(card).getByRole("button", { name: "Отклонить" }));

    expect(mocked.rejectProposal).toHaveBeenCalledWith(11);
  });

  it("ошибка сервера показывается оператору", async () => {
    mocked.approveProposal.mockRejectedValue(
      new real.ApiError(409, "по предложению уже есть решение"),
    );
    render(<AgentPage onTemplateCreated={onTemplateCreated} />);
    const card = await cardAt(0);

    await userEvent.click(within(card).getByRole("button", { name: "Одобрить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("по предложению уже есть решение");
  });

  describe("опрос во время разбора", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

    it("одна ошибка 503 не останавливает опрос", async () => {
      mocked.agentRuns
        .mockResolvedValueOnce([run({ status: "running" })])
        .mockRejectedValueOnce(new real.ApiError(503, "недоступно"))
        .mockResolvedValueOnce([run({ status: "running" })])
        .mockResolvedValue([run({ status: "succeeded" })]);
      render(<AgentPage onTemplateCreated={onTemplateCreated} />);
      await tick(0);
      expect(screen.getByRole("button", { name: "Идёт разбор…" })).toBeDisabled();

      await tick(1000); // запрос упал
      await tick(1000); // опрос продолжился
      await tick(1000);

      expect(mocked.agentRuns.mock.calls.length).toBeGreaterThanOrEqual(4);
      expect(screen.getByRole("button", { name: "Запустить разбор" })).toBeEnabled();
    });

    it("при размонтировании опрос прекращается", async () => {
      mocked.agentRuns.mockResolvedValue([run({ status: "running" })]);
      const { unmount } = render(<AgentPage onTemplateCreated={onTemplateCreated} />);
      await tick(0);
      await tick(1000);
      unmount();
      const calls = mocked.agentRuns.mock.calls.length;

      await tick(5000);

      expect(mocked.agentRuns).toHaveBeenCalledTimes(calls);
    });
  });
});
