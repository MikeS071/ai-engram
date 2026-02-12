from social_scheduler.core.hashing import content_hash, idempotency_key


def test_content_hash_is_stable_under_whitespace_variations():
    a = "Hello  world\n\n\nThis is a test."
    b = "Hello world\n\nThis is a test.\n"
    assert content_hash(a) == content_hash(b)


def test_idempotency_key_is_deterministic():
    key1 = idempotency_key("camp_1", "x", "abc123")
    key2 = idempotency_key("camp_1", "x", "abc123")
    assert key1 == key2
