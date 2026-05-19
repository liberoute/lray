"""
Quota Tracker — tracks GAS and CFW usage, persists across restarts.

Monitors:
  - Per-script request count (how many requests sent to each GAS script)
  - Quota exhaustion detection (when 429/rate-limit is received)
  - Reset time estimation (24h after first request)
  - Blacklist status (which scripts are temporarily disabled)

Data is saved to a JSON file so it survives restarts.

Dashboard integration:
  - Shows per-script usage
  - Shows which scripts are exhausted
  - Shows estimated reset time
  - Shows total remaining capacity
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger("Quota")

_DEFAULT_GAS_DAILY_LIMIT = 20000
_DEFAULT_CFW_DAILY_LIMIT = 100000
_SAVE_INTERVAL = 30  # save to disk every 30 seconds max


@dataclass
class ScriptQuota:
    """Quota state for a single script/worker."""
    script_id: str
    display_id: str = ""  # short version for display
    requests_today: int = 0
    daily_limit: int = _DEFAULT_GAS_DAILY_LIMIT
    first_request_at: float = 0.0  # timestamp of first request in current period
    reset_at: float = 0.0  # when quota resets (first_request_at + 24h)
    exhausted: bool = False  # True when 429 received
    exhausted_at: float = 0.0
    last_request_at: float = 0.0
    errors: int = 0


class QuotaTracker:
    """Tracks quota usage for all GAS scripts and CFW workers."""

    def __init__(self, config: dict, data_dir: str = "."):
        self._scripts: dict[str, ScriptQuota] = {}
        self._data_file = Path(data_dir) / "quota_state.json"
        self._last_save = 0.0
        self._dirty = False

        # Initialize from config
        script_ids = config.get("script_ids") or config.get("script_id")
        if isinstance(script_ids, str):
            script_ids = [script_ids]
        elif not script_ids:
            script_ids = []

        for sid in script_ids:
            short = sid[-12:] if len(sid) > 12 else sid
            self._scripts[sid] = ScriptQuota(
                script_id=sid,
                display_id=short,
                daily_limit=_DEFAULT_GAS_DAILY_LIMIT,
            )

        # Load persisted state
        self._load()

    def record_request(self, script_id: str):
        """Record a successful request to a script."""
        quota = self._scripts.get(script_id)
        if not quota:
            short = script_id[-12:] if len(script_id) > 12 else script_id
            quota = ScriptQuota(script_id=script_id, display_id=short)
            self._scripts[script_id] = quota

        now = time.time()

        # Check if period has reset
        if quota.reset_at > 0 and now > quota.reset_at:
            quota.requests_today = 0
            quota.exhausted = False
            quota.exhausted_at = 0.0
            quota.first_request_at = now
            quota.reset_at = now + 86400

        # First request of period
        if quota.first_request_at == 0:
            quota.first_request_at = now
            quota.reset_at = now + 86400

        quota.requests_today += 1
        quota.last_request_at = now
        self._dirty = True
        self._maybe_save()

    def record_exhausted(self, script_id: str):
        """Record that a script returned 429 / quota exhausted."""
        quota = self._scripts.get(script_id)
        if not quota:
            return

        quota.exhausted = True
        quota.exhausted_at = time.time()
        quota.errors += 1
        self._dirty = True
        self._save()
        log.warning(
            "Script %s quota exhausted (%d requests today, resets in %s)",
            quota.display_id, quota.requests_today,
            self._format_time_left(quota.reset_at),
        )

    def record_error(self, script_id: str):
        """Record a non-quota error."""
        quota = self._scripts.get(script_id)
        if quota:
            quota.errors += 1
            self._dirty = True

    def is_exhausted(self, script_id: str) -> bool:
        """Check if a script's quota is exhausted."""
        quota = self._scripts.get(script_id)
        if not quota:
            return False

        # Check if reset time has passed
        if quota.exhausted and quota.reset_at > 0 and time.time() > quota.reset_at:
            quota.exhausted = False
            quota.requests_today = 0
            quota.first_request_at = 0
            self._dirty = True
            return False

        return quota.exhausted

    def get_best_script(self, script_ids: list[str]) -> str | None:
        """Get the script with most remaining quota (not exhausted)."""
        best = None
        best_remaining = -1

        for sid in script_ids:
            if self.is_exhausted(sid):
                continue
            quota = self._scripts.get(sid)
            remaining = (quota.daily_limit - quota.requests_today) if quota else _DEFAULT_GAS_DAILY_LIMIT
            if remaining > best_remaining:
                best_remaining = remaining
                best = sid

        return best

    def get_stats(self) -> dict:
        """Get quota stats for dashboard."""
        now = time.time()
        scripts = []
        total_used = 0
        total_limit = 0
        total_remaining = 0

        for sid, quota in self._scripts.items():
            # Auto-reset if period expired
            if quota.reset_at > 0 and now > quota.reset_at:
                quota.requests_today = 0
                quota.exhausted = False
                quota.first_request_at = 0

            remaining = max(0, quota.daily_limit - quota.requests_today)
            total_used += quota.requests_today
            total_limit += quota.daily_limit
            total_remaining += remaining

            scripts.append({
                "id": quota.display_id,
                "requests_today": quota.requests_today,
                "daily_limit": quota.daily_limit,
                "remaining": remaining,
                "used_pct": round((quota.requests_today / quota.daily_limit) * 100) if quota.daily_limit else 0,
                "exhausted": quota.exhausted,
                "reset_in": self._format_time_left(quota.reset_at) if quota.reset_at > 0 else "—",
                "errors": quota.errors,
            })

        return {
            "scripts": scripts,
            "total_used": total_used,
            "total_limit": total_limit,
            "total_remaining": total_remaining,
            "total_used_pct": round((total_used / total_limit) * 100) if total_limit else 0,
            "all_exhausted": all(q.exhausted for q in self._scripts.values()) if self._scripts else False,
        }

    @staticmethod
    def _format_time_left(reset_at: float) -> str:
        if reset_at <= 0:
            return "—"
        left = reset_at - time.time()
        if left <= 0:
            return "resetting..."
        h = int(left // 3600)
        m = int((left % 3600) // 60)
        return f"{h}h {m}m"

    def _maybe_save(self):
        """Save to disk if enough time has passed."""
        now = time.time()
        if now - self._last_save > _SAVE_INTERVAL and self._dirty:
            self._save()

    def _save(self):
        """Persist quota state to disk."""
        try:
            data = {}
            for sid, quota in self._scripts.items():
                data[sid] = {
                    "requests_today": quota.requests_today,
                    "first_request_at": quota.first_request_at,
                    "reset_at": quota.reset_at,
                    "exhausted": quota.exhausted,
                    "exhausted_at": quota.exhausted_at,
                    "errors": quota.errors,
                    "last_request_at": quota.last_request_at,
                }
            self._data_file.write_text(json.dumps(data, indent=2))
            self._last_save = time.time()
            self._dirty = False
        except Exception as e:
            log.debug("Failed to save quota state: %s", e)

    def _load(self):
        """Load persisted quota state from disk."""
        if not self._data_file.exists():
            return
        try:
            data = json.loads(self._data_file.read_text())
            now = time.time()
            for sid, state in data.items():
                quota = self._scripts.get(sid)
                if not quota:
                    short = sid[-12:] if len(sid) > 12 else sid
                    quota = ScriptQuota(script_id=sid, display_id=short)
                    self._scripts[sid] = quota

                quota.requests_today = state.get("requests_today", 0)
                quota.first_request_at = state.get("first_request_at", 0)
                quota.reset_at = state.get("reset_at", 0)
                quota.exhausted = state.get("exhausted", False)
                quota.exhausted_at = state.get("exhausted_at", 0)
                quota.errors = state.get("errors", 0)
                quota.last_request_at = state.get("last_request_at", 0)

                # Auto-reset expired periods
                if quota.reset_at > 0 and now > quota.reset_at:
                    quota.requests_today = 0
                    quota.exhausted = False
                    quota.first_request_at = 0
                    quota.reset_at = 0

            log.info("Loaded quota state: %d scripts", len(data))
        except Exception as e:
            log.debug("Failed to load quota state: %s", e)
