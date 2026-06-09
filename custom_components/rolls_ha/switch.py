"""Switch entities for Rolls Solar Controller.

- RollsAutoSwitch: control automat global (on/off pentru întreaga integrare)
- RollsCoverActiveSwitch: activare/dezactivare per jaluzea
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_COVERS,
    RUNTIME_AUTO_ENABLED,
    RUNTIME_COVER_STATES,
    COVER_STATE_PENDING,
)
from .coordinator import RollsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Creează entitățile switch pentru această config entry."""
    coordinator: RollsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    covers_list: list[str] = entry.data.get(CONF_COVERS, [])

    entities: list[SwitchEntity] = [RollsAutoSwitch(coordinator, entry)]

    for eid in covers_list:
        name = _cover_name(eid)
        entities.append(RollsCoverActiveSwitch(coordinator, entry, eid, name))

    async_add_entities(entities)


def _cover_name(entity_id: str) -> str:
    """Derivă un nume prietenos din entity_id."""
    return entity_id.split(".")[-1].replace("_", " ").title()


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Rolls Solar Controller",
        manufacturer="vculea",
        model="Rolls Solar Controller",
        entry_type="service",
    )


# ── Switch global ────────────────────────────────────────────────────────────

class RollsAutoSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Activează / dezactivează controlul solar automat pentru toate jaluzelele."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:solar-power-variant"
    _attr_translation_key = "control_automat"

    def __init__(self, coordinator: RollsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_control_automat"
        self._attr_device_info = _device_info(entry)
        self._is_on = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._is_on = last.state == STATE_ON
        self._runtime()[RUNTIME_AUTO_ENABLED] = self._is_on

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        self._is_on = True
        self._runtime()[RUNTIME_AUTO_ENABLED] = True
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        self._is_on = False
        self._runtime()[RUNTIME_AUTO_ENABLED] = False
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    def _runtime(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]


# ── Switch per jaluzea ───────────────────────────────────────────────────────

class RollsCoverActiveSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Include / exclude o jaluzea din automatizarea solară."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:window-shutter-settings"
    _attr_translation_key = "activ_jaluzea"

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
        self._attr_unique_id = f"{entry.entry_id}_activ_{slug}"
        self._attr_name = f"Activ — {cover_name}"
        self._attr_device_info = _device_info(entry)
        self._is_on = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._is_on = last.state == STATE_ON
        # Sincronizează valoarea restaurată în runtime store
        self._runtime()[f"cover_active_{self._cover_entity_id}"] = self._is_on

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        self._is_on = True
        rt = self._runtime()
        rt[f"cover_active_{self._cover_entity_id}"] = True
        # Dacă jaluzea era dezactivată, o readuce la PENDING
        cover_states: dict = rt.get(RUNTIME_COVER_STATES, {})
        if self._cover_entity_id not in cover_states or not any(
            v == self._cover_entity_id
            for v in [self._cover_entity_id]
        ):
            cover_states.setdefault(self._cover_entity_id, COVER_STATE_PENDING)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        self._is_on = False
        self._runtime()[f"cover_active_{self._cover_entity_id}"] = False
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    def _runtime(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]
