"""Stub-uri minimale pentru modulele homeassistant.

Permit rularea testelor fără o instalare completă de HA.
"""
import sys
import types
from unittest.mock import MagicMock

# ── Stub module factory ────────────────────────────────────────────────────────

def _stub(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# homeassistant.core
core_mod = _stub(
    "homeassistant.core",
    HomeAssistant=MagicMock,
    Context=MagicMock,
    callback=lambda f: f,  # decorator no-op
)

# homeassistant.const
_stub(
    "homeassistant.const",
    STATE_ON="on",
    STATE_OFF="off",
    STATE_UNAVAILABLE="unavailable",
    STATE_UNKNOWN="unknown",
)

# homeassistant.config_entries
_stub("homeassistant.config_entries", ConfigEntry=MagicMock)

# homeassistant.helpers.update_coordinator
class _FakeCoordinator:
    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.data = None
        self._unsub_listeners = []
        self._debounce_unsub = None

    async def async_config_entry_first_refresh(self):
        pass

    async def async_refresh(self):
        self.data = await self._async_update_data()

    async def _async_update_data(self):
        return {}


_stub(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=_FakeCoordinator,
    UpdateFailed=Exception,
    CoordinatorEntity=MagicMock,
)

# homeassistant.helpers.event
_stub(
    "homeassistant.helpers.event",
    async_track_state_change_event=MagicMock(return_value=lambda: None),
    async_track_time_change=MagicMock(return_value=lambda: None),
    async_call_later=MagicMock(return_value=lambda: None),
)

# homeassistant.helpers.restore_state
_stub("homeassistant.helpers.restore_state", RestoreEntity=object)

# homeassistant.helpers.entity
_stub("homeassistant.helpers.entity", DeviceInfo=dict)

# homeassistant.helpers.entity_platform
_stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock)

# homeassistant.helpers.selector
_stub(
    "homeassistant.helpers.selector",
    EntitySelector=MagicMock,
    EntitySelectorConfig=MagicMock,
    NumberSelector=MagicMock,
    NumberSelectorConfig=MagicMock,
    NumberSelectorMode=MagicMock(BOX="box", SLIDER="slider"),
    SelectOptionDict=dict,
    SelectSelector=MagicMock,
    SelectSelectorConfig=MagicMock,
    SelectSelectorMode=MagicMock(LIST="list"),
    TextSelector=MagicMock,
    TextSelectorConfig=MagicMock,
)

# homeassistant.components.switch
_stub("homeassistant.components.switch", SwitchEntity=object)

# homeassistant.components.number
_stub(
    "homeassistant.components.number",
    NumberEntity=object,
    NumberMode=MagicMock(BOX="box", SLIDER="slider"),
)

# homeassistant.components.sensor
_stub(
    "homeassistant.components.sensor",
    SensorEntity=object,
    SensorDeviceClass=MagicMock(POWER="power"),
)

# homeassistant
_stub("homeassistant", config_entries=sys.modules["homeassistant.config_entries"])

# homeassistant.util.dt
import datetime as _dt

class _DtUtil:
    @staticmethod
    def now():
        return _dt.datetime.now()

_stub("homeassistant.util", dt=_DtUtil())
_stub("homeassistant.util.dt", now=_DtUtil.now)
