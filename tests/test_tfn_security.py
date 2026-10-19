import pytest

from cryptography.fernet import Fernet

from app.tfn_security import (
    canonical_tfn,
    encrypt_tfn,
    mask_tfn,
    valid_tfn,
)


def test_valid_tfn():
    assert valid_tfn("123 456 782")
    assert canonical_tfn("123 456 782") == "123456782"


def test_invalid_tfn():
    assert not valid_tfn("123456789")
    assert not valid_tfn("12345678X")
    assert not valid_tfn("")


def test_masking():
    assert mask_tfn("782") == "*** *** 782"


def test_encryption(monkeypatch):
    key = Fernet.generate_key()

    monkeypatch.setenv(
        "GREEN_ORBIT_TFN_KEY",
        key.decode(),
    )

    ciphertext = encrypt_tfn("123456782")

    assert b"123456782" not in ciphertext

    assert Fernet(key).decrypt(
        ciphertext
    ) == b"123456782"


def test_missing_key(monkeypatch):
    monkeypatch.delenv(
        "GREEN_ORBIT_TFN_KEY",
        raising=False,
    )

    with pytest.raises(RuntimeError):
        encrypt_tfn("123456782")
