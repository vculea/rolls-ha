"""DataUpdateCoordinator for Rolls Solar Controller.

Logica de control:

  surplus_virtual = grid_export
                    + motor_power  ×  nr_jaluzele_aflate_în_mișcare

  Coada de deschidere (per zi):
    - Jaluzele în stare PENDING sunt deschise pe rând când surplus_virtual >= motor_power
    - Surplusul trebuie să fie stabil (>= prag) timp de `stabilization_delay` secunde
    - După trimiterea comenzii se așteptă finalizarea mișcării înainte de jaluzea urm.
    - Dacă surplusul scade sub prag, coada se oprește (jaluzele deja deschise rămân)

  Detectare operare manuală:
    - La fiecare serviciu apelat de coordinator se reține context_id + timestamp
    - Orice schimbare de stare pe un cover cu context diferit → MANUAL (ignorată azi)

  Reset zilnic la miezul nopții:
    - Toate stările (PENDING/OPENING/AUTO_OPENED/MANUAL) → PENDING
    - Covers dezactivate (cover_active = False) nu sunt atinse
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_SOLAR_SENSOR,
    CONF_GRID_SENSOR,
    CONF_GRID_POSITIVE_IS_EXPORT,
    CONF_COVERS,
    CONF_MOTOR_POWER,
    RUNTIME_AUTO_ENABLED,
    RUNTIME_COVER_STATES,
    RUNTIME_SURPLUS_STABLE_SINCE,
    COVER_STATE_PENDING,
    COVER_STATE_OPENING,
    COVER_STATE_AUTO_OPENED,
    COVER_STATE_MANUAL,
    DEFAULT_MOTOR_POWER,
    DEFAULT_OPEN_POSITION,
    OPENING_TIMEOUT,
    STATUS_WAITING_SURPLUS,
    STATUS_OPENING,
    STATUS_AUTO_OPENED,
    STATUS_MANUAL,
    STATUS_DISABLED,
    STATUS_GLOBAL_OFF,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

# Stările în care coordinator-ul poate detecta operare manuală
_TRACKABLE_STATES = (COVER_STATE_PENDING, COVER_STATE_OPENING, COVER_STATE_AUTO_OPENED)

# Timp de grație după o acțiune a coordinator-ului (pentru mișcări lungi)
_COORDINATOR_GRACE_SECONDS = 300


class RollsCoordinator(DataUpdateCoordinator):
    """Gestionează controlul reactiv + polling al jaluzelelor pe baza surplusului solar."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.entry = entry
        self._unsub_listeners: list = []
        self._debounce_unsub = None
        self._action_log: deque[str] = deque(maxlen=10)
        self._cycle_log: deque[str] = deque(maxlen=6)
        self._cycle_buf: list[str] = []

        # entity_id → {"time": datetime, "context_id": str, "target_position": int}
        self._coordinator_actions: dict[str, dict] = {}

        # entity_id → {"started": datetime, "target_position": int}
        self._opening_in_progress: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_config_entry_first_refresh(self) -> None:
        """Subscrie la senzori + cover + miezul nopții, apoi face primul refresh."""
        await super().async_config_entry_first_refresh()
        self._subscribe_sensors()
        self._subscribe_covers()
        self._subscribe_midnight_reset()

    def _subscribe_sensors(self) -> None:
        """Refresh reactiv când senzorii solar / rețea se schimbă."""
        cfg = self.entry.data
        watch = [cfg[CONF_SOLAR_SENSOR], cfg[CONF_GRID_SENSOR]]

        @callback
        def _sensor_changed(event) -> None:  # noqa: ANN001
            if self._debounce_unsub is not None:
                self._debounce_unsub()

            def _do_refresh(_now) -> None:  # noqa: ANN001
                self._debounce_unsub = None
                self.hass.async_create_task(self.async_refresh())

            self._debounce_unsub = async_call_later(self.hass, 3, _do_refresh)

        unsub = async_track_state_change_event(self.hass, watch, _sensor_changed)
        self._unsub_listeners.append(unsub)

    def _subscribe_covers(self) -> None:
        """Detectează operarea manuală a oricărei jaluzele gestionate."""
        covers_list: list[str] = self.entry.data.get(CONF_COVERS, [])
        if not covers_list:
            return

        @callback
        def _cover_changed(event) -> None:  # noqa: ANN001
            entity_id: str | None = event.data.get("entity_id")
            if entity_id is None:
                return

            new_state = event.data.get("new_state")
            if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return

            # Verifică dacă schimbarea a fost inițiată de coordinator
            action = self._coordinator_actions.get(entity_id)
            if action:
                elapsed = (datetime.now() - action["time"]).total_seconds()
                evt_ctx = event.context
                coordinator_ctx_id = action.get("context_id")

                # Potrivire context (cel mai precis) SAU grație de timp
                if elapsed < _COORDINATOR_GRACE_SECONDS:
                    if coordinator_ctx_id is not None and evt_ctx is not None:
                        if (
                            evt_ctx.id == coordinator_ctx_id
                            or evt_ctx.parent_id == coordinator_ctx_id
                        ):
                            return  # schimbare inițiată de coordinator
                    else:
                        return  # în grace period, presupunem coordinator

            # Schimbare manuală
            rt = self._runtime()
            cover_states: dict = rt.get(RUNTIME_COVER_STATES, {})
            current = cover_states.get(entity_id)

            if current in _TRACKABLE_STATES:
                cover_states[entity_id] = COVER_STATE_MANUAL
                self._coordinator_actions.pop(entity_id, None)
                self._opening_in_progress.pop(entity_id, None)
                self._log_action(
                    f"Jaluzea {entity_id}: operare manuală detectată → ignorată azi"
                )
                self.hass.async_create_task(self.async_refresh())

        unsub = async_track_state_change_event(self.hass, covers_list, _cover_changed)
        self._unsub_listeners.append(unsub)

    def _subscribe_midnight_reset(self) -> None:
        """Resetează stările tuturor jaluzelelor la miezul nopții."""

        @callback
        def _midnight_reset(_now) -> None:  # noqa: ANN001
            self._do_midnight_reset()

        unsub = async_track_time_change(
            self.hass, _midnight_reset, hour=0, minute=0, second=0
        )
        self._unsub_listeners.append(unsub)

    def reset_states(self) -> None:
        """Reset manual al stărilor (apelabil din button entity)."""
        self._do_midnight_reset()

    def _do_midnight_reset(self) -> None:
        """Resetează stările la PENDING (exceptând dezactivate)."""
        rt = self._runtime()
        cover_states: dict = rt.get(RUNTIME_COVER_STATES, {})
        covers_list: list[str] = self.entry.data.get(CONF_COVERS, [])
        reset_count = 0

        for eid in covers_list:
            if rt.get(f"cover_active_{eid}", True):
                cover_states[eid] = COVER_STATE_PENDING
                reset_count += 1

        rt[RUNTIME_SURPLUS_STABLE_SINCE] = None
        self._opening_in_progress.clear()
        self._coordinator_actions.clear()

        self._log_action(
            f"Reset miezul nopții: {reset_count} jaluzele → PENDING"
        )
        self.hass.async_create_task(self.async_refresh())

    @callback
    def async_cancel_subscriptions(self) -> None:
        """Anulează toate subscripțiile la schimbări de stare."""
        if self._debounce_unsub is not None:
            self._debounce_unsub()
            self._debounce_unsub = None
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Rulează logica de control și returnează un snapshot pentru entități."""
        try:
            await self._apply_control_logic()
        except Exception as exc:  # noqa: BLE001
            raise UpdateFailed(f"Eroare logică control: {exc}") from exc
        return self._build_snapshot()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _runtime(self) -> dict:
        """Returnează store-ul mutable pentru acest config entry."""
        return self.hass.data[DOMAIN][self.entry.entry_id]

    def _log_action(self, message: str) -> None:
        """Log INFO + adaugă în log-ul de acțiuni (maxim 10 intrări)."""
        _LOGGER.info(message)
        self._action_log.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        )

    def _clog(self, line: str) -> None:
        """Adaugă o linie debug în buffer-ul ciclului curent."""
        _LOGGER.debug(line)
        self._cycle_buf.append(line)

    def _float_state(self, entity_id: str) -> float | None:
        """Citește starea unui senzor numeric; returnează None dacă indisponibil."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _cover_position(self, entity_id: str) -> int | None:
        """Returnează poziția curentă a unui cover (0–100); None dacă necunoscută."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        pos = state.attributes.get("current_position")
        if pos is not None:
            try:
                return int(pos)
            except (ValueError, TypeError):
                pass
        # Fallback pe stare textuală
        if state.state == "open":
            return 100
        if state.state == "closed":
            return 0
        return None

    def _cover_is_moving(self, entity_id: str) -> bool:
        """Returnează True dacă jaluzea se mișcă (opening / closing)."""
        state = self.hass.states.get(entity_id)
        return state is not None and state.state in ("opening", "closing")

    # ------------------------------------------------------------------
    # Control logic
    # ------------------------------------------------------------------

    async def _apply_control_logic(self) -> None:  # noqa: PLR0912, PLR0915
        cfg = self.entry.data
        rt = self._runtime()
        self._cycle_buf = []

        auto_enabled: bool = rt.get(RUNTIME_AUTO_ENABLED, True)
        motor_power: float = rt.get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER)
        cover_states: dict = rt.get(RUNTIME_COVER_STATES, {})

        # ── Citire senzori ───────────────────────────────────────────────
        solar_raw = self._float_state(cfg[CONF_SOLAR_SENSOR])
        grid_raw = self._float_state(cfg[CONF_GRID_SENSOR])

        opts = self.entry.options
        grid_convention_override = opts.get("grid_convention_override")
        if grid_convention_override is not None:
            grid_positive_is_export = grid_convention_override == "export"
        else:
            grid_positive_is_export: bool = cfg.get(CONF_GRID_POSITIVE_IS_EXPORT, True)

        # Normalizare: grid_export > 0 = exportăm (surplus), < 0 = importăm
        grid_export: float = 0.0
        if grid_raw is not None:
            grid_export = grid_raw if grid_positive_is_export else -grid_raw

        # ── Surplus virtual ──────────────────────────────────────────────
        # Adaugă puterea motoarelor active pentru a evita false-negative
        virtual_surplus = grid_export

        for eid, opening_info in list(self._opening_in_progress.items()):
            elapsed = (datetime.now() - opening_info["started"]).total_seconds()
            target_pos = opening_info["target_position"]
            current_pos = self._cover_position(eid)
            still_moving = self._cover_is_moving(eid)

            finished = (
                elapsed > OPENING_TIMEOUT
                or (not still_moving and elapsed > 5)
                or (current_pos is not None and current_pos >= target_pos - 2)
            )

            if finished:
                self._opening_in_progress.pop(eid, None)
                # Nu ștergem coordinator_action imediat — mai lăsăm 60s grație
                cover_states[eid] = COVER_STATE_AUTO_OPENED
                actual_pos = current_pos if current_pos is not None else target_pos
                self._log_action(
                    f"Jaluzea {eid}: deschidere finalizată la {actual_pos}%"
                )
            else:
                # Motor încă rulează — adaugă puterea înapoi la surplus virtual
                virtual_surplus += motor_power

        self._clog(
            f"solar={f'{solar_raw:.0f}' if solar_raw is not None else 'N/A'}W  "
            f"rețea={grid_export:+.0f}W  surplus={virtual_surplus:.0f}W  "
            f"prag={motor_power:.0f}W  auto={'ON' if auto_enabled else 'OFF'}"
        )

        # ── Control dezactivat ───────────────────────────────────────────
        if not auto_enabled:
            self._clog("Control automat dezactivat — skip")
            self._flush_cycle_log()
            return

        # ── Întrerupem deschiderea dacă surplusul a scăzut sub prag ──────
        if self._opening_in_progress and virtual_surplus < motor_power:
            for eid in list(self._opening_in_progress.keys()):
                cover_states[eid] = COVER_STATE_PENDING
                await self._stop_cover(eid)
                self._opening_in_progress.pop(eid)
            self._log_action(
                f"Surplus {virtual_surplus:.0f}W < prag {motor_power:.0f}W "
                f"— jaluzea oprită, revine la PENDING"
            )
            self._flush_cycle_log()
            return

        # ── Așteptăm finalizarea jaluzea curentă ─────────────────────────
        if self._opening_in_progress:
            in_progress_eid = next(iter(self._opening_in_progress))
            elapsed = (
                datetime.now() - self._opening_in_progress[in_progress_eid]["started"]
            ).total_seconds()
            self._clog(
                f"Jaluzea {in_progress_eid} se deschide ({elapsed:.0f}s)..."
            )
            self._flush_cycle_log()
            return

        # ── Găsim prima jaluzea PENDING care chiar necesită deschidere ─────
        # Jaluzele deja la poziția țintă sunt marcate AUTO_OPENED instant,
        # fără a reseta timer-ul de stabilizare, și se trece imediat la urm.
        covers_list: list[str] = cfg.get(CONF_COVERS, [])
        next_pending_eid: str | None = None
        target_pos: int = DEFAULT_OPEN_POSITION
        current_pos: int | None = None

        while True:
            candidate: str | None = None
            for eid in covers_list:
                active = rt.get(f"cover_active_{eid}", True)
                if active and cover_states.get(eid) == COVER_STATE_PENDING:
                    candidate = eid
                    break

            if candidate is None:
                self._clog("Nicio jaluzea PENDING — toate procesate sau dezactivate")
                self._flush_cycle_log()
                return

            target_pos = rt.get(f"open_position_{candidate}", DEFAULT_OPEN_POSITION)
            current_pos = self._cover_position(candidate)
            if current_pos is not None and current_pos >= target_pos - 2:
                cover_states[candidate] = COVER_STATE_AUTO_OPENED
                self._log_action(
                    f"Jaluzea {candidate}: deja la {current_pos}% "
                    f"(țintă {target_pos}%) — marcată ca deschisă automat, trec la urm."
                )
                # Nu resetăm timer-ul; trecem imediat la urm. jaluzea din coadă
                continue

            next_pending_eid = candidate
            break

        # ── Deschidere imediată când surplusul e suficient ───────────────
        if virtual_surplus >= motor_power:
            self._clog(
                f"Surplus {virtual_surplus:.0f}W ≥ prag {motor_power:.0f}W "
                f"— deschid {next_pending_eid}"
            )
            await self._open_cover(next_pending_eid, target_pos, rt, cover_states)
        else:
            self._clog(
                f"Surplus {virtual_surplus:.0f}W < prag {motor_power:.0f}W "
                f"— așteptare surplus"
            )

        self._flush_cycle_log()

    async def _open_cover(
        self,
        entity_id: str,
        target_position: int,
        rt: dict,
        cover_states: dict,
    ) -> None:
        """Trimite comanda de deschidere și înregistrează acțiunea coordinator-ului."""
        cover_states[entity_id] = COVER_STATE_OPENING

        self._opening_in_progress[entity_id] = {
            "started": datetime.now(),
            "target_position": target_position,
        }

        # Creează un Context propriu pentru a putea distinge de acțiuni manuale
        ctx = Context()
        self._coordinator_actions[entity_id] = {
            "time": datetime.now(),
            "context_id": ctx.id,
            "target_position": target_position,
        }

        if target_position < 100:
            service_name = "set_cover_position"
            service_data: dict = {"entity_id": entity_id, "position": target_position}
        else:
            service_name = "open_cover"
            service_data = {"entity_id": entity_id}

        await self.hass.services.async_call(
            "cover",
            service_name,
            service_data,
            context=ctx,
            blocking=False,
        )

        self._log_action(
            f"Deschidere {entity_id} la {target_position}% — surplus suficient"
        )

    async def _stop_cover(self, entity_id: str) -> None:
        """Trimite stop_cover și înregistrează acțiunea (evită detecție manuală)."""
        ctx = Context()
        self._coordinator_actions[entity_id] = {
            "time": datetime.now(),
            "context_id": ctx.id,
            "target_position": 0,
        }
        await self.hass.services.async_call(
            "cover",
            "stop_cover",
            {"entity_id": entity_id},
            context=ctx,
            blocking=False,
        )
        self._log_action(f"Jaluzea {entity_id}: oprită (surplus insuficient)")

    def _flush_cycle_log(self) -> None:
        """Salvează buffer-ul ciclului curent în cycle_log (fără duplicate)."""
        buf = self._cycle_buf
        if not buf:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        content_lines = "\n".join(f"  {ln}" for ln in buf)
        block = f"[{ts}]\n{content_lines}"
        last_content = (
            self._cycle_log[-1].split("\n", 1)[1] if self._cycle_log else None
        )
        if content_lines != last_content:
            self._cycle_log.append(block)
        self._cycle_buf = []

    # ------------------------------------------------------------------
    # State snapshot (consumat de entitățile sensor/switch/number)
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> dict:
        cfg = self.entry.data
        rt = self._runtime()
        covers_list: list[str] = cfg.get(CONF_COVERS, [])
        cover_states: dict = rt.get(RUNTIME_COVER_STATES, {})
        auto_enabled: bool = rt.get(RUNTIME_AUTO_ENABLED, True)

        solar_raw = self._float_state(cfg[CONF_SOLAR_SENSOR])
        grid_raw = self._float_state(cfg[CONF_GRID_SENSOR])

        opts = self.entry.options
        grid_convention_override = opts.get("grid_convention_override")
        if grid_convention_override is not None:
            grid_positive_is_export = grid_convention_override == "export"
        else:
            grid_positive_is_export = cfg.get(CONF_GRID_POSITIVE_IS_EXPORT, True)

        grid_export: float | None = None
        if grid_raw is not None:
            grid_export = grid_raw if grid_positive_is_export else -grid_raw

        motor_power: float = rt.get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER)
        surplus: float | None = grid_export

        # Status per jaluzea
        cover_statuses: dict[str, str] = {}
        for eid in covers_list:
            active = rt.get(f"cover_active_{eid}", True)
            state = cover_states.get(eid, COVER_STATE_PENDING)

            if not auto_enabled:
                status = STATUS_GLOBAL_OFF
            elif not active:
                status = STATUS_DISABLED
            elif state == COVER_STATE_MANUAL:
                status = STATUS_MANUAL
            elif state == COVER_STATE_OPENING:
                status = STATUS_OPENING
            elif state == COVER_STATE_AUTO_OPENED:
                status = STATUS_AUTO_OPENED
            else:  # PENDING
                status = STATUS_WAITING_SURPLUS

            cover_statuses[eid] = status

        return {
            "solar_power": solar_raw,
            "grid_export": grid_export,
            "surplus": surplus,
            "motor_power": motor_power,
            "auto_enabled": auto_enabled,
            "cover_states": dict(cover_states),
            "cover_statuses": cover_statuses,
            "covers": covers_list,
            "action_log": list(self._action_log),
            "cycle_log": list(reversed(list(self._cycle_log))),
        }
