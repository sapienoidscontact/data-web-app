"""
GeminiSentinel — Dual-key Gemini API client with automatic failover.

Environment variables (set in .env):
    GEMINI_KEY_PRIMARY   primary API key  (required for AI features)
    GEMINI_KEY_BACKUP    backup API key   (optional but recommended)
    GEMINI_MODEL         model name       (default: gemini-1.5-flash)
    GEMINI_DAILY_LIMIT   display-only request counter reference (default: 1500)
                         — does NOT block requests; only used for the status widget.
                         — Gemini Flash free tier is 1500 RPD.

Quota policy:
    Keys are blocked ONLY when the real Gemini API returns a 429 / ResourceExhausted
    or 503 / ServiceUnavailable response.  The soft GEMINI_DAILY_LIMIT counter is
    tracked for visibility but never used to gate requests.

    A single safety guard exists to prevent runaway error loops:
    prompts longer than _MAX_PROMPT_CHARS are truncated before sending.

Public API:
    sentinel = get_sentinel()
    text     = sentinel.generate_insight(prompt)
    status   = sentinel.get_status()      → dict   (for sidebar widget)
    log      = sentinel.switch_log()      → list   (for debugging)
"""

import os
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

from loguru import logger

# ── Loguru configuration ──────────────────────────────────────────────────────
logger.remove()
logger.add(sys.stderr, level="WARNING", colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")

_log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
os.makedirs(_log_dir, exist_ok=True)
logger.add(
    os.path.join(_log_dir, "sapienoids_{time:YYYY-MM-DD}.log"),
    rotation="00:00",       # new file every midnight
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

# ── Constants ─────────────────────────────────────────────────────────────────
# Display-only counter reference — does NOT block requests.
_DAILY_LIMIT    = int(os.getenv("GEMINI_DAILY_LIMIT", "1500"))
# Safety cap: truncate runaway prompts that would waste the entire daily token budget.
_MAX_PROMPT_CHARS = int(os.getenv("GEMINI_MAX_PROMPT_CHARS", "30000"))

# Model to use — env var overrides. Auto-selects smartest available free model
# by trying each in order until one succeeds (NotFound → next candidate).
# Priority: 2.5 series (best reasoning) → 2.0 series → 1.5 legacy fallbacks.
_MODEL_NAME = os.getenv("GEMINI_MODEL", "")   # empty = auto-select
_MODEL_FALLBACK_ORDER = [
    "gemini-2.5-flash",                  # smartest + fast + free (primary target)
    "gemini-2.5-flash-preview-04-17",    # preview alias for same
    "gemini-2.5-pro",                    # most capable free model
    "gemini-2.5-pro-preview-05-06",      # preview alias for same
    "gemini-2.0-flash",                  # stable fallback
    "gemini-2.0-flash-lite",             # lightweight fallback
    "gemini-1.5-flash",                  # legacy fallback
    "gemini-1.5-pro",                    # legacy fallback
]

_FALLBACK_MSGS = [
    (
        "AI insights are temporarily unavailable — both API keys have reached "
        "their daily quota. All analytics features continue to work normally. "
        "Quota resets at midnight."
    ),
    (
        "The AI assistant is at capacity for today (quota exceeded on both keys). "
        "Charts, statistics, and ML tools are fully available without AI."
    ),
    (
        "Daily AI quota reached. To extend capacity, add a second Gemini key as "
        "GEMINI_KEY_BACKUP in your .env file (free at aistudio.google.com)."
    ),
]


# ── Key state dataclass ───────────────────────────────────────────────────────
@dataclass
class _KeyState:
    name: str
    key: str
    request_count: int = 0
    last_reset: date = field(default_factory=date.today)
    hard_exhausted: bool = False  # flipped on 429 / 503

    @property
    def configured(self) -> bool:
        """True if a non-empty key string is present."""
        return bool(self.key and self.key.strip())

    @property
    def usage_pct(self) -> float:
        """Fraction of display reference consumed (0.0–1.0+). Display only."""
        return self.request_count / _DAILY_LIMIT if _DAILY_LIMIT > 0 else 0.0

    @property
    def available(self) -> bool:
        """True when this key can accept a new request.
        Blocked ONLY by a real API 429/503 — never by the soft counter."""
        return self.configured and not self.hard_exhausted


# ── GeminiSentinel ────────────────────────────────────────────────────────────
class GeminiSentinel:
    """
    Dual-key Gemini API client with automatic failover.

    Routes all requests through PRIMARY by default.
    Switches to BACKUP automatically when any of the following occur:
      • HTTP 429 ResourceExhausted received
      • HTTP 503 ServiceUnavailable received
      • PRIMARY reaches GEMINI_FAILOVER_PCT of its daily quota (proactive)

    If both keys are exhausted: returns a graceful fallback string.
    Never raises to the caller.
    """

    def __init__(self) -> None:
        """Load both keys, resolve active model, and initialise routing state."""
        self._keys: List[_KeyState] = [
            _KeyState(name="PRIMARY", key=os.getenv("GEMINI_KEY_PRIMARY", "")),
            _KeyState(name="BACKUP",  key=os.getenv("GEMINI_KEY_BACKUP",  "")),
        ]
        self._active_idx: int = 0
        self._switch_log: List[dict] = []
        # Resolved model — may be updated by _resolve_model() on first successful call
        self._model: str = _MODEL_NAME if _MODEL_NAME else _MODEL_FALLBACK_ORDER[0]
        self._model_confirmed: bool = False  # set True only after a successful API call

        if not self._keys[0].configured:
            logger.warning(
                "GEMINI_KEY_PRIMARY is not set. AI features will use fallback responses. "
                "Add your key to the .env file (free at aistudio.google.com)."
            )
        else:
            backup_note = "BACKUP key also configured." if self._keys[1].configured else "No BACKUP key configured."
            logger.info(
                f"GeminiSentinel ready. Model: {self._model} (auto-fallback enabled). "
                f"Quota gate: real API 429 only. {backup_note}"
            )

    # ── Public methods ────────────────────────────────────────────────────────

    def generate_insight(self, prompt: str) -> str:
        """
        Send a natural-language prompt to Gemini and return the response text.

        Handles key selection, quota tracking, and failover internally.
        Callers receive plain text and never interact with key logic.

        Args:
            prompt: The full prompt string to send to Gemini.

        Returns:
            Response text from Gemini, or a graceful fallback string.
        """
        self._reset_if_new_day()
        return self._track_and_route(prompt)

    def get_status(self) -> dict:
        """
        Return key health information for the Streamlit sidebar widget.

        Returns:
            dict with keys:
                keys        list[dict]  — one entry per key with name/configured/
                                          available/active/requests/pct/limit
                active_key  str         — 'PRIMARY' or 'BACKUP'
                total_today int         — total requests across both keys today
                model       str         — Gemini model in use
                both_down   bool        — True when neither key can serve requests
        """
        self._reset_if_new_day()
        key_list = []
        for i, ks in enumerate(self._keys):
            key_list.append({
                "name":       ks.name,
                "configured": ks.configured,
                "available":  ks.available,
                "active":     i == self._active_idx,
                "requests":   ks.request_count,
            })
        return {
            "keys":        key_list,
            "active_key":  self._keys[self._active_idx].name,
            "total_today": sum(k.request_count for k in self._keys),
            "model":       self._model,
            "both_down":   not any(k.available for k in self._keys),
        }

    def switch_log(self) -> List[dict]:
        """
        Return a copy of the failover event log.

        Each entry: {ts, from, to, reason}
        Useful for the diagnostics panel or debug logging.
        """
        return list(self._switch_log)

    # ── Internal methods ──────────────────────────────────────────────────────

    def _reset_if_new_day(self) -> None:
        """
        Reset request counters for any key whose last_reset date is before today.
        Also clears hard_exhausted flags so keys become usable again at midnight.
        Called at the start of every generate_insight() and get_status() call.
        """
        today = date.today()
        for ks in self._keys:
            if ks.last_reset < today:
                logger.info(
                    f"Daily counter reset for {ks.name} key "
                    f"(was {ks.request_count} requests on {ks.last_reset})"
                )
                ks.request_count   = 0
                ks.last_reset      = today
                ks.hard_exhausted  = False

    def _track_and_route(self, prompt: str) -> str:
        """
        Core routing logic.

        Error classification:
          quota    (429/ResourceExhausted/ServiceUnavailable) → mark key exhausted, switch key
          not_found (NotFound/404) → model unavailable, try next model in fallback list
          permanent (PermissionDenied/InvalidArgument/Unauthenticated) → bad key, clear message
          transient (everything else) → retry once with 0.5s pause

        Keys are blocked ONLY by real API quota errors, never by a soft counter.
        Prompts are truncated if they exceed _MAX_PROMPT_CHARS (safety only).
        """
        import time

        if len(prompt) > _MAX_PROMPT_CHARS:
            logger.warning(
                f"Prompt truncated from {len(prompt):,} to {_MAX_PROMPT_CHARS:,} chars."
            )
            prompt = prompt[:_MAX_PROMPT_CHARS] + "\n[...prompt truncated for safety...]"

        import google.generativeai as genai

        # Build ordered model list: confirmed model first, then full fallback chain
        if self._model_confirmed:
            models_to_try = [self._model]
        else:
            seen = set()
            models_to_try = []
            for m in [self._model] + _MODEL_FALLBACK_ORDER:
                if m not in seen:
                    seen.add(m)
                    models_to_try.append(m)

        for model_name in models_to_try:
            # Each model gets up to 2 key attempts (PRIMARY then BACKUP on quota error)
            for key_attempt in range(2):
                ks = self._pick_available_key()
                if ks is None:
                    # Both keys quota-exhausted — no point trying more models
                    logger.warning("Both API keys quota-exhausted.")
                    return self._get_fallback()

                try:
                    genai.configure(api_key=ks.key)
                    response = genai.GenerativeModel(model_name).generate_content(prompt)
                    ks.request_count += 1
                    self._model = model_name
                    self._model_confirmed = True
                    logger.debug(
                        f"Gemini OK | model={model_name} | key={ks.name} | "
                        f"requests today: {ks.request_count}"
                    )
                    return response.text

                except Exception as exc:
                    cls_name = type(exc).__name__
                    msg      = str(exc).lower()

                    is_quota = any(s in cls_name.lower() or s in msg for s in
                                   ("resourceexhausted", "serviceunavailable",
                                    "quotaexceeded", "quota exceeded", "429"))
                    is_not_found = ("notfound" in cls_name.lower()
                                    or "model not found" in msg
                                    or ("not found" in msg and "model" in msg))
                    is_perm = any(s in cls_name.lower() or s in msg for s in
                                  ("permissiondenied", "unauthenticated",
                                   "invalid api key", "api key not valid"))

                    if is_quota:
                        logger.warning(f"Quota on {ks.name} ({cls_name}) — switching key.")
                        ks.hard_exhausted = True
                        self._execute_switch(reason=f"{cls_name} on {ks.name}")
                        # continue inner loop → retry same model with other key

                    elif is_not_found:
                        logger.warning(f"Model '{model_name}' not available — trying next.")
                        break  # exit key loop → outer loop tries next model

                    elif is_perm:
                        logger.error(f"API key rejected ({ks.name}): {exc}")
                        return (
                            "Gemini API key rejected — please re-enter your key in the "
                            "sidebar (free at aistudio.google.com)."
                        )

                    else:
                        # Transient: retry once with a short pause
                        if key_attempt == 0:
                            logger.warning(f"Transient error ({cls_name}) — retrying once.")
                            time.sleep(0.5)
                        else:
                            logger.error(f"Failed after retry ({model_name}): {exc}")
                            break  # try next model

        logger.error("All model/key combinations failed.")
        return self._get_fallback()

    def _next_fallback_model(self) -> Optional[str]:
        """Return the next model in the fallback list after the current one, or None."""
        try:
            idx = _MODEL_FALLBACK_ORDER.index(self._model)
        except ValueError:
            idx = -1
        next_idx = idx + 1
        return _MODEL_FALLBACK_ORDER[next_idx] if next_idx < len(_MODEL_FALLBACK_ORDER) else None

    def _pick_available_key(self) -> Optional[_KeyState]:
        """Return the active key if available, else try the other key."""
        if self._keys[self._active_idx].available:
            return self._keys[self._active_idx]
        other = 1 - self._active_idx
        if self._keys[other].available:
            self._active_idx = other
            return self._keys[other]
        return None

    def _execute_switch(self, reason: str) -> None:
        """Switch the active index and record a timestamped log entry."""
        from_name = self._keys[self._active_idx].name
        self._active_idx = 1 - self._active_idx
        to_name = self._keys[self._active_idx].name
        entry = {
            "ts":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "from":   from_name,
            "to":     to_name,
            "reason": reason,
        }
        self._switch_log.append(entry)
        logger.warning(
            f"[GeminiSentinel] KEY SWITCH  {from_name} → {to_name}  |  {reason}"
        )

    @staticmethod
    def _get_fallback() -> str:
        """Return a random graceful fallback message (no network call)."""
        return random.choice(_FALLBACK_MSGS)


# ── Module-level singleton ────────────────────────────────────────────────────
_sentinel: Optional[GeminiSentinel] = None


def get_sentinel() -> GeminiSentinel:
    """
    Return the process-level GeminiSentinel singleton.

    Import and call this everywhere in the app:
        from core.ai import get_sentinel
        result = get_sentinel().generate_insight("Summarise this data...")
    """
    global _sentinel
    if _sentinel is None:
        _sentinel = GeminiSentinel()
    return _sentinel
