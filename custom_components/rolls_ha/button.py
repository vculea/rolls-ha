"""Button entities for Rolls Solar Controller.

- RollsResetButton: resetează stările de automatizare ale tuturor jaluzelelor la PENDING.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RollsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Creează entitățile button pentru această config entry."""
    coordinator: RollsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([RollsResetButton(coordinator, entry)])


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Rolls Solar Controller",
        manufacturer="vculea",
        model="Rolls Solar Controller",
        entry_type="service",
    )


class RollsResetButton(CoordinatorEntity, ButtonEntity):
    """Resetează stările de automatizare ale tuturor jaluzelelor la PENDING."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:restart"
    _attr_translation_key = "reset_stare"

    def __init__(self, coordinator: RollsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_stare"
        self._attr_suggested_object_id = "rolls_reset_stare"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        """Resetează toate stările la PENDING."""
        self.coordinator.reset_states()
