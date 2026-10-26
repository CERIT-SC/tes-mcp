import os

os.environ.setdefault("TES_URL", "https://tes.example.com")
os.environ.setdefault("TES_USERNAME", "test-user")
os.environ.setdefault("TES_PASSWORD", "test-password")
os.environ.setdefault("OUTPUT_PATH", "/results")
os.environ.setdefault("OUTPUT_URL", "s3://test-bucket/results")
