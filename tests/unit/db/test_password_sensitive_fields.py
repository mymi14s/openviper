"""Unit tests for PasswordField and SensitiveField."""

from __future__ import annotations

import pytest

from openviper.db.fields import CharField, PasswordField, SensitiveField
from openviper.db.models import Model, ModelMeta
from openviper.exceptions import FieldError
from openviper.testing.settings import override_openviper_settings

TEST_SECRET_KEY = "test-secret-key-for-encryption-testing-only-1234567890"


@pytest.fixture(autouse=True)
def reset_registry():
    old_reg = ModelMeta.registry.copy()
    old_index = ModelMeta.name_index.copy()
    ModelMeta.registry.clear()
    ModelMeta.name_index.clear()
    yield
    ModelMeta.registry = old_reg
    ModelMeta.name_index = old_index



class TestPasswordFieldConfiguration:
    """PasswordField stores one-way hashes and enforces plaintext length."""

    def test_column_type_is_varchar(self):
        field = PasswordField()
        assert field.column_type.startswith("VARCHAR")

    def test_defaults_to_nullable(self):
        field = PasswordField()
        assert field.null is True

    def test_default_min_length_is_4(self):
        field = PasswordField()
        assert field.min_length == 4

    def test_default_plaintext_max_is_128(self):
        field = PasswordField()
        assert field._plaintext_max == 128

    def test_custom_min_length(self):
        field = PasswordField(min_length=10)
        assert field.min_length == 10

    def test_custom_max_length(self):
        field = PasswordField(max_length=200)
        assert field.max_length == 200


class TestPasswordFieldValidation:
    """Plaintext values are length-checked; hashes bypass validation."""

    def test_validate_accepts_argon2_hash(self):
        field = PasswordField()
        field.name = "password"
        field.validate("argon2$somehashvalue")

    def test_validate_accepts_bcrypt_hash(self):
        field = PasswordField()
        field.name = "password"
        field.validate("bcrypt$somehashvalue")

    def test_validate_accepts_plain_hash(self):
        field = PasswordField()
        field.name = "password"
        field.validate("plain$somehashvalue")

    def test_validate_rejects_short_plaintext(self):
        field = PasswordField(min_length=8)
        field.name = "password"
        with pytest.raises(ValueError, match="at least 8"):
            field.validate("short")

    def test_validate_rejects_oversized_plaintext(self):
        field = PasswordField()
        field.name = "password"
        with pytest.raises(ValueError, match="exceed"):
            field.validate("x" * 200)

    def test_validate_accepts_none_when_nullable(self):
        field = PasswordField()
        field.name = "password"
        field.validate(None)

    def test_validate_rejects_none_when_not_nullable(self):
        field = PasswordField(null=False)
        field.name = "password"
        with pytest.raises(ValueError, match="cannot be null"):
            field.validate(None)

    def test_validate_accepts_valid_plaintext(self):
        field = PasswordField(min_length=4)
        field.name = "password"
        field.validate("validpassword")


class TestPasswordFieldToPython:
    """to_python converts values to string."""

    def test_to_python_returns_string(self):
        field = PasswordField()
        assert field.to_python("hello") == "hello"

    def test_to_python_returns_none(self):
        field = PasswordField()
        assert field.to_python(None) is None

    def test_to_python_coerces_int(self):
        field = PasswordField()
        assert field.to_python(123) == "123"


# ---------------------------------------------------------------------------
# SensitiveField (encrypted, retrievable)
# ---------------------------------------------------------------------------


class TestSensitiveFieldConfiguration:
    """SensitiveField stores encrypted values with Fernet."""

    def test_column_type_is_varchar(self):
        field = SensitiveField()
        assert field.column_type.startswith("VARCHAR")

    def test_defaults_to_nullable(self):
        field = SensitiveField()
        assert field.null is True

    def test_default_max_length_is_512(self):
        field = SensitiveField()
        assert field.max_length == 512

    def test_custom_max_length(self):
        field = SensitiveField(max_length=1024)
        assert field.max_length == 1024

    def test_encrypted_prefix(self):
        field = SensitiveField()
        assert field._ENCRYPTED_PREFIX == "enc$"


class TestSensitiveFieldEncryption:
    """Encrypt/decrypt round-trip with Fernet symmetric encryption."""

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            field = SensitiveField()
            field.name = "api_key"
            encrypted = field.encrypt("sk-live-abc123")
            assert encrypted.startswith("enc$")
            assert encrypted != "sk-live-abc123"
            assert field.decrypt(encrypted) == "sk-live-abc123"

    @pytest.mark.asyncio
    async def test_to_db_encrypts_plaintext(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            field = SensitiveField()
            field.name = "api_key"
            result = field.to_db("plaintext-secret")
            assert result.startswith("enc$")
            assert field.decrypt(result) == "plaintext-secret"

    @pytest.mark.asyncio
    async def test_to_db_passes_through_already_encrypted(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            field = SensitiveField()
            field.name = "api_key"
            encrypted = field.encrypt("my-secret")
            result = field.to_db(encrypted)
            assert result == encrypted

    @pytest.mark.asyncio
    async def test_to_db_returns_none_for_none(self):
        field = SensitiveField()
        assert field.to_db(None) is None

    @pytest.mark.asyncio
    async def test_decrypt_rejects_non_encrypted_value(self):
        field = SensitiveField()
        field.name = "api_key"
        with pytest.raises(ValueError, match="not an encrypted token"):
            field.decrypt("plaintext-without-prefix")

    @pytest.mark.asyncio
    async def test_decrypt_rejects_corrupted_token(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            field = SensitiveField()
            field.name = "api_key"
            with pytest.raises(ValueError, match="failed to decrypt"):
                field.decrypt("enc$corrupted-data-here")

    @pytest.mark.asyncio
    async def test_decrypt_rejects_wrong_key(self):
        with override_openviper_settings(SECRET_KEY="first-key-1234567890"):
            field = SensitiveField()
            field.name = "api_key"
            encrypted = field.encrypt("my-secret")

        with override_openviper_settings(SECRET_KEY="different-key-9876543210"):
            with pytest.raises(ValueError, match="failed to decrypt"):
                field.decrypt(encrypted)

    @pytest.mark.asyncio
    async def test_get_fernet_key_requires_secret_key(self):
        with override_openviper_settings(SECRET_KEY=""):
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                SensitiveField.get_fernet_key()

    @pytest.mark.asyncio
    async def test_get_fernet_key_is_deterministic(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            key1 = SensitiveField.get_fernet_key()
            key2 = SensitiveField.get_fernet_key()
            assert key1 == key2

    @pytest.mark.asyncio
    async def test_different_secret_keys_produce_different_encryption(self):
        with override_openviper_settings(SECRET_KEY="key-one-1234567890"):
            field = SensitiveField()
            field.name = "api_key"
            enc1 = field.encrypt("same-plaintext")

        with override_openviper_settings(SECRET_KEY="key-two-9876543210"):
            enc2 = field.encrypt("same-plaintext")

        assert enc1 != enc2


class TestSensitiveFieldToPython:
    """to_python converts values to string."""

    def test_to_python_returns_string(self):
        field = SensitiveField()
        assert field.to_python("enc$abc") == "enc$abc"

    def test_to_python_returns_none(self):
        field = SensitiveField()
        assert field.to_python(None) is None


# ---------------------------------------------------------------------------
# Model.get_sensitive integration
# ---------------------------------------------------------------------------


class _SecretModel(Model):
    _app_name = "test"

    name = CharField(max_length=50)
    api_key = SensitiveField()
    user_password = PasswordField()

    class Meta:
        table_name = "test_secret_model"


class TestModelGetSensitive:
    """Model.get_sensitive decrypts SensitiveField values."""

    @pytest.mark.asyncio
    async def test_get_sensitive_returns_plaintext_for_encrypted_value(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            inst = _SecretModel(name="x")
            sf = inst._fields["api_key"]
            encrypted = sf.encrypt("sk-live-abc123")
            inst.api_key = encrypted
            assert inst.get_sensitive("api_key") == "sk-live-abc123"

    @pytest.mark.asyncio
    async def test_get_sensitive_returns_plaintext_for_in_memory_value(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            inst = _SecretModel(name="x")
            inst.api_key = "sk-in-memory"
            assert inst.get_sensitive("api_key") == "sk-in-memory"

    @pytest.mark.asyncio
    async def test_get_sensitive_returns_none_for_empty_field(self):
        inst = _SecretModel(name="x")
        assert inst.get_sensitive("api_key") is None

    @pytest.mark.asyncio
    async def test_get_sensitive_raises_for_password_field(self):
        inst = _SecretModel(name="x")
        inst.user_password = "argon2$hash"
        with pytest.raises(FieldError, match="not a SensitiveField"):
            inst.get_sensitive("user_password")

    @pytest.mark.asyncio
    async def test_get_sensitive_raises_for_non_secret_field(self):
        inst = _SecretModel(name="x")
        with pytest.raises(FieldError, match="not a SensitiveField"):
            inst.get_sensitive("name")

    @pytest.mark.asyncio
    async def test_get_sensitive_raises_for_nonexistent_field(self):
        inst = _SecretModel(name="x")
        with pytest.raises(FieldError, match="no field"):
            inst.get_sensitive("nonexistent")

    @pytest.mark.asyncio
    async def test_get_sensitive_roundtrip_after_to_db(self):
        with override_openviper_settings(SECRET_KEY=TEST_SECRET_KEY):
            inst = _SecretModel(name="x")
            sf = inst._fields["api_key"]
            stored = sf.to_db("sk-roundtrip")
            inst.api_key = stored
            assert inst.get_sensitive("api_key") == "sk-roundtrip"
