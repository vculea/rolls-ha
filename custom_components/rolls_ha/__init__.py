"""Rolls Solar Controller — Home Assistant custom integration.

Deschide automat jaluzele (cover entities) când există surplus de producție
solară, în ordinea configurată, câte una pe rând.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_COVERS,
    CONF_MOTOR_POWER,
    CONF_STABILIZATION_DELAY,
    RUNTIME_AUTO_ENABLED,
    RUNTIME_COVER_STATES,
    RUNTIME_SURPLUS_STABLE_SINCE,
    COVER_STATE_PENDING,
    DEFAULT_MOTOR_POWER,
    DEFAULT_STABILIZATION_DELAY,
    DEFAULT_OPEN_POSITION,
)
from .coordinator import RollsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rolls Solar Controller from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    covers_list: list[str] = entry.data.get(CONF_COVERS, [])

    # Runtime store — mutable in-memory dict shared by coordinator + entities
    rt: dict = {
        CONF_MOTOR_POWER: entry.options.get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER),
        CONF_STABILIZATION_DELAY: entry.options.get(
            CONF_STABILIZATION_DELAY, DEFAULT_STABILIZATION_DELAY
        ),
        RUNTIME_AUTO_ENABLED: True,
        RUNTIME_COVER_STATES: {eid: COVER_STATE_PENDING for eid in covers_list},
        RUNTIME_SURPLUS_STABLE_SINCE: None,
    }

    # Per-cover defaults (overridden by number/switch entities after restore)
    for eid in covers_list:
        rt[f"open_position_{eid}"] = DEFAULT_OPEN_POSITION
        rt[f"cover_active_{eid}"] = True

    hass.data[DOMAIN][entry.entry_id] = rt

    coordinator = RollsCoordinator(hass, entry)
    rt["coordinator"] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: RollsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.async_cancel_subscriptions()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — sync changed values into the runtime store."""
    store = hass.data[DOMAIN][entry.entry_id]
    store[CONF_MOTOR_POWER] = entry.options.get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER)
    store[CONF_STABILIZATION_DELAY] = entry.options.get(
        CONF_STABILIZATION_DELAY, DEFAULT_STABILIZATION_DELAY
    )
