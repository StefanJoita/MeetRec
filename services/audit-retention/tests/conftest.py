# services/audit-retention/tests/conftest.py
import os

# Settings() e instanțiat la import-time în config.py; DATABASE_URL e obligatoriu.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
