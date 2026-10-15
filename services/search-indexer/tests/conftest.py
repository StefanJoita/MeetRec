# services/search-indexer/tests/conftest.py
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
