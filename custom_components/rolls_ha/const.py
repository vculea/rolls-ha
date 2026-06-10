"""Constants for Rolls Solar Controller."""

DOMAIN = "rolls_ha"

# ── Config entry keys — stored in `data`, require Reconfigure to change ────────
CONF_SOLAR_SENSOR = "solar_sensor"
CONF_GRID_SENSOR = "grid_sensor"
CONF_GRID_POSITIVE_IS_EXPORT = "grid_positive_is_export"
CONF_COVERS = "covers"  # list[str] — cover entity IDs in activation order

# ── Options keys — runtime-adjustable (Options flow or number entities) ─────────
CONF_MOTOR_POWER = "motor_power"
CONF_STABILIZATION_DELAY = "stabilization_delay"

# ── hass.data runtime keys ───────────────────────────────────────────────────────
RUNTIME_AUTO_ENABLED = "auto_enabled"
RUNTIME_COVER_STATES = "cover_states"       # dict: entity_id → state string
RUNTIME_SURPLUS_STABLE_SINCE = "surplus_stable_since"  # datetime | None

# Per-cover runtime keys (keyed by entity_id):
#   f"open_position_{entity_id}"  → int  (0–100, default 100)
#   f"cover_active_{entity_id}"   → bool (default True)

# ── Cover automation state values ────────────────────────────────────────────────
COVER_STATE_PENDING = "pending"
COVER_STATE_OPENING = "opening"
COVER_STATE_AUTO_OPENED = "auto_opened"
COVER_STATE_MANUAL = "manual"

# ── Default values ────────────────────────────────────────────────────────────────
DEFAULT_MOTOR_POWER = 150.0         # W — estimated motor draw while opening
DEFAULT_STABILIZATION_DELAY = 10    # seconds — surplus must stay above threshold
DEFAULT_OPEN_POSITION = 100         # % — fully open
OPENING_TIMEOUT = 120               # seconds — max wait for cover to finish moving

# ── Platforms ─────────────────────────────────────────────────────────────────────
PLATFORMS = ["button", "switch", "number", "sensor"]

# ── Status strings (used by sensor entities) ──────────────────────────────────────
STATUS_WAITING_SURPLUS = "Așteptare surplus"
STATUS_OPENING = "Deschidere automată"
STATUS_AUTO_OPENED = "Deschis automat"
STATUS_MANUAL = "Control manual"
STATUS_DISABLED = "Dezactivat"
STATUS_GLOBAL_OFF = "Control automat oprit"
