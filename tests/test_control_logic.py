"""Teste pentru logica de control a coordinator-ului.

Testele rulează fără HA real — toate dependențele sunt stub-uite în conftest.py.
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_state(state_str: str, attributes: dict | None = None):
    s = MagicMock()
    s.state = state_str
    s.attributes = attributes or {}
    return s


def _make_entry(
    covers: list[str] | None = None,
    grid_positive_is_export: bool = True,
    motor_power: float = 150.0,
    stabilization_delay: int = 0,  # 0s în teste pentru a nu aștepta
):
    covers = covers or ["cover.j1", "cover.j2", "cover.j3"]
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_SOLAR_SENSOR: "sensor.solar",
        CONF_GRID_SENSOR: "sensor.grid",
        CONF_GRID_POSITIVE_IS_EXPORT: grid_positive_is_export,
        CONF_COVERS: covers,
    }
    entry.options = {
        CONF_MOTOR_POWER: motor_power,
        CONF_STABILIZATION_DELAY: stabilization_delay,
    }
    return entry


def _make_hass(solar_w: float, grid_w: float, cover_states: dict | None = None):
    """Creează un hass mock cu senzori și stări covers configurate."""
    hass = MagicMock()

    def _get_state(entity_id: str):
        if entity_id == "sensor.solar":
            return _make_state(str(solar_w))
        if entity_id == "sensor.grid":
            return _make_state(str(grid_w))
        # Stare cover
        if cover_states and entity_id in cover_states:
            pos, st = cover_states[entity_id]
            return _make_state(st, {"current_position": pos})
        return _make_state("closed", {"current_position": 0})

    hass.states.get = _get_state
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock()
    hass.data = {}
    return hass


def _make_runtime(
    covers: list[str],
    motor_power: float = 150.0,
    stabilization_delay: int = 0,
    cover_states: dict | None = None,
    auto_enabled: bool = True,
) -> dict:
    rt = {
        CONF_MOTOR_POWER: motor_power,
        CONF_STABILIZATION_DELAY: stabilization_delay,
        RUNTIME_AUTO_ENABLED: auto_enabled,
        RUNTIME_COVER_STATES: cover_states or {c: COVER_STATE_PENDING for c in covers},
        RUNTIME_SURPLUS_STABLE_SINCE: None,
    }
    for eid in covers:
        rt[f"open_position_{eid}"] = 100
        rt[f"cover_active_{eid}"] = True
    return rt


def _build_coordinator(hass, entry, rt: dict) -> RollsCoordinator:
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


# ── S1: Deschidere normală la surplus ≥ prag ──────────────────────────────────

@pytest.mark.asyncio
async def test_s1_deschidere_la_surplus_suficient():
    """S1: surplus >= prag → prima jaluzea PENDING se deschide."""
    covers = ["cover.j1", "cover.j2"]
    entry = _make_entry(covers=covers, stabilization_delay=0)
    rt = _make_runtime(covers)
    hass = _make_hass(solar_w=1000, grid_w=200)  # grid pozitiv = export → surplus = 200W
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_OPENING
    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_PENDING
    hass.services.async_call.assert_called_once()
    call_args = hass.services.async_call.call_args
    assert call_args[0][0] == "cover"
    assert call_args[0][1] == "open_cover"
    assert call_args[0][2]["entity_id"] == "cover.j1"


@pytest.mark.asyncio
async def test_s1_pozitie_partiala():
    """S1b: target_position < 100 → se folosește set_cover_position."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers, stabilization_delay=0)
    rt = _make_runtime(covers)
    rt["open_position_cover.j1"] = 80
    hass = _make_hass(solar_w=500, grid_w=200)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    call_args = hass.services.async_call.call_args
    assert call_args[0][1] == "set_cover_position"
    assert call_args[0][2]["position"] == 80


# ── S2: Surplus insuficient ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s2_surplus_insuficient_nu_deschide():
    """S2: surplus < prag → nicio jaluzea nu se deschide."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers, motor_power=150.0, stabilization_delay=0)
    rt = _make_runtime(covers)
    hass = _make_hass(solar_w=200, grid_w=100)  # surplus = 100W < 150W
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_PENDING
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_s2_reset_timer_la_scadere_surplus():
    """S2b: timer-ul de stabilizare se resetează când surplusul scade sub prag."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers, motor_power=150.0, stabilization_delay=30)
    rt = _make_runtime(covers)
    rt[RUNTIME_SURPLUS_STABLE_SINCE] = datetime.now() - timedelta(seconds=10)
    hass = _make_hass(solar_w=200, grid_w=50)  # surplus = 50W < 150W
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_SURPLUS_STABLE_SINCE] is None
    hass.services.async_call.assert_not_called()


# ── S3: Stabilizare ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s3_asteapta_stabilizare():
    """S3: surplus suficient, dar timer-ul nu a expirat → nu acționează."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers, motor_power=150.0, stabilization_delay=10)
    rt = _make_runtime(covers, stabilization_delay=10)
    # Timer pornit acum 5 secunde (< 10s)
    rt[RUNTIME_SURPLUS_STABLE_SINCE] = datetime.now() - timedelta(seconds=5)
    hass = _make_hass(solar_w=1000, grid_w=300)  # surplus = 300W
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_PENDING
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_s3_actioneaza_dupa_stabilizare():
    """S3b: timer-ul a expirat → deschide jaluzea."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers, motor_power=150.0, stabilization_delay=10)
    rt = _make_runtime(covers, stabilization_delay=10)
    rt[RUNTIME_SURPLUS_STABLE_SINCE] = datetime.now() - timedelta(seconds=15)
    hass = _make_hass(solar_w=1000, grid_w=300)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_OPENING
    hass.services.async_call.assert_called_once()


# ── S4: Ordine corectă ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s4_ordine_deschidere():
    """S4: jaluzelele se deschid în ordinea din config, nu toate deodată."""
    covers = ["cover.j1", "cover.j2", "cover.j3"]
    entry = _make_entry(covers=covers, motor_power=150.0, stabilization_delay=0)
    rt = _make_runtime(covers)
    hass = _make_hass(solar_w=1000, grid_w=500)  # surplus = 500W (≫ 150W)
    coord = _build_coordinator(hass, entry, rt)

    # Prima rulare: deschide j1
    await coord._apply_control_logic()
    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_OPENING
    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_PENDING
    assert rt[RUNTIME_COVER_STATES]["cover.j3"] == COVER_STATE_PENDING
    assert hass.services.async_call.call_count == 1


@pytest.mark.asyncio
async def test_s4_sare_peste_auto_opened():
    """S4b: jaluzelele AUTO_OPENED sunt sărite, se continuă cu PENDING."""
    covers = ["cover.j1", "cover.j2", "cover.j3"]
    entry = _make_entry(covers=covers, stabilization_delay=0)
    rt = _make_runtime(covers, cover_states={
        "cover.j1": COVER_STATE_AUTO_OPENED,
        "cover.j2": COVER_STATE_PENDING,
        "cover.j3": COVER_STATE_PENDING,
    })
    hass = _make_hass(solar_w=1000, grid_w=200)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    # j1 deja deschisă, j2 trebuie să fie următoarea
    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_OPENING
    assert rt[RUNTIME_COVER_STATES]["cover.j3"] == COVER_STATE_PENDING


# ── S5: Control automat dezactivat ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s5_auto_off_nu_actioneaza():
    """S5: control automat dezactivat → nicio acțiune."""
    covers = ["cover.j1"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, auto_enabled=False)
    hass = _make_hass(solar_w=1000, grid_w=500)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_PENDING
    hass.services.async_call.assert_not_called()


# ── S6: Cover dezactivată ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s6_cover_dezactivata_sarire():
    """S6: cover cu cover_active=False este sărită, se trece la următoarea."""
    covers = ["cover.j1", "cover.j2"]
    entry = _make_entry(covers=covers, stabilization_delay=0)
    rt = _make_runtime(covers)
    rt["cover_active_cover.j1"] = False  # j1 dezactivată
    hass = _make_hass(solar_w=1000, grid_w=200)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    # j1 dezactivată → se deschide j2
    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_OPENING
    call_args = hass.services.async_call.call_args
    assert call_args[0][2]["entity_id"] == "cover.j2"


# ── S7: Cover MANUAL sărită ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s7_manual_sarita():
    """S7: cover MANUAL este sărită în coadă."""
    covers = ["cover.j1", "cover.j2"]
    entry = _make_entry(covers=covers, stabilization_delay=0)
    rt = _make_runtime(covers, cover_states={
        "cover.j1": COVER_STATE_MANUAL,
        "cover.j2": COVER_STATE_PENDING,
    })
    hass = _make_hass(solar_w=1000, grid_w=200)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_OPENING


# ── S8: Toate jaluzelele procesate ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s8_toate_procesate_stop():
    """S8: când toate jaluzelele sunt AUTO_OPENED sau MANUAL, nu se acționează."""
    covers = ["cover.j1", "cover.j2"]
    entry = _make_entry(covers=covers)
    rt = _make_runtime(covers, cover_states={
        "cover.j1": COVER_STATE_AUTO_OPENED,
        "cover.j2": COVER_STATE_MANUAL,
    })
    hass = _make_hass(solar_w=1000, grid_w=500)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    hass.services.async_call.assert_not_called()


# ── S9: Convenție rețea inversată ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s9_conventie_retea_inversa():
    """S9: grid_positive_is_export=False → semn inversat, surplus calculat corect."""
    covers = ["cover.j1"]
    entry = _make_entry(
        covers=covers,
        grid_positive_is_export=False,  # pozitiv = import
        motor_power=150.0,
        stabilization_delay=0,
    )
    rt = _make_runtime(covers)
    # grid = -200 (import) → grid_export = -(-200) = 200W → surplus = 200W ≥ 150W
    hass = _make_hass(solar_w=500, grid_w=-200)
    coord = _build_coordinator(hass, entry, rt)

    await coord._apply_control_logic()

    assert rt[RUNTIME_COVER_STATES]["cover.j1"] == COVER_STATE_OPENING


# ── S10: Surplus virtual cu motor activ ───────────────────────────────────────

@pytest.mark.asyncio
async def test_s10_surplus_virtual_motor_activ():
    """S10: motor activ adaugă puterea înapoi → evită oprire prematură a cozii."""
    covers = ["cover.j1", "cover.j2"]
    entry = _make_entry(covers=covers, motor_power=150.0, stabilization_delay=0)
    rt = _make_runtime(covers, cover_states={
        "cover.j1": COVER_STATE_OPENING,
        "cover.j2": COVER_STATE_PENDING,
    })
    hass = _make_hass(solar_w=500, grid_w=50)  # surplus aparent = 50W (< 150W)
    coord = _build_coordinator(hass, entry, rt)

    # Simulează că j1 se deschide (in_progress)
    coord._opening_in_progress["cover.j1"] = {
        "started": datetime.now() - timedelta(seconds=10),
        "target_position": 100,
    }
    # Simulează acoperă în mișcare
    def _get_state_moving(entity_id):
        if entity_id == "sensor.solar":
            return _make_state("500")
        if entity_id == "sensor.grid":
            return _make_state("50")
        if entity_id == "cover.j1":
            return _make_state("opening", {"current_position": 50})
        return _make_state("closed", {"current_position": 0})
    hass.states.get = _get_state_moving

    await coord._apply_control_logic()

    # j1 încă în mișcare → nu se trece la j2 (trebuie să aștepte)
    assert rt[RUNTIME_COVER_STATES]["cover.j2"] == COVER_STATE_PENDING
    hass.services.async_call.assert_not_called()
