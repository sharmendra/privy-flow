"""Vault errors. Messages are fixed text and never include a key, a value or a reference."""


class VaultError(Exception):
    """Base class for vault failures."""


class VaultConfigError(VaultError):
    """A key, the pepper or the API key list is missing or malformed."""


class MappingIntegrityError(VaultError):
    """A stored mapping failed authentication or is not in the expected form.

    Raised for a modified ciphertext, nonce, key version or binding, and for a key version the
    keyring does not hold. The caller must treat it as a failed restore, never as plaintext.
    """
