import { formatTime } from "../format";

describe("formatTime (BUG-02)", () => {
  it("показывает UTC-время в зоне оператора", () => {
    expect(formatTime("2026-10-30T21:30:00+00:00", "Europe/Moscow")).toBe("31.10, 00:30");
  });

  it("одинаковый момент в разных записях даёт одинаковый вывод", () => {
    expect(formatTime("2026-10-30T09:20:00Z", "UTC")).toBe(
      formatTime("2026-10-30T12:20:00+03:00", "UTC"),
    );
  });

  it("мусор не роняет интерфейс", () => {
    expect(formatTime("not-a-date")).toBe("—");
  });
});
