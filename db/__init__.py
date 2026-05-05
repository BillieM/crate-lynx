"""Database helpers shared by Alembic and the app runtime."""

__all__ = ["decrypt_token", "encrypt_token"]


def __getattr__(name: str):
    if name == "encrypt_token":
        from .crypto import encrypt_token

        return encrypt_token

    if name == "decrypt_token":
        from .crypto import decrypt_token

        return decrypt_token

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
