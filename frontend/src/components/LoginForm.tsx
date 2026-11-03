import { useState } from "react";
import { ApiError, api, setToken, type Operator } from "../api";

export function LoginForm({ onLogin }: { onLogin: (op: Operator) => void }) {
  const [login, setLogin] = useState("operator");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.login(login, password);
      setToken(res.access_token);
      onLogin(res.operator);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Сервер недоступен");
    }
  }

  return (
    <form className="login" onSubmit={submit}>
      <h1>SellerDesk</h1>
      <p className="muted">Вход оператора</p>
      <label>
        Логин
        <input value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" />
      </label>
      <label>
        Пароль
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit">Войти</button>
    </form>
  );
}
