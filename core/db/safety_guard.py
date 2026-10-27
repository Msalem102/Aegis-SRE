"""
DDL Safety and Policy Guardrails.
Enforces the Aegis SRE Production Safety Mandate:
- Hard-blocks destructive operations: DROP, TRUNCATE, ALTER TABLE ... DROP COLUMN.
- Mandates CONCURRENTLY for index builds to prevent exclusive write locks.
- Enforces strict timeout boundaries (lock_timeout = '5s', statement_timeout = '30s').
- Mandates idempotency (IF NOT EXISTS).
"""

from typing import Dict, Any, List, Tuple
import re


class DDLSafetyGuard:
    DESTRUCTIVE_PATTERNS = [
        r"\bDROP\s+TABLE\b",
        r"\bDROP\s+DATABASE\b",
        r"\bDROP\s+SCHEMA\b",
        r"\bTRUNCATE\b",
        r"\bALTER\s+TABLE\b.*\bDROP\s+COLUMN\b",
        r"\bDELETE\s+FROM\b",
        r"\bUPDATE\b"
    ]

    @classmethod
    def validate_ddl(cls, ddl_script: str) -> Tuple[bool, List[str]]:
        """
        Validates synthesized DDL statements against enterprise safety policies.
        Returns (is_valid, violation_reasons).
        """
        violations = []
        normalized_script = ddl_script.strip().upper()

        # 1. Check for destructive operations
        for pattern in cls.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, normalized_script, re.IGNORECASE):
                violations.append(f"Hard-blocked destructive statement matching pattern: {pattern}")

        # 2. Check if creating index without CONCURRENTLY
        create_index_matches = re.finditer(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", normalized_script, re.IGNORECASE)
        for match in create_index_matches:
            # Check if CONCURRENTLY immediately follows CREATE [UNIQUE] INDEX
            snippet = normalized_script[match.start():match.start() + 40]
            if "CONCURRENTLY" not in snippet:
                violations.append("Violation: Index creation must include 'CONCURRENTLY' to prevent production table locks.")

        # 3. Check for idempotency
        if "CREATE INDEX" in normalized_script and "IF NOT EXISTS" not in normalized_script:
            violations.append("Violation: Index creation must include 'IF NOT EXISTS' for safe idempotent re-runs.")

        # 4. Check for lock_timeout guard
        if "LOCK_TIMEOUT" not in normalized_script:
            violations.append("Violation: Missing mandatory 'SET lock_timeout' boundary (must be <= 10s).")

        return (len(violations) == 0, violations)

    @classmethod
    def enforce_safety_envelope(cls, raw_ddl: str) -> str:
        """
        Wraps an index DDL statement in strict timeout boundaries if not already present.
        """
        header = "-- Aegis SRE Zero-Downtime Safe DDL Envelope\n"
        timeouts = "SET statement_timeout = '30s';\nSET lock_timeout = '5s';\n\n"
        
        # Ensure raw_ddl has CONCURRENTLY and IF NOT EXISTS
        sanitized_ddl = raw_ddl
        if re.search(r"\bCREATE\s+INDEX\b", sanitized_ddl, re.IGNORECASE) and "CONCURRENTLY" not in sanitized_ddl.upper():
            sanitized_ddl = re.sub(
                r"\bCREATE\s+INDEX\b", "CREATE INDEX CONCURRENTLY", sanitized_ddl, flags=re.IGNORECASE
            )

        if "IF NOT EXISTS" not in sanitized_ddl.upper():
            sanitized_ddl = re.sub(
                r"\bCONCURRENTLY\b", "CONCURRENTLY IF NOT EXISTS", sanitized_ddl, flags=re.IGNORECASE
            )

        envelope = header
        if "SET LOCK_TIMEOUT" not in sanitized_ddl.upper():
            envelope += timeouts
        envelope += sanitized_ddl.strip()
        if not envelope.endswith(";"):
            envelope += ";"
        return envelope
