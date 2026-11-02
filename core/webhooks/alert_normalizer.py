"""
Autonomous Alert Webhook Normalizer.
Classifies and normalizes inbound JSON alert payloads (from application middleware,
Alertmanager, Sentry, or direct health/watchdog monitors) into Vector A (Database)
or Vector B (Upstream API Contract Drift) remediation triggers.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import json
import uuid
import hashlib


class AlertEventNormalizer:
    """Classifies generic JSON alert webhooks into Vector A or Vector B incident payloads."""

    DB_EVENT_KEYWORDS = {
        "slow_query", "db_slow_query", "db_timeout", "postgres_slow_query",
        "latency_breach", "seq_scan", "pg_slow_query_breach", "critical_cpu_spike"
    }
    API_EVENT_KEYWORDS = {
        "api_error", "contract_drift", "http_error", "validation_error",
        "checkout_failed", "payment_error", "upstream_422", "contract_violation"
    }

    @classmethod
    def classify_and_normalize(
        cls,
        raw_payload: Dict[str, Any],
        default_service: str = "monitored-service"
    ) -> Optional[Dict[str, Any]]:
        """
        Inspects an inbound JSON alert payload.
        Returns `{"vector": "a" | "b", "event_uid": str, "payload": dict}` or `None` if benign.
        """
        if not isinstance(raw_payload, dict) or not raw_payload:
            return None

        event_obj = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else raw_payload
        event_name = str(
            event_obj.get("event")
            or event_obj.get("event_type")
            or raw_payload.get("error_code")
            or ""
        ).strip()

        props = event_obj.get("properties") if isinstance(event_obj.get("properties"), dict) else {}

        # Explicit vector hint if provided by sender (`"vector": "a"` or `"vector": "b"`)
        explicit_vector = str(raw_payload.get("vector") or event_obj.get("vector") or "").strip().lower()

        explicit_uid = (
            raw_payload.get("incident_id")
            or event_obj.get("id")
            or event_obj.get("uuid")
        )
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        service = str(
            raw_payload.get("service")
            or event_obj.get("service")
            or props.get("service")
            or default_service
        )

        # 1. Extract Database Slow Query / Latency Breach signals (Vector A)
        sql_query = (
            raw_payload.get("pg_stat_statements_summary", {}).get("query")
            or raw_payload.get("offending_query")
            or raw_payload.get("query")
            or event_obj.get("query")
            or event_obj.get("sql")
            or props.get("query")
            or props.get("sql")
        )
        latency_ms = (
            raw_payload.get("latency_ms")
            or raw_payload.get("duration_ms")
            or raw_payload.get("p99_latency_ms")
            or raw_payload.get("anomaly_trigger", {}).get("current_value")
            or event_obj.get("duration_ms")
            or props.get("duration_ms")
            or props.get("latency_ms")
        )
        status_code = (
            raw_payload.get("http_status")
            or raw_payload.get("status_code")
            or event_obj.get("http_status")
            or props.get("http_status")
        )

        is_db_event = (
            explicit_vector in ("a", "db", "database")
            or bool(sql_query)
            or event_name.lower() in cls.DB_EVENT_KEYWORDS
            or "slow_query" in event_name.lower()
            or "seq_scan" in event_name.lower()
            or "database" in event_name.lower()
            or (status_code is not None and str(status_code).isdigit() and int(status_code) == 504)
            or (latency_ms is not None and float(latency_ms) >= 1000.0 and not status_code)
        )

        if is_db_event and explicit_vector not in ("b", "api"):
            fingerprint = f"{service}:{sql_query or event_name}"
            event_uid = str(explicit_uid or f"db-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:8]}")
            inc_id = str(raw_payload.get("incident_id") or f"INC-{ts_tag}-DB-{event_uid[-6:].upper()}")
            measured_lat = float(latency_ms) if latency_ms is not None else 2450.0
            cpu_pct = float(
                raw_payload.get("host_cpu_percent")
                or raw_payload.get("anomaly_trigger", {}).get("host_cpu_percent")
                or props.get("host_cpu_percent")
                or 92.4
            )
            sample_params = (
                raw_payload.get("sample_params")
                or event_obj.get("sample_params")
                or props.get("sample_params")
            )
            return {
                "vector": "a",
                "event_uid": event_uid,
                "payload": {
                    "incident_id": inc_id,
                    "service": service,
                    "discovery_source": "alert_webhook",
                    "pg_stat_statements_summary": {
                        "query": sql_query or ""
                    },
                    "sample_params": sample_params if isinstance(sample_params, list) else None,
                    "anomaly_trigger": {
                        "metric": "p99_query_latency_ms",
                        "current_value": measured_lat,
                        "threshold": float(raw_payload.get("sla_threshold_ms", 1500.0)),
                        "host_cpu_percent": cpu_pct
                    }
                }
            }

        # 2. Extract API Contract Drift / HTTP 4xx-5xx / Runtime Exception signals (Vector B)
        exc_msg = (
            raw_payload.get("error_message")
            or raw_payload.get("error")
            or raw_payload.get("detail")
            or event_obj.get("error_message")
            or props.get("error_message")
            or props.get("error")
        )
        stack_trace = (
            raw_payload.get("raw_traceback")
            or raw_payload.get("traceback")
            or raw_payload.get("stack_trace")
            or event_obj.get("traceback")
            or props.get("traceback")
            or ""
        )
        endpoint = (
            raw_payload.get("endpoint")
            or raw_payload.get("url")
            or event_obj.get("endpoint")
            or props.get("endpoint")
            or ""
        )

        has_error_status = False
        if status_code is not None:
            try:
                has_error_status = int(status_code) >= 400
            except Exception:
                pass

        is_api_event = (
            explicit_vector in ("b", "api", "contract")
            or event_name.lower() in cls.API_EVENT_KEYWORDS
            or bool(exc_msg)
            or has_error_status
            or "error" in event_name.lower()
            or "fail" in event_name.lower()
            or "exception" in event_name.lower()
            or "drift" in event_name.lower()
        )

        if is_api_event:
            parsed_status = int(status_code) if (status_code and str(status_code).isdigit()) else 422
            fingerprint = f"{service}:{endpoint or 'checkout'}:{parsed_status}:{event_name or 'error'}"
            event_uid = str(explicit_uid or f"api-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:8]}")
            inc_id = str(raw_payload.get("incident_id") or f"INC-{ts_tag}-API-{event_uid[-6:].upper()}")
            return {
                "vector": "b",
                "event_uid": event_uid,
                "payload": {
                    "incident_id": inc_id,
                    "service": service,
                    "discovery_source": "alert_webhook",
                    "http_status": parsed_status,
                    "endpoint": endpoint,
                    "error_message": str(exc_msg or f"Alert '{event_name}' reported HTTP {parsed_status} contract failure"),
                    "raw_traceback": str(stack_trace or json.dumps(raw_payload)[:1200])
                }
            }

        return None
