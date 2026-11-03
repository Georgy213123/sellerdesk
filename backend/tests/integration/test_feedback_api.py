"""FR-05 / US-04: отзывы и вопросы — фильтры и ответ."""

from sqlalchemy import select

from app.models import Feedback


def test_filters(client, auth, synced):
    all_ = client.get("/api/feedback?limit=200", headers=auth).json()
    assert all_["total"] == 39
    low = client.get("/api/feedback?rating=1", headers=auth).json()["items"]
    assert low and all(i["rating"] == 1 for i in low)
    questions = client.get("/api/feedback?kind=question", headers=auth).json()["items"]
    assert questions and all(i["rating"] is None for i in questions)
    unanswered = client.get("/api/feedback?answered=false&limit=200", headers=auth).json()
    answered = client.get("/api/feedback?answered=true&limit=200", headers=auth).json()
    assert unanswered["total"] + answered["total"] == 39
    assert all(i["answer_text"] for i in answered["items"])


def test_us04_answer_review(client, auth, synced, mocks):
    fb = synced.execute(select(Feedback).where(Feedback.answer_text.is_(None)).limit(1)).scalar_one()
    r = client.post(f"/api/feedback/{fb.id}/answer", json={"text": "Спасибо!"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["answer_text"] == "Спасибо!"
    assert any(log == [(fb.external_id, "Спасибо!")] for log in (m.sent_log for m in mocks.values()))


def test_second_answer_is_conflict(client, auth, synced):
    fb = synced.execute(select(Feedback).where(Feedback.answer_text.is_(None)).limit(1)).scalar_one()
    client.post(f"/api/feedback/{fb.id}/answer", json={"text": "Раз"}, headers=auth)
    r = client.post(f"/api/feedback/{fb.id}/answer", json={"text": "Два"}, headers=auth)
    assert r.status_code == 409


def test_answer_survives_resync(client, auth, synced):
    from app import cli

    fb = synced.execute(select(Feedback).where(Feedback.answer_text.is_(None)).limit(1)).scalar_one()
    client.post(f"/api/feedback/{fb.id}/answer", json={"text": "Ответ"}, headers=auth)
    cli.sync_now(synced)
    synced.refresh(fb)
    assert fb.answer_text == "Ответ"


def test_ai_draft_for_negative_review(client, auth, synced):
    fb = synced.execute(select(Feedback).where(Feedback.rating == 1).limit(1)).scalar_one()
    d = client.post(f"/api/feedback/{fb.id}/ai-draft", headers=auth).json()
    assert "замену или возврат" in d["text"]


def test_template_reply_without_buyer_name_becomes_draft(client, auth, synced, mocks):
    fb = synced.execute(
        select(Feedback).where(Feedback.buyer_name.is_(None), Feedback.kind == "review").limit(1)
    ).scalar_one()
    tpl = next(t for t in client.get("/api/templates", headers=auth).json() if t["name"] == "Спасибо за отзыв")
    r = client.post(f"/api/feedback/{fb.id}/template-reply", json={"template_id": tpl["id"]}, headers=auth).json()
    assert r["sent"] is False
    assert r["missing"] == ["buyer_name"]
    assert all(not m.sent_log for m in mocks.values())


def test_review_text_is_returned_verbatim(client, auth, synced):
    """BUG-04 на стороне API: текст отзыва отдаётся как есть, экранирует его интерфейс при выводе."""
    items = client.get("/api/feedback?limit=200", headers=auth).json()["items"]
    assert any("<img" in i["text"] for i in items)
