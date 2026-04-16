"""Функции шифрования чувствительных строк."""

import logging
from functools import lru_cache

from cryptography.fernet import Fernet

from config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Возвращает экземпляр Fernet."""
    return Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))


def encrypt_value(plain_text: str | None) -> str | None:
    """Шифрует строку."""
    if not plain_text:
        return plain_text
    return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted_text: str | None) -> str | None:
    """Расшифровывает строку."""
    if not encrypted_text:
        return encrypted_text
    return _get_fernet().decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
