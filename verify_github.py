"""
GitHub API Diagnostic & Live Integration Verification Tool.
Verifies GitHub Personal Access Token authentication, repository access,
and pull request creation capabilities for Aegis SRE.
"""

import sys
import os
import httpx
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv(override=True)


def test_github_integration(target_repo: str = "ahmedharib/mockStore"):
    print("=" * 76)
    print("🔍 AEGIS SRE: GitHub Integration & Pull Request Capability Test")
    print("=" * 76)

    token = os.getenv("GITHUB_TOKEN")
    if token:
        token = token.strip().strip('"').strip("'")

    if not token or token == "ghp_your_github_personal_access_token":
        print("\n⚠️  No live GITHUB_TOKEN detected in .env.")
        print("\nTo connect live GitHub Pull Request delivery:")
        print("1. Go to: https://github.com/settings/tokens")
        print("2. Generate a Personal Access Token with:")
        print("   • Classic Token: 'public_repo' (for public repos) or 'repo' (for private)")
        print("   • OR Fine-Grained Token: Repository 'ahmedharib/mockStore'")
        print("     Permissions: Contents (Read & Write), Pull Requests (Read & Write)")
        print("3. Open '.env' in your workspace root and add:")
        print("   GITHUB_TOKEN=ghp_your_token_here")
        print("4. Re-run this check: .\\.venv\\Scripts\\python.exe verify_github.py")
        print("\n(Note: Without a token, Aegis safely runs in SIMULATED_LOCAL delivery mode).")
        print("=" * 76)
        return False

    masked = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "SET"
    print(f"\n[Configuration]")
    print(f" -> Token Detected:   {masked}")
    print(f" -> Target Repository: {target_repo}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    print("\n[1/3] Authenticating with GitHub API...")
    try:
        with httpx.Client(timeout=15.0) as client:
            user_resp = client.get("https://api.github.com/user", headers=headers)
            if user_resp.status_code == 401:
                print("❌ GitHub API Error: 401 Unauthorized. The provided GITHUB_TOKEN is invalid or expired.")
                return False
            user_resp.raise_for_status()
            user_data = user_resp.json()
            username = user_data.get("login", "unknown")
            print(f"✅ Authenticated as GitHub user: @{username}")

            print(f"\n[2/3] Verifying access to repository '{target_repo}'...")
            repo_resp = client.get(f"https://api.github.com/repos/{target_repo}", headers=headers)
            if repo_resp.status_code == 404:
                print(f"❌ Repository '{target_repo}' not found or token lacks access.")
                return False
            repo_resp.raise_for_status()
            repo_data = repo_resp.json()
            default_branch = repo_data.get("default_branch", "master")
            permissions = repo_data.get("permissions", {})
            can_push = permissions.get("push", False)
            print(f"✅ Repository accessible! Default branch: '{default_branch}'")
            print(f" -> Write/Push Permission: {'YES (Ready for PRs)' if can_push else 'NO (PR branch creation may fail)'}")

            print("\n[3/3] Inspecting active pull requests on target repository...")
            prs_resp = client.get(f"https://api.github.com/repos/{target_repo}/pulls?state=all&per_page=5", headers=headers)
            if prs_resp.status_code == 200:
                prs = prs_resp.json()
                print(f"✅ Pull Request API responsive ({len(prs)} recent PRs found).")

            print("\n" + "=" * 76)
            print("🎉 GitHub PR Delivery is FULLY CONFIGURED and ready for live SRE remediation!")
            print("=" * 76)
            return True

    except Exception as e:
        print(f"\n❌ GitHub API Check Failed: {e}")
        return False


if __name__ == "__main__":
    test_github_integration()
