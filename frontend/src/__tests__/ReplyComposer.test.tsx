import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReplyComposer } from "../components/ReplyComposer";

describe("ReplyComposer (US-02, BUG-01)", () => {
  it("повтор после ошибки идёт с тем же ключом, после успеха ключ новый", async () => {
    const keys: string[] = [];
    const onSend = vi
      .fn<(text: string, key: string) => Promise<void>>()
      .mockImplementationOnce(async (_t, k) => {
        keys.push(k);
        throw new Error("сеть");
      })
      .mockImplementation(async (_t, k) => {
        keys.push(k);
      });
    const user = userEvent.setup();
    render(<ReplyComposer draft="Ответ" onSend={onSend} />);
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("сеть");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    await user.type(screen.getByRole("textbox"), "Ещё");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(keys).toHaveLength(3);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
  });

  it("подставляет черновик и показывает предупреждение шаблона", () => {
    render(
      <ReplyComposer
        draft="Заказ {{order_number}} в пути"
        note="Не отправлено: не подставились переменные order_number."
        onSend={vi.fn()}
      />,
    );
    expect(screen.getByRole("textbox")).toHaveValue("Заказ {{order_number}} в пути");
    expect(screen.getByRole("alert")).toHaveTextContent("order_number");
  });
});
