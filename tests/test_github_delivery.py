"""
Unit & Integration Tests for the Real GitHub Pull Request Delivery Engine.
Verifies:
1. Atomic Git Data API branch + blob + tree + commit + PR creation.
2. Simulated local delivery when token is not configured.
3. Graceful fallback on network or permission errors.
4. Dynamic target repository resolution for any downstream project.
"""

import pytest
import httpx
from core.delivery.github_delivery import GitHubDeliveryEngine


def test_simulated_delivery_when_token_is_missing():
    """Asserts that missing GitHub token safely defaults to SIMULATED_LOCAL mode."""
    engine = GitHubDeliveryEngine(github_token=None)
    res = engine.deliver_remediation_pr(
        repo="any-org/any-service",
        incident_id="INC-TEST-01",
        pr_title="fix(api): fix contract drift",
        pr_body="# Incident Report\nVerified in sandbox.",
        files_to_commit={"src/client.py": "# fixed client code"}
    )

    assert res["status"] == "SIMULATED_LOCAL"
    assert res["pr_number"] == 42
    assert "any-org/any-service" in res["html_url"]
    assert "src/client.py" in res["committed_files"]
    assert res["branch"].startswith("aegis/remediate-inc-test-01-")


def test_live_github_pr_workflow_atomic_git_tree():
    """
    Asserts the full atomic GitHub REST API sequence:
    1. Resolve repo & default branch
    2. Get HEAD commit SHA & base tree SHA
    3. Create Git Blobs for modified files
    4. Create new Git Tree
    5. Create Git Commit
    6. Create remote branch ref
    7. Open live GitHub Pull Request
    """
    def mock_transport(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        method = request.method

        if "repos/my-org/novacart-store/git/ref/heads/main" in url_str:
            return httpx.Response(200, json={"object": {"sha": "sha_base_commit_111"}})
        elif "repos/my-org/novacart-store/git/commits/sha_base_commit_111" in url_str:
            return httpx.Response(200, json={"tree": {"sha": "sha_base_tree_222"}})
        elif "repos/my-org/novacart-store/git/blobs" in url_str and method == "POST":
            return httpx.Response(201, json={"sha": "sha_blob_333"})
        elif "repos/my-org/novacart-store/git/trees" in url_str and method == "POST":
            return httpx.Response(201, json={"sha": "sha_new_tree_444"})
        elif "repos/my-org/novacart-store/git/commits" in url_str and method == "POST":
            return httpx.Response(201, json={"sha": "sha_new_commit_555"})
        elif "repos/my-org/novacart-store/git/refs" in url_str and method == "POST":
            return httpx.Response(201, json={"ref": "refs/heads/aegis/remediate-xyz"})
        elif "repos/my-org/novacart-store/pulls" in url_str and method == "GET":
            return httpx.Response(200, json=[])
        elif "repos/my-org/novacart-store/pulls" in url_str and method == "POST":
            return httpx.Response(201, json={
                "number": 88,
                "html_url": "https://github.com/my-org/novacart-store/pull/88",
                "state": "open"
            })
        elif "repos/my-org/novacart-store" in url_str and method == "GET":
            return httpx.Response(200, json={"default_branch": "main", "full_name": "my-org/novacart-store"})

        return httpx.Response(404, json={"message": f"Not found: {url_str}"})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    engine = GitHubDeliveryEngine(github_token="ghp_mock_live_token_12345", client=mock_client)

    res = engine.deliver_remediation_pr(
        repo="my-org/novacart-store",
        incident_id="INC-20261028-API-99",
        pr_title="fix(contract): auto-remediate upstream payment contract",
        pr_body="# Post-Mortem\nGate: PASSED",
        files_to_commit={
            "src/models.py": "class ChargeRequest:\n    pass\n",
            "src/payment_client.py": "def charge():\n    pass\n"
        }
    )

    assert res["status"] == "LIVE_GITHUB_PR"
    assert res["pr_number"] == 88
    assert res["html_url"] == "https://github.com/my-org/novacart-store/pull/88"
    assert res["commit_sha"] == "sha_new_commit_555"
    assert res["target_repo"] == "my-org/novacart-store"
    assert len(res["committed_files"]) == 2


def test_graceful_fallback_on_github_api_error():
    """Asserts that 403 or network failure gracefully degrades to FALLBACK_LOCAL."""
    def mock_transport_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Bad credentials or write access denied"})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_transport_error))
    engine = GitHubDeliveryEngine(github_token="ghp_invalid_token", client=mock_client)

    res = engine.deliver_remediation_pr(
        repo="my-org/novacart-store",
        incident_id="INC-ERROR-01",
        pr_title="fix(db): add index",
        pr_body="Post-mortem",
        files_to_commit={"migrations/idx.sql": "CREATE INDEX ..."}
    )

    assert res["status"] == "FALLBACK_LOCAL"
    assert res["pr_number"] == 42
    assert "403" in res["error"]
    assert "my-org/novacart-store" in res["html_url"]


def test_unified_diff_generation():
    """Asserts accurate unified diff generation across multiple modified files."""
    engine = GitHubDeliveryEngine()
    orig = {
        "src/models.py": "amount: float\naddress: str\n",
        "src/client.py": "def send():\n    return {'amount': amount}\n"
    }
    repaired = {
        "src/models.py": "amount_cents: int\nbilling: dict\n",
        "src/client.py": "def send():\n    return {'amount_cents': amount * 100}\n"
    }

    diff_text = engine.generate_diff(orig, repaired)
    assert "--- a/src/models.py" in diff_text
    assert "+++ b/src/models.py" in diff_text
    assert "-amount: float" in diff_text
    assert "+amount_cents: int" in diff_text
    assert "--- a/src/client.py" in diff_text


def test_live_github_pr_already_open_deduplication():
    """Asserts that an existing open PR for the same incident is reused instead of creating duplicate PRs."""
    def mock_transport(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        method = request.method
        if "repos/my-org/novacart-store/pulls" in url_str and method == "GET":
            return httpx.Response(200, json=[{
                "number": 12,
                "html_url": "https://github.com/my-org/novacart-store/pull/12",
                "title": "fix(contract): auto-remediate upstream payment contract",
                "head": {"ref": "aegis/remediate-inc-20261028-api-99-abc123"}
            }])
        elif "repos/my-org/novacart-store" in url_str and method == "GET":
            return httpx.Response(200, json={"default_branch": "main", "full_name": "my-org/novacart-store"})
        return httpx.Response(404, json={"message": "Not found"})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    engine = GitHubDeliveryEngine(github_token="ghp_mock_live_token_12345", client=mock_client)

    res = engine.deliver_remediation_pr(
        repo="my-org/novacart-store",
        incident_id="INC-20261028-API-99",
        pr_title="fix(contract): auto-remediate upstream payment contract",
        pr_body="# Post-Mortem",
        files_to_commit={"src/models.py": "class Charge:\n    pass\n"}
    )

    assert res["status"] == "LIVE_GITHUB_PR_ALREADY_OPEN"
    assert res["pr_number"] == 12
    assert res["html_url"] == "https://github.com/my-org/novacart-store/pull/12"
    assert "already exists" in res["message"]


def test_find_open_remediation_pr_preflight():
    """Asserts that find_open_remediation_pr detects open PRs by incident_id or keywords before LLM execution."""
    def mock_transport(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "repos/my-org/novacart-store/pulls" in url_str:
            return httpx.Response(200, json=[{
                "number": 42,
                "html_url": "https://github.com/my-org/novacart-store/pull/42",
                "title": "fix(db): add index on orders (INC-20261104-PG-SEQSCAN)",
                "body": "Resolves unindexed sequential scan on orders table.",
                "head": {"ref": "aegis/remediate-inc-20261104-pg-seqscan-7f8a9b"}
            }])
        return httpx.Response(404, json={})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    engine = GitHubDeliveryEngine(github_token="ghp_test_token_123", client=mock_client)

    # 1. Matches by exact incident ID
    pr_match = engine.find_open_remediation_pr("my-org/novacart-store", "INC-20261104-PG-SEQSCAN")
    assert pr_match is not None
    assert pr_match["pr_number"] == 42
    assert pr_match["html_url"] == "https://github.com/my-org/novacart-store/pull/42"

    # 2. Matches by keyword (e.g. table name 'orders')
    pr_match_kw = engine.find_open_remediation_pr("my-org/novacart-store", "INC-UNKNOWN", keywords=["orders"])
    assert pr_match_kw is not None
    assert pr_match_kw["pr_number"] == 42

    # 3. Returns None when no match found
    pr_none = engine.find_open_remediation_pr("my-org/novacart-store", "INC-UNRELATED", keywords=["payments"])
    assert pr_none is None

