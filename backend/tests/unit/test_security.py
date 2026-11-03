from app.security import create_token, decode_token, hash_password, verify_password


def test_password_roundtrip():
    h = hash_password("secret-1")
    assert verify_password("secret-1", h)
    assert not verify_password("secret-2", h)


def test_garbage_hash_rejected():
    assert not verify_password("x", "not-a-hash")


def test_token_roundtrip():
    assert decode_token(create_token(42)) == 42


def test_tampered_token_rejected():
    token = create_token(42)
    assert decode_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb")) is None
