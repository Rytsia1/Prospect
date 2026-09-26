import os

# Dummy placeholders so Settings validates in unit tests. Real env vars take precedence.
for key, value in {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "OBJECT_STORAGE_ENDPOINT": "https://storage.test",
    "OBJECT_STORAGE_BUCKET": "test-bucket",
    "OBJECT_STORAGE_ACCESS_KEY": "test-access-key",
    "OBJECT_STORAGE_SECRET_KEY": "test-secret-key",
    "APP_SECRET": "test-app-secret",
}.items():
    os.environ.setdefault(key, value)
