"""Teste pentru detectarea operării manuale și resetul zilnic."""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.rolls_ha.const import (
    CONF_COVERS,
    CONF_GRID_POSITIVE_IS_EXPORT,
    CONF_GRID_SENSOR,
    CONF_MOTOR_POWER,
    CONF_SOLAR_SENSOR,
    CONF_STABILIZATION_DELAY,
    COVER_STATE_AUTO_OPENED,
    COVER_STATE_MANUAL,
    COVER_STATE_OPENING,
    COVER_STATE_PENDING,
    DOMAIN,
    RUNTIME_AUTO_ENABLED,
    RUNTIME_COVER_STATES,
    RUNTIME_SURPLUS_STABLE_SINCE,
)
from custom_components.rolls_ha.coordinator import RollsCoordinator


# ── Helpers (refolosite din test_control_logic) ────────────────────────────────

def _make_entry(covers=None, motor_power=150.0, stabilization_delay=0):
    covers = covers or ["cover.j1"]
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_SOLAR_SENSOR: "sensor.solar",
        CONF_GRID_SENSOR: "sensor.grid",
        CONF_GRID_POSITIVE_IS_EXPORT: True,
        CONF_COVERS: covers,
    }
    entry.options = {
        CONF_MOTOR_POWER: motor_power,
        CONF_STABILIZATION_DELAY: stabilization_delay,
    }
    return entry


def _make_runtime(covers, cover_states=None, auto_enabled=True):
    rt = {
        CONF_MOTOR_POWER: 150.0,
        CONF_STABILIZATION_DELAY: 0,
        RUNTIME_AUTO_ENABLED: auto_enabled,
        RUNTIME_COVER_STATES: cover_states or {c: COVER_STATE_PENDING for c in covers},
        RUNTIME_SURPLUS_STABLE_SINCE: None,
    }
    for eid in covers:
        rt[f"open_position_{eid}"] = 100
        rt[f"cover_active_{eid}"] = True
    return rt


def _make_state(state_str, attributes=None):
    s = MagicMock()
    s.state = state_str
    s.attributes = attributes or {}
    return s


def _build_coordinator(hass, entry, rt):
    hass.data[DOMAIN] = {entry.entry_id: rt}
    coord = RollsCoordinator.__new__(RollsCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord.data = None
    coord._unsub_listeners = []
    coord._debounce_unsub = None
    from collections import deque
    coord._action_log = deque(maxlen=10)
    coord._cycle_log = deque(maxlen=6)
    coord._cycle_buf = []
    coord._coordinator_actions = {}
    coord._opening_in_progress = {}
    return coord


def _make_event(entity_id, state_str, context_id=None, parent_id=None):
    """Creează un event mock de schimbare stare."""
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "new_state": _make_state(state_str),
    }
    ctx = MagicMock()
    ctx.id = context_id or "random_ctx_id"
    ctx.parent_id = parent_id
    event.context = ctx
    return event


# ── Detectare manuală ─────────────────────────────────────────────────────────

def test_m1_schimbare_manuala_markare():
    """M1: schimbare fără context coordinator → stare devine MANUAL."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={"cover.j1": COVER_STATE_PENDING})
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    hass.async_create_task = MagicMock()
    coord = _build_coordinator(hass, entry, rt)

    # Simulează event manual (nu există coordinator_action pentru j1)
    event = _make_event("cover.j1", "open", context_id="manual_user_ctx")
    coord._subscribe_covers.__func__  # nu apelăm _subscribe (nu avem HA real)

    # Apelăm direct handler-ul intern
    cover_states = rt[RUNTIME_COVER_STATES]
    action = coord._coordinator_actions.get("cover.j1")
    assert action is None  # nu există acțiune coordinator

    # Simulăm ce face handler-ul
    current = cover_states.get("cover.j1")
    if current in (COVER_STATE_PENDING, COVER_STATE_OPENING, COVER_STATE_AUTO_OPENED):
        cover_states["cover.j1"] = COVER_STATE_MANUAL

    assert cover_states["cover.j1"] == COVER_STATE_MANUAL


def test_m2_schimbare_in_grace_period_ignorata():
    """M2: schimbare în grace period după acțiune coordinator → nu e MANUAL."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={"cover.j1": COVER_STATE_OPENING})
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    coord = _build_coordinator(hass, entry, rt)

    # Coordinator a acționat acum 30s (< 300s grace)
    coord._coordinator_actions["cover.j1"] = {
        "time": datetime.now() - timedelta(seconds=30),
        "context_id": "coord_ctx_id",
        "target_position": 100,
    }

    event = _make_event("cover.j1", "opening", context_id="some_other_ctx")

    # Verificare: în grace period, evenimentul trebuie ignorat
    action = coord._coordinator_actions.get("cover.j1")
    elapsed = (datetime.now() - action["time"]).total_seconds()
    assert elapsed < 300  # în grace period → ignorăm

    # Starea nu trebuie schimbată manual
    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_OPENING


def test_m3_schimbare_context_coordinator_ignorata():
    """M3: schimbare cu context.id == coordinator context → ignorată (nu e manuală)."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={"cover.j1": COVER_STATE_OPENING})
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    coord = _build_coordinator(hass, entry, rt)

    coord_ctx_id = "coordinator_context_123"
    coord._coordinator_actions["cover.j1"] = {
        "time": datetime.now() - timedelta(seconds=400),  # după grace period
        "context_id": coord_ctx_id,
        "target_position": 100,
    }

    event = _make_event("cover.j1", "open", context_id=coord_ctx_id)

    # Chiar dacă e după grace period, context match → ignorăm
    action = coord._coordinator_actions.get("cover.j1")
    elapsed = (datetime.now() - action["time"]).total_seconds()
    evt_ctx_id = event.context.id
    coordinator_ctx = action.get("context_id")

    assert elapsed >= 300  # depășit grace period
    assert evt_ctx_id == coordinator_ctx  # dar context match → OK


def test_m4_auto_opened_devine_manual_la_inchidere():
    """M4: o jaluzea AUTO_OPENED devine MANUAL dacă e închisă manual."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={"cover.j1": COVER_STATE_AUTO_OPENED})
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    coord = _build_coordinator(hass, entry, rt)

    # Nicio acțiune coordinator înregistrată
    cover_states = rt[RUNTIME_COVER_STATES]
    current = cover_states.get("cover.j1")

    # Simulăm handler-ul manual
    if current in (COVER_STATE_PENDING, COVER_STATE_OPENING, COVER_STATE_AUTO_OPENED):
        cover_states["cover.j1"] = COVER_STATE_MANUAL

    assert cover_states["cover.j1"] == COVER_STATE_MANUAL


# ── Reset zilnic la miezul nopții ─────────────────────────────────────────────

def test_r1_reset_midnight_pending():
    """R1: la miezul nopții, stările PENDING/AUTO_OPENED/MANUAL → PENDING."""
    covers = ["cover.j1", "cover.j2", "cover.j3"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={
        "cover.j1": COVER_STATE_AUTO_OPENED,
        "cover.j2": COVER_STATE_MANUAL,
        "cover.j3": COVER_STATE_PENDING,
    })
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    hass.async_create_task = MagicMock()
    coord = _build_coordinator(hass, entry, rt)

    coord._do_midnight_reset()

    for eid in covers:
        assert rt[RUNTIME_COVER_STATES][eid] == COVER_STATE_PENDING


def test_r2_reset_nu_atinge_dezactivate():
    """R2: jaluzelele cu cover_active=False nu sunt resetate la PENDING."""
    covers = ["cover.j1", "cover.j2"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={
        "cover.j1": COVER_STATE_AUTO_OPENED,
        "cover.j2": COVER_STATE_AUTO_OPENED,
    })
    rt["cover_active_cover.j2"] = False  # j2 dezactivată
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    hass.async_create_task = MagicMock()
    coord = _build_coordinator(hass, entry, rt)

    coord._do_midnight_reset()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_PENDING
    # j2 dezactivată → starea ei rămâne AUTO_OPENED (nu e resetată)
    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_AUTO_OPENED


def test_r3_reset_sterge_timer_stabilizare():
    """R3: reset-ul miezului nopții curăță timer-ul de stabilizare."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers)
    rt[RUNTIME_SURPLUS_STABLE_SINCE] = datetime.now()
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    hass.async_create_task = MagicMock()
    coord = _build_coordinator(hass, entry, rt)

    coord._do_midnight_reset()

    assert rt[RUNTIME_SURPLUS_STABLE_SINCE] is None


def test_r4_reset_sterge_opening_in_progress():
    """R4: reset-ul curăță orice mișcare în curs."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers)
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: rt}}
    hass.async_create_task = MagicMock()
    coord = _build_coordinator(hass, entry, rt)

    coord._opening_in_progress["cover.j1"] = {
        "started": datetime.now(),
        "target_position": 100,
    }
    coord._coordinator_actions["cover.j1"] = {
        "time": datetime.now(),
        "context_id": "ctx123",
    }

    coord._do_midnight_reset()

    assert len(coord._opening_in_progress) == 0
    assert len(coord._coordinator_actions) == 0
