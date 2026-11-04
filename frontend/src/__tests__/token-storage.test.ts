// SD-06: если sessionStorage недоступен, токен живёт в памяти модуля.
import { getToken, setToken } from "../api";

describe("токен без sessionStorage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setToken(null);
  });

  it("при SecurityError токен остаётся в памяти", () => {
    const boom = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(boom);
    setToken("abc");
    expect(getToken()).toBe("abc");
    setToken(null);
    expect(getToken()).toBeNull();
  });

  it("при рабочем хранилище дублирует токен в sessionStorage", () => {
    setToken("xyz");
    expect(sessionStorage.getItem("sellerdesk.token")).toBe("xyz");
    expect(getToken()).toBe("xyz");
  });
});
