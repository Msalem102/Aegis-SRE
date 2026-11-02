"""
Modal Cloud Infrastructure Live Verification Script.
Redirects to unified `verify_apis.py` while preserving standalone CLI compatibility.
"""
import sys
from verify_apis import verify_modal_api

if __name__ == "__main__":
    res = verify_modal_api(quiet=False)
    sys.exit(0 if res.get("passed") else 1)
