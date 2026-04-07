from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from models.database import Base
from utils.encryption import encrypt_value, decrypt_value


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=22)
    username = Column(String(100), nullable=False)

    # Зашифрованные колонки (в БД хранятся только ciphertext)
    _password_encrypted = Column("password", String, nullable=True)
    _ssh_key_encrypted = Column("ssh_key", String, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ------------------------------------------------------------------
    # Properties — прозрачное шифрование при записи / расшифрование при чтении
    # ------------------------------------------------------------------

    @property
    def password(self) -> str | None:
        """Возвращает расшифрованный пароль."""
        return decrypt_value(self._password_encrypted)

    @password.setter
    def password(self, plain_text: str | None) -> None:
        """Шифрует и сохраняет пароль."""
        self._password_encrypted = encrypt_value(plain_text)

    @property
    def ssh_key(self) -> str | None:
        """Возвращает расшифрованный SSH-ключ."""
        return decrypt_value(self._ssh_key_encrypted)

    @ssh_key.setter
    def ssh_key(self, plain_text: str | None) -> None:
        """Шифрует и сохраняет SSH-ключ."""
        self._ssh_key_encrypted = encrypt_value(plain_text)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<Server(id={self.id}, name='{self.name}', "
            f"host='{self.host}', active={self.is_active})>"
        )
