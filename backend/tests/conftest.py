import os

# Settings require a password; set a dummy one before the app module is imported.
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("PII_HASH_KEY", "test-pii-hash-key-0123456789")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-0123456789-0123456789")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
