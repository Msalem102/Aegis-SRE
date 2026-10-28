"""
Aegis SRE Unified CLI (`aegis_cli.py`).
Provides project onboarding, contract compliance verification (`aegis.yaml`),
and autonomous remediation orchestration for any conforming project.

Usage:
  python aegis_cli.py check [--config aegis.yaml]
  python aegis_cli.py init  [--output aegis.yaml]
  python aegis_cli.py run   --vector [a|b|all] [--config aegis.yaml]
"""

import sys
import os
import argparse

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


def cmd_run(vector: str, config_path: str) -> int:
    code = cmd_check(config_path)
    if code != 0:
        print("Aborting execution due to contract compliance failure.")
        return code

    v = vector.lower()
    if v in ("a", "db", "all"):
        from aegis_vector_a_runner import run_vector_a_remediation
        run_vector_a_remediation(config_path=config_path)

    if v in ("b", "api", "all"):
        from aegis_vector_b_runner import run_vector_b_remediation
        run_vector_b_remediation(config_path=config_path)

    return 0


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

    args = parser.parse_args()

    if args.command in ("check", "validate"):
        return cmd_check(args.config)
    elif args.command == "init":
        return cmd_init(args.output, overwrite=args.force)
    elif args.command == "run":
        return cmd_run(args.vector, args.config)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
