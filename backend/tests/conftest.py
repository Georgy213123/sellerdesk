import os

# Тесты не ждут искусственную задержку площадки.
os.environ.setdefault("MOCK_MARKETPLACE_DELAY_MS", "0")
