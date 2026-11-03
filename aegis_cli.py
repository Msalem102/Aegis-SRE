"""
Aegis SRE Unified CLI (`aegis_cli.py`).
Provides project onboarding, contract compliance verification (`aegis.yaml`),
autonomous remediation orchestration, live alert/DB watchdog listening, and
zero-idle-cost Modal Cloud serverless deployment.

Usage:
  python aegis_cli.py check  [--config aegis.yaml]
  python aegis_cli.py init   [--output aegis.yaml]
  python aegis_cli.py run    --vector [a|b|all] [--config aegis.yaml]
  python aegis_cli.py listen [--config aegis.yaml] [--port 8080] [--watchdog]
  python aegis_cli.py deploy [--config aegis.yaml]
"""

import sys
import os
import argparse
import subprocess
from typing import Optional
from dotenv import load_dotenv

_cli_env = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
if os.path.exists(_cli_env):
    load_dotenv(dotenv_path=_cli_env, override=True)
else:
    load_dotenv(override=True)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

from core.config.aegis_config import AegisConfigLoader


def cmd_check(config_path: str) -> int:
    if not RICH_AVAILABLE:
        print("=" * 78)
        print("🛡️  AEGIS SRE: Project Integration Contract Compliance Audit")
        print("=" * 78)
        print(f"Manifest Target: {config_path}\n")

    try:
        manifest = AegisConfigLoader.load(config_path)
    except Exception as e:
        print(f"❌ Failed to load manifest '{config_path}': {e}")
        return 1

    base_dir = os.path.dirname(os.path.abspath(config_path)) or "."
    report = AegisConfigLoader.validate_project_compliance(manifest, base_dir=base_dir)

    if RICH_AVAILABLE:
        table = Table(title="🛡️  Aegis SRE: Project Integration Contract Audit", show_header=True, header_style="bold cyan")
        table.add_column("Status", justify="center", width=8)
        table.add_column("Category", style="bold yellow", width=22)
        table.add_column("Contract Rule", style="bold white", width=35)
        table.add_column("Verification Detail", style="dim white")

        for item in report["checks"]:
            status_badge = "[bold green]PASS[/bold green]" if item["passed"] else "[bold red]FAIL[/bold red]"
            table.add_row(status_badge, item["category"], item["name"], item["detail"])

        console.print(table)

        if report["passed"]:
            console.print(Panel(
                f"[bold green]🎉 CONTRACT VERIFIED:[/bold green] Project '[bold white]{report['service_name']}[/bold white]' is 100% compliant with Aegis SRE!",
                border_style="green"
            ))
            return 0
        else:
            err_text = "\n".join([f"• {err}" for err in report["errors"]])
            console.print(Panel(
                f"[bold red]🚨 CONTRACT VIOLATIONS DETECTED ({len(report['errors'])} error(s)):[/bold red]\n{err_text}",
                border_style="red"
            ))
            return 1
    else:
        for item in report["checks"]:
            icon = "✅" if item["passed"] else "❌"
            print(f" {icon} [{item['category']}] {item['name']}")
            print(f"    └─ {item['detail']}")

        print("\n" + "-" * 78)
        if report["passed"]:
            print(f"🎉 CONTRACT VERIFIED: Project '{report['service_name']}' is 100% compliant with Aegis SRE!")
            print("=" * 78)
            return 0
        else:
            print(f"🚨 CONTRACT VIOLATIONS DETECTED ({len(report['errors'])} error(s)):")
            for err in report["errors"]:
                print(f"   • {err}")
            print("=" * 78)
            return 1


def cmd_init(output_path: str, overwrite: bool = False) -> int:
    if os.path.exists(output_path) and not overwrite:
        print(f"⚠️ File '{output_path}' already exists. Use --force to overwrite.")
        return 1

    template = AegisConfigLoader.generate_starter_template()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(template)
    print(f"✅ Generated starter Aegis integration manifest at: {output_path}")
    return 0


def cmd_run(vector: str, config_path: str, query: Optional[str] = None, skip_verify: bool = False) -> int:
    code = cmd_check(config_path)
    if code != 0:
        print("Aborting execution due to contract compliance failure.")
        return code

    if not skip_verify:
        from verify_apis import verify_all_apis
        verify_all_apis(config_path=config_path)

    v = vector.lower()
    try:
        if v in ("a", "db", "all"):
            from aegis_vector_a_runner import run_vector_a_remediation
            alert_override = None
            if query:
                alert_override = {
                    "incident_id": "INC-CLI-ON-DEMAND",
                    "service": "cli-query-trigger",
                    "pg_stat_statements_summary": {"query": query.strip()},
                    "anomaly_trigger": {"current_value": 3200.0, "threshold": 1000.0, "host_cpu_percent": 91.0}
                }
            run_vector_a_remediation(config_path=config_path, alert_payload_override=alert_override)

        if v in ("b", "api", "all"):
            from aegis_vector_b_runner import run_vector_b_remediation
            run_vector_b_remediation(config_path=config_path)
    except Exception as e:
        print(f"❌ Remediation failed: {e}")
        return 1

    return 0


def find_free_port(start_port: int = 8080, max_attempts: int = 15) -> int:
    """Finds an available TCP port starting from start_port."""
    import socket
    for candidate in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", candidate))
                return candidate
            except OSError:
                continue
    return start_port


def cmd_listen(config_path: str, host: str = "0.0.0.0", port: int = 8080, watchdog: bool = False, skip_verify: bool = False) -> int:
    code = cmd_check(config_path)
    if code != 0:
        print("Aborting webhook daemon startup due to contract compliance failure.")
        return code

    if not skip_verify:
        from verify_apis import verify_all_apis
        verify_all_apis(config_path=config_path)

    actual_port = find_free_port(port)
    if actual_port != port:
        print(f"⚠️  Port {port} is occupied by another process. Automatically switched to port {actual_port}.")

    import uvicorn
    from core.webhooks.listener import create_webhook_app

    print("=" * 78)
    print(f"🛡️  AEGIS SRE Autonomous Webhook & Watchdog Daemon Listening on http://{host}:{actual_port}")
    print(f"   • SRE Control Plane UI: http://localhost:{actual_port}/ (or http://127.0.0.1:{actual_port}/)")
    print(f"   • Alert Webhook URL:    http://localhost:{actual_port}/webhooks/alert")
    print(f"   • Health Check URL:     http://localhost:{actual_port}/health")
    print(f"   • Direct DB Watchdog:   {'ENABLED' if watchdog else 'DISABLED (pass --watchdog to enable)'}")
    print("=" * 78)

    app = create_webhook_app(config_path=config_path, enable_db_watchdog=watchdog)
    uvicorn.run(app, host=host, port=actual_port)
    return 0


def cmd_ui(config_path: str, host: str = "0.0.0.0", port: int = 8080, watchdog: bool = True, skip_verify: bool = False, no_browser: bool = False) -> int:
    import webbrowser
    import time
    import threading

    default_config = config_path if (config_path and os.path.exists(config_path)) else ("mockstore_aegis.yaml" if os.path.exists("mockstore_aegis.yaml") else "aegis.yaml")
    actual_port = find_free_port(port)
    if actual_port != port:
        print(f"⚠️  Port {port} is occupied by another process. Automatically launching on port {actual_port}.")

    if not no_browser:
        def _open():
            time.sleep(1.2)
            try:
                webbrowser.open(f"http://localhost:{actual_port}/")
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    return cmd_listen(config_path=default_config, host=host, port=actual_port, watchdog=watchdog, skip_verify=skip_verify)


def cmd_verify(config_path: str) -> int:
    from verify_apis import verify_all_apis
    results = verify_all_apis(config_path=config_path)
    return 0 if results["all_passed"] else 1


def cmd_deploy(config_path: str) -> int:
    code = cmd_check(config_path)
    if code != 0:
        print("Aborting serverless deployment due to contract compliance failure.")
        return code

    serverless_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aegis_serverless.py")
    print("=" * 78)
    print("☁️  Deploying Zero-Idle-Cost Aegis SRE Daemon to Modal Cloud...")
    print(f"   • Manifest:  {config_path}")
    print("   • Endpoints: Scale-to-Zero HTTPS Alert Webhook + 30-min Read-Only DB Watchdog")
    print("=" * 78)

    deploy_env = {**os.environ, "AEGIS_DEPLOY_CONFIG": config_path}
    res = subprocess.run([sys.executable, "-m", "modal", "deploy", serverless_file], env=deploy_env)
    return res.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Aegis SRE Project Contract & Remediation CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # check / validate
    p_check = subparsers.add_parser("check", aliases=["validate"], help="Validate project compliance with aegis.yaml")
    p_check.add_argument("--config", default="aegis.yaml", help="Path to aegis.yaml manifest")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a starter aegis.yaml manifest")
    p_init.add_argument("--output", default="aegis.yaml", help="Output path for generated manifest")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing file")

    # run
    p_run = subparsers.add_parser("run", help="Run autonomous remediation using aegis.yaml")
    p_run.add_argument("--vector", choices=["a", "b", "db", "api", "all"], default="all", help="Remediation vector to execute")
    p_run.add_argument("--config", default="aegis.yaml", help="Path to aegis.yaml manifest")
    p_run.add_argument("--query", default=None, help="Optional offending SQL query to remediate on-demand")
    p_run.add_argument("--skip-verify", action="store_true", help="Skip pre-flight API verification checks")

    # listen
    p_listen = subparsers.add_parser("listen", help="Start live Alert webhook & optional Direct DB Watchdog daemon")
    p_listen.add_argument("--config", default="aegis.yaml", help="Path to aegis.yaml manifest")
    p_listen.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p_listen.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    p_listen.add_argument("--watchdog", action="store_true", help="Actively monitor PostgreSQL read-only telemetry in background")
    p_listen.add_argument("--skip-verify", action="store_true", help="Skip pre-flight API verification checks")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify live connectivity to Meta Model API, Modal Cloud, and GitHub")
    p_verify.add_argument("--config", default="aegis.yaml", help="Path to aegis.yaml manifest")

    # ui / dashboard
    p_ui = subparsers.add_parser("ui", aliases=["dashboard"], help="Launch the Aegis SRE Web Dashboard & Control Plane")
    p_ui.add_argument("--config", default="mockstore_aegis.yaml", help="Path to aegis.yaml or mockstore_aegis.yaml")
    p_ui.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p_ui.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    p_ui.add_argument("--no-watchdog", action="store_true", help="Disable direct DB watchdog")
    p_ui.add_argument("--skip-verify", action="store_true", help="Skip pre-flight API verification checks")
    p_ui.add_argument("--no-browser", action="store_true", help="Do not automatically open the browser")

    # deploy
    p_deploy = subparsers.add_parser("deploy", help="Deploy zero-idle-cost scale-to-zero Aegis SRE daemon onto Modal Cloud")
    p_deploy.add_argument("--config", default="aegis.yaml", help="Path to aegis.yaml manifest")

    args = parser.parse_args()

    if args.command in ("check", "validate"):
        return cmd_check(args.config)
    elif args.command == "init":
        return cmd_init(args.output, overwrite=args.force)
    elif args.command == "run":
        return cmd_run(args.vector, args.config, query=args.query, skip_verify=args.skip_verify)
    elif args.command == "listen":
        return cmd_listen(args.config, host=args.host, port=args.port, watchdog=args.watchdog, skip_verify=args.skip_verify)
    elif args.command in ("ui", "dashboard"):
        return cmd_ui(args.config, host=args.host, port=args.port, watchdog=not args.no_watchdog, skip_verify=args.skip_verify, no_browser=args.no_browser)
    elif args.command == "verify":
        return cmd_verify(args.config)
    elif args.command == "deploy":
        return cmd_deploy(args.config)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
