"""Unit tests for PII hashing, normalisation and masking."""

from app.security import pii

KEY = "unit-test-key-0123456789"


def test_address_spellings_normalise_to_the_same_hash() -> None:
    a = pii.hash_address("12, M.G. Road", "Bengaluru", "560001", KEY)
    b = pii.hash_address("12 MG Rd", "bengaluru", "560001", KEY)
    assert a == b
    assert pii.normalize_address("12, M.G. Road", "Bengaluru", "560001") == "12 mg road bengaluru 560001"


def test_different_addresses_hash_differently() -> None:
    assert pii.hash_address("12 MG Road", "Bengaluru", "560001", KEY) != pii.hash_address(
        "14 MG Road", "Bengaluru", "560001", KEY
    )


def test_card_hash_ignores_formatting_and_never_contains_the_number() -> None:
    plain = pii.hash_card("4111111111111111", KEY)
    assert plain == pii.hash_card("4111 1111-1111 1111", KEY)
    assert "4111111111111111" not in plain
    assert len(plain) == 64


def test_hash_depends_on_secret_key() -> None:
    assert pii.hash_card("4111111111111111", KEY) != pii.hash_card("4111111111111111", KEY + "x")


def test_phone_normalisation_to_e164() -> None:
    assert pii.normalize_phone("098450 12345") == "+919845012345"
    assert pii.normalize_phone("9845012345") == "+919845012345"
    assert pii.normalize_phone("+91 98450-12345") == "+919845012345"
    assert pii.hash_phone("09845012345", KEY) == pii.hash_phone("+919845012345", KEY)


def test_mask_phone_keeps_last_four() -> None:
    assert pii.mask_phone("+919845012345") == "******2345"
