---
description: Приёмка истории на стенде через Playwright MCP
argument-hint: <US-NN>
---

1. Убедись, что стенд поднят (`make up`) и отвечает `/health`.
2. Отдай агенту `e2e-acceptor` историю $ARGUMENTS с её критериями приёмки.
3. Для каждого «не выполнен» открой баг по шаблону `.github/ISSUE_TEMPLATE/bug_report.yml`.
4. Если сценарий проходит, а e2e-теста на него нет, предложи тест в `e2e/`.
