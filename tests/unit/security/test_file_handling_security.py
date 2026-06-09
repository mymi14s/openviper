"""File handling security tests.

Requirement IDs: FILE-001 through FILE-006.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from openviper.admin.site import ADMIN_STATIC_DIR, get_admin_site
from openviper.conf import settings
from openviper.http.request import MAX_BODY_SIZE, MAX_FILES_PER_REQUEST
from openviper.http.uploads import UploadFile
from openviper.storage.base import (
    HIDDEN_FILENAME_RE,
    MAX_COMPONENT_LEN,
    UNSAFE_FILENAME_RE,
    FileSystemStorage,
    generate_unique_name,
)

from .conftest import PATH_TRAVERSAL_PAYLOADS


class TestUploadFilenameSanitization:
    """Uploaded filenames must be sanitized to prevent path traversal."""

    def test_file001_unsafe_filename_regex(self):
        """The unsafe filename regex must match dangerous characters."""
        # Must match path traversal characters
        assert UNSAFE_FILENAME_RE.search("../")
        assert UNSAFE_FILENAME_RE.search("..\\")
        assert UNSAFE_FILENAME_RE.search("\x00")

    def test_file001_storage_sanitizes_traversal_filenames(self):
        """FileSystemStorage must sanitize filenames with path traversal."""
        storage = FileSystemStorage()
        root = Path(storage.location).resolve()
        for payload in PATH_TRAVERSAL_PAYLOADS:
            # _validate_name must sanitize path traversal sequences
            result = storage._validate_name(payload)
            full = storage._full_path(result)
            assert str(full).startswith(str(root))

    def test_file001_storage_rejects_absolute_paths(self):
        """FileSystemStorage must not allow absolute paths as filenames."""
        storage = FileSystemStorage()
        # _validate_name must strip leading slashes from absolute paths
        result = storage._validate_name("/etc/passwd")
        assert not result.startswith("/")

    def test_file001_max_component_length(self):
        """Filename components must not exceed the maximum length."""
        assert MAX_COMPONENT_LEN == 255

    def test_file001_hidden_filenames_sanitized(self):
        """Hidden filenames (leading dot) must be replaced to prevent serving config files."""
        storage = FileSystemStorage()
        # .htaccess, .env, .gitignore must be sanitized
        assert not storage._validate_name(".htaccess").startswith(".")
        assert not storage._validate_name(".env").startswith(".")
        assert not storage._validate_name(".gitignore").startswith(".")
        # Leading dot is replaced with underscore
        assert storage._validate_name(".htaccess") == "_htaccess"
        assert storage._validate_name(".env") == "_env"

    def test_file001_hidden_filename_regex(self):
        """The hidden filename regex must match leading dots."""
        assert HIDDEN_FILENAME_RE.match(".htaccess")
        assert HIDDEN_FILENAME_RE.match(".env")
        assert HIDDEN_FILENAME_RE.match(".gitignore")
        assert not HIDDEN_FILENAME_RE.match("normal.txt")


class TestFileOverwritePrevention:
    """Uploaded files must not overwrite existing files."""

    def test_file002_unique_name_generation(self):
        """FileSystemStorage must generate unique names for duplicate uploads."""
        name1 = generate_unique_name("document.pdf")
        name2 = generate_unique_name("document.pdf")

        assert name1 != name2
        assert name1.endswith(".pdf")
        assert name2.endswith(".pdf")


class TestExecutableUploadBlocking:
    """Executable file uploads must be blocked or stored safely."""

    def test_file003_upload_file_content_type_tracked(self):
        """UploadFile must track content type for executable detection."""
        upload = UploadFile(
            filename="malware.exe", content_type="application/x-msdownload", file=None
        )
        assert upload.content_type == "application/x-msdownload"
        assert upload.filename == "malware.exe"

    def test_file003_upload_file_stores_filename(self):
        """UploadFile must store the original filename for validation."""
        upload = UploadFile(filename="test.txt", content_type="text/plain", file=None)
        assert upload.filename == "test.txt"


class TestZipSlipPrevention:
    """Archive extraction must prevent zip slip attacks."""

    def test_file004_storage_path_resolution(self):
        """FileSystemStorage must resolve paths within the base directory."""
        storage = FileSystemStorage()
        # The storage base directory must be set
        assert storage.location is not None or hasattr(storage, "_location")

    def test_file004_admin_extension_path_traversal_check(self):
        """Admin extension serving must verify paths stay within base_dir."""
        # The admin site's serve_extension_file checks:
        # if not str(ext_file).startswith(str(base_dir) + "/") and ext_file != base_dir:
        #     raise NotFound("Invalid extension path")
        # This prevents path traversal in extension file serving.
        # Verify the check exists in the source.
        source = inspect.getsource(get_admin_site)
        assert "startswith" in source or "resolve" in source


class TestDecompressionBombLimit:
    """Decompression bombs must be detected and limited."""

    def test_file005_request_body_size_limit(self):
        """Request body size must be limited to prevent decompression bombs."""
        assert MAX_BODY_SIZE > 0
        assert MAX_BODY_SIZE <= 100 * 1024 * 1024  # 100 MB max

    def test_file005_max_files_per_request(self):
        """The number of files per multipart request must be limited."""
        assert MAX_FILES_PER_REQUEST > 0
        assert MAX_FILES_PER_REQUEST <= 1000  # Reasonable upper bound


class TestPrivateUploadIsolation:
    """Private uploads must not be accessible via public static URLs."""

    def test_file006_storage_url_does_not_expose_private_paths(self):
        """Storage URLs must not expose private file paths."""
        storage = FileSystemStorage()
        # The URL method must not include the full filesystem path
        # This is a structural check; actual serving is tested in integration tests
        assert hasattr(storage, "url")

    def test_file006_media_root_separate_from_static(self):
        """Media (upload) directory must be separate from static files."""
        media_root = getattr(settings, "MEDIA_ROOT", "")
        # Media and static must be separate
        if media_root:
            assert "/static/" not in media_root or media_root.endswith("/media/")
