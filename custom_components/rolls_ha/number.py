"""Number entities for Rolls Solar Controller.

- RollsMotorPowerNumber: puterea motorului (prag surplus necesar, W)
- RollsStabilizationDelayNumber: timp de stabilizare surplus (s)
- RollsCoverPositionNumber: procentul de deschidere per jaluzea (%)
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_COVERS,
    CONF_MOTOR_POWER,
    CONF_STABILIZATION_DELAY,
    DEFAULT_MOTOR_POWER,
    DEFAULT_STABILIZATION_DELAY,
    DEFAULT_OPEN_POSITION,
)
from .coordinator import RollsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Creează entitățile number pentru această config entry."""
    coordinator: RollsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    covers_list: list[str] = entry.data.get(CONF_COVERS, [])

    entities: list[NumberEntity] = [
        RollsMotorPowerNumber(coordinator, entry),
        RollsStabilizationDelayNumber(coordinator, entry),
    ]

    for eid in covers_list:
        name = _cover_name(eid)
        entities.append(RollsCoverPositionNumber(coordinator, entry, eid, name))

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


# ── Motor power ──────────────────────────────────────────────────────────────

class RollsMotorPowerNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    """Pragul de surplus necesar pentru a deschide o jaluzea (W)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:flash"
    _attr_native_min_value = 10.0
    _attr_native_max_value = 5000.0
    _attr_native_step = 10.0
    _attr_native_unit_of_measurement = "W"
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "putere_motor"

    def __init__(self, coordinator: RollsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_putere_motor"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = DEFAULT_MOTOR_POWER

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            try:
                value = float(last.state)
                self._attr_native_value = value
                self._runtime()[CONF_MOTOR_POWER] = value
                return
            except (ValueError, TypeError):
                pass
        # Fallback la valoarea din options/runtime
        value = self._runtime().get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER)
        self._attr_native_value = value

    @property
    def native_value(self) -> float:
        return self._runtime().get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._runtime()[CONF_MOTOR_POWER] = value
        self.async_write_ha_state()

    def _runtime(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]


# ── Stabilization delay ──────────────────────────────────────────────────────

class RollsStabilizationDelayNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    """Cât timp (secunde) trebuie să fie stabil surplusul înainte de acțiune."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 300.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "timp_stabilizare"

    def __init__(self, coordinator: RollsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_timp_stabilizare"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = float(DEFAULT_STABILIZATION_DELAY)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            try:
                value = float(last.state)
                self._attr_native_value = value
                self._runtime()[CONF_STABILIZATION_DELAY] = int(value)
                return
            except (ValueError, TypeError):
                pass
        value = self._runtime().get(CONF_STABILIZATION_DELAY, DEFAULT_STABILIZATION_DELAY)
        self._attr_native_value = float(value)

    @property
    def native_value(self) -> float:
        return float(self._runtime().get(CONF_STABILIZATION_DELAY, DEFAULT_STABILIZATION_DELAY))

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._runtime()[CONF_STABILIZATION_DELAY] = int(value)
        self.async_write_ha_state()

    def _runtime(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]


# ── Cover open position ──────────────────────────────────────────────────────

class RollsCoverPositionNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    """La ce procent se deschide această jaluzea (0–100%)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:window-shutter-open"
    _attr_native_min_value = 10.0
    _attr_native_max_value = 100.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "pozitie_deschidere"

    def __init__(
        self,
        coordinator: RollsCoordinator,
        entry: ConfigEntry,
        cover_entity_id: str,
        cover_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._cover_entity_id = cover_entity_id
        slug = cover_entity_id.replace(".", "_").replace("-", "_")
        self._attr_unique_id = f"{entry.entry_id}_pozitie_{slug}"
        self._attr_name = f"Poziție deschidere — {cover_name}"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = float(DEFAULT_OPEN_POSITION)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            try:
                value = float(last.state)
                self._attr_native_value = value
                self._runtime()[f"open_position_{self._cover_entity_id}"] = int(value)
                return
            except (ValueError, TypeError):
                pass
        # Setează valoarea implicită în runtime
        self._runtime()[f"open_position_{self._cover_entity_id}"] = DEFAULT_OPEN_POSITION

    @property
    def native_value(self) -> float:
        return float(
            self._runtime().get(
                f"open_position_{self._cover_entity_id}", DEFAULT_OPEN_POSITION
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._runtime()[f"open_position_{self._cover_entity_id}"] = int(value)
        self.async_write_ha_state()

    def _runtime(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]
