"""FR-07: справочник шаблонов."""


def test_list_has_seed_with_variables(client, auth):
    items = client.get("/api/templates", headers=auth).json()
    status = next(t for t in items if t["name"] == "Статус заказа")
    assert status["variables"] == ["buyer_name", "order_number"]


def test_create(client, auth):
    r = client.post("/api/templates", json={"name": "Новый", "body": "{{Buyer_Name}}, привет"}, headers=auth)
    assert r.status_code == 201
    assert r.json()["variables"] == ["buyer_name"]


def test_unknown_variable_rejected(client, auth):
    r = client.post("/api/templates", json={"name": "Плохой", "body": "{{nickname}}"}, headers=auth)
    assert r.status_code == 400
    assert "nickname" in r.json()["detail"]


def test_duplicate_name_conflict(client, auth):
    r = client.post("/api/templates", json={"name": "Гарантия", "body": "x"}, headers=auth)
    assert r.status_code == 409
