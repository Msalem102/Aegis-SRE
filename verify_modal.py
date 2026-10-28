"""
Modal Cloud Infrastructure Live Verification Script.
Tests live connectivity to Modal using MODAL_TOKEN_ID and MODAL_TOKEN_SECRET,
provisions an ephemeral serverless Linux micro-VM in the cloud, benchmarks spin-up latency,
and validates execution inside the remote sandbox.
"""

import sys
import os
import time
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()


def test_modal_cloud_sandbox():
    print("=" * 76)
    print("☁️  AEGIS SRE: Modal Cloud Serverless Infrastructure Live Test")
    print("=" * 76)

    token_id = os.getenv("MODAL_TOKEN_ID")
    token_secret = os.getenv("MODAL_TOKEN_SECRET")

    print("\n[Configuration]")
    masked_id = f"{token_id[:6]}...{token_id[-4:]}" if token_id and len(token_id) > 10 else ("Configured" if token_id else "NOT SET")
    print(f" -> MODAL_TOKEN_ID:     {masked_id}")
    print(f" -> MODAL_TOKEN_SECRET: {'Configured (Hidden)' if token_secret else 'NOT SET'}")

    if not token_id or not token_secret or "xxxx" in token_id:
        print("\n❌ Modal tokens are missing in .env.")
        print("Please ensure MODAL_TOKEN_ID and MODAL_TOKEN_SECRET are set.")
        print("=" * 76)
        return False

    try:
        import modal
    except ImportError:
        print("\n❌ Modal package not installed in current Python environment.")
        return False

    print("\n[Provisioning Ephemeral Linux Container on Modal Cloud...]")
    start_time = time.perf_counter()

    try:
        app = modal.App.lookup("aegis-sre", create_if_missing=True)
        image = modal.Image.debian_slim().pip_install("pytest")

        # Launch cloud sandbox
        sb = modal.Sandbox.create(
            "python", "-c",
            "import sys, platform; print(f'⚡ Aegis SRE Container Active on {platform.system()} {platform.machine()} | Python {sys.version.split()[0]}')",
            image=image,
            app=app,
            timeout=60
        )
        sb.wait()

        elapsed_seconds = time.perf_counter() - start_time
        stdout = sb.stdout.read().strip()
        stderr = sb.stderr.read().strip()

        if sb.returncode == 0:
            print("\n✅ Modal Cloud Sandbox Verification SUCCESSFUL!")
            print(f" -> Container Object ID: {sb.object_id}")
            print(f" -> Spin-up + Exec Time: {elapsed_seconds:.2f} seconds")
            print(f" -> Remote Container Log: \"{stdout}\"")
            print(f" -> Exit Status:         0 (ALL CHECKS PASSED)")
            print("=" * 76)
            return True
        else:
            print(f"\n❌ Container Exited with Error Code {sb.returncode}:")
            print(f" -> Stderr: {stderr}")
            print("=" * 76)
            return False

    except Exception as e:
        print(f"\n❌ Modal Cloud Connection Failed: {e}")
        print("=" * 76)
        return False


if __name__ == "__main__":
    test_modal_cloud_sandbox()
