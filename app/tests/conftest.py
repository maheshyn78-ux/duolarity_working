import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="duolarity-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DOCUMENT_STORAGE_PATH"] = f"{_tmp}/docs"
os.environ["AI_PROVIDER"] = "none"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-0123456789")
