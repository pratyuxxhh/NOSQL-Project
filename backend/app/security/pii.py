"""PII protection: hashing and masking of card numbers, phone numbers and addresses.

Hashes are HMAC-SHA256 with a secret key (PII_HASH_KEY). A plain SHA-256 of a
card or phone number could be reversed by hashing every possible number; the
secret key prevents that while keeping hashes stable, so the same card always
maps to the same Card node.
"""

import hashlib
import hmac
import re

# Common abbreviations, so "12 MG Rd" and "12, M.G. Road" normalise identically.
_ADDRESS_ABBREVIATIONS = {
    "rd": "road",
    "st": "street",
    "ave": "avenue",
    "apt": "apartment",
    "apts": "apartments",
    "nr": "near",
    "opp": "opposite",
}


def keyed_hash(value: str, key: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def hash_card(card_number: str, key: str) -> str:
    """Hash a card number; spaces and dashes are ignored."""
    return keyed_hash(re.sub(r"\D", "", card_number), key)


def normalize_phone(raw: str, default_country_code: str = "91") -> str:
    """Return E.164 form, e.g. '098450 12345' -> '+919845012345'."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return "+" + digits
    digits = digits.lstrip("0")
    if len(digits) == 10:
        digits = default_country_code + digits
    return "+" + digits


def hash_phone(raw: str, key: str) -> str:
    return keyed_hash(normalize_phone(raw), key)


def mask_phone(raw: str) -> str:
    """Keep only the last 4 digits for display: '******4321'."""
    digits = re.sub(r"\D", "", raw)
    return "*" * 6 + digits[-4:]


def normalize_address(line: str, city: str, pincode: str) -> str:
    """Lowercase, drop dots ('M.G.' -> 'mg'), turn other punctuation into spaces,
    expand common abbreviations and collapse whitespace."""
    text = f"{line} {city} {pincode}".lower().replace(".", "")
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join(_ADDRESS_ABBREVIATIONS.get(word, word) for word in words)


def hash_address(line: str, city: str, pincode: str, key: str) -> str:
    return keyed_hash(normalize_address(line, city, pincode), key)
