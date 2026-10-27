from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hashing_roundtrip():
    password_hash = hash_password("CorrectHorseBatteryStaple!")

    assert password_hash != "CorrectHorseBatteryStaple!"
    assert verify_password("CorrectHorseBatteryStaple!", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_access_token_contains_subject():
    token = create_access_token(
        subject="00000000-0000-0000-0000-000000000001",
        extra_claims={"roles": ["Super Admin"]},
    )

    payload = decode_token(token, "access")

    assert payload["sub"] == "00000000-0000-0000-0000-000000000001"
    assert payload["roles"] == ["Super Admin"]
