"""
GitHub API Diagnostic & Live Integration Verification Tool.
Redirects to unified `verify_apis.py` while preserving standalone CLI compatibility.
"""
import sys
from verify_apis import verify_github_api

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ahmedharib/mockStore"
    res = verify_github_api(target_repo=target, quiet=False)
    sys.exit(0 if res.get("passed") else 1)
