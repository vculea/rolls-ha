"""Sensor entities for Rolls Solar Controller.

- RollsSurplusSensor: surplusul solar calculat (W)
- RollsCoverStatusSensor: statusul automatizării per jaluzea (text)
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_COVERS, COVER_STATE_AUTO_OPENED, COVER_STATE_OPENING
from .coordinator import RollsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Creează entitățile sensor pentru această config entry."""
    coordinator: RollsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    covers_list: list[str] = entry.data.get(CONF_COVERS, [])

    entities: list[SensorEntity] = [RollsSurplusSensor(coordinator, entry)]

    for eid in covers_list:
        name = _cover_name(eid)
        entities.append(RollsCoverStatusSensor(coordinator, entry, eid, name))

    async_add_entities(entities)


def _cover_name(entity_id: str) -> str:
    return entity_id.split(".")[-1].replace("_", " ").title()


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Rolls Solar Controller",
        manufacturer="vculea",
        model="Rolls Solar Controller",
        entry_type="service",
    )


# ── Surplus solar ─────────────────────────────────────────────────────────────

class RollsSurplusSensor(CoordinatorEntity, SensorEntity):
    """Surplus solar disponibil (export rețea, W). Pozitiv = injectăm în rețea."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:solar-power"
    _attr_translation_key = "surplus_solar"

    def __init__(self, coordinator: RollsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_surplus_solar"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("surplus")

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        data = self.coordinator.data
        cover_states: dict = data.get("cover_states", {})
        covers_list: list[str] = data.get("covers", [])

        deschise = [
            eid for eid in covers_list
            if cover_states.get(eid) in (COVER_STATE_AUTO_OPENED, COVER_STATE_OPENING)
        ]
        in_asteptare = [
            eid for eid in covers_list
            if cover_states.get(eid) not in (
                COVER_STATE_AUTO_OPENED, COVER_STATE_OPENING
            )
        ]

        return {
            "solar_power_w": data.get("solar_power"),
            "grid_export_w": data.get("grid_export"),
            "motor_power_w": data.get("motor_power"),
            "jaluzele_deschise": len(deschise),
            "jaluzele_deschise_lista": deschise,
            "jaluzele_in_asteptare": len(in_asteptare),
            "action_log": data.get("action_log", []),
            "cycle_log": data.get("cycle_log", []),
        }


# ── Status per jaluzea ────────────────────────────────────────────────────────

class RollsCoverStatusSensor(CoordinatorEntity, SensorEntity):
    """Status automatizare pentru o jaluzea specifică."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:window-shutter"
    _attr_translation_key = "status_jaluzea"

    def __init__(
        self,
        coordinator: RollsCoordinator,
        entry: ConfigEntry,
        cover_entity_id: str,
        cover_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._cover_entity_id = cover_entity_id
        slug = cover_entity_id.replace(".", "_").replace("-", "_")
        self._attr_unique_id = f"{entry.entry_id}_status_{slug}"
        self._attr_name = f"Status — {cover_name}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("cover_statuses", {}).get(
            self._cover_entity_id
        )

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {}

        # ── Starea live din dispozitivul cover (ex. Shelly Cover) ─────────
        cover_state = self.hass.states.get(self._cover_entity_id)
        if cover_state is not None:
            pos = cover_state.attributes.get("current_position")
            attrs["pozitie"] = pos  # 0–100 sau None dacă dispozitivul nu raportează
            attrs["stare_cover"] = cover_state.state  # open/closed/opening/closing/stopped
            attrs["este_deschisa"] = cover_state.state in ("open", "opening") or (
                pos is not None and pos > 0
            )
            # Atribute suplimentare expuse de Shelly Cover (dacă există)
            for extra_key in ("current_tilt_position", "stopped", "calibrated"):
                val = cover_state.attributes.get(extra_key)
                if val is not None:
                    attrs[extra_key] = val
        else:
            attrs["pozitie"] = None
            attrs["stare_cover"] = None
            attrs["este_deschisa"] = None

        # ── Starea internă a automatizării ────────────────────────────────
        if self.coordinator.data is not None:
            cover_states = self.coordinator.data.get("cover_states", {})
            attrs["stare_automatizare"] = cover_states.get(self._cover_entity_id)

        attrs["cover_entity_id"] = self._cover_entity_id
        return attrs
