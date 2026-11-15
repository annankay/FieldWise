"""Tests run on SYNTHETIC development data in a temporary folder (never on a real data store)."""
import os
import tempfile

os.environ["FIELDWISE_DEMO"] = "1"
os.environ.setdefault("FIELDWISE_DATA_DIR", tempfile.mkdtemp(prefix="fieldwise-test-"))
os.environ["FIELDWISE_FETCH_LIMIT_PER_HOUR"] = "2"
