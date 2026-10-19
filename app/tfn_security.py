import os
import re

from cryptography.fernet import Fernet


TFN_WEIGHTS = (1, 4, 3, 7, 5, 8, 6, 9, 10)


def normalise_tfn(value: str) -> str:
    return re.sub(r"[ -]", "", value.strip())


def valid_tfn(value: str) -> bool:
    digits = normalise_tfn(value)

    if not digits.isascii() or not digits.isdigit():
        return False

    if len(digits) == 8:
        digits = "0" + digits
    elif len(digits) != 9:
        return False

    return sum(
        int(digit) * weight
        for digit, weight in zip(digits, TFN_WEIGHTS)
    ) % 11 == 0


def canonical_tfn(value: str) -> str:
    digits = normalise_tfn(value)

    if not valid_tfn(digits):
        raise ValueError("Invalid Australian TFN")

    return digits.zfill(9)


def get_cipher() -> Fernet:
    key = os.environ.get("GREEN_ORBIT_TFN_KEY")

    if not key:
        raise RuntimeError(
            "TFN encryption key is not configured"
        )

    return Fernet(key.encode("ascii"))


def encrypt_tfn(value: str) -> bytes:
    return get_cipher().encrypt(
        canonical_tfn(value).encode("ascii")
    )


def mask_tfn(last_three: str) -> str:
    return "*** *** " + last_three
