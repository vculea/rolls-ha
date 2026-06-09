"""Rolls Solar Controller — Home Assistant custom integration.

Deschide automat jaluzele (cover entities) când există surplus de producție
solară, în ordinea configurată, câte una pe rând.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_COVERS,
    CONF_SOLAR_SENSOR,
    CONF_GRID_SENSOR,
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

    # Generează dashboard-ul cu entity ID-urile reale după ce platformele sunt gata
    hass.async_create_task(_generate_dashboard(hass, entry))

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
    # Regenerează dashboard-ul după orice schimbare de opțiuni/configurare
    hass.async_create_task(_generate_dashboard(hass, entry))


# ── Dashboard auto-generator ────────────────────────────────────────────────

def _cover_friendly_name(entity_id: str) -> str:
    return entity_id.split(".")[-1].replace("_", " ").title()


def _cover_slug(entity_id: str) -> str:
    return entity_id.replace(".", "_").replace("-", "_")


async def _generate_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Generează un fișier YAML de dashboard cu entity ID-urile reale din registry.

    Fișierul este salvat la: <config>/www/rolls_ha_dashboard.yaml
    Poate fi importat în HA din: Settings → Dashboards → Add dashboard → From YAML.
    Este regenerat automat la fiecare pornire HA și la modificarea configurației.
    """
    # Import local — evită erori în medii de test fără HA instalat
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)
    entry_id = entry.entry_id
    covers_list: list[str] = entry.data.get(CONF_COVERS, [])
    solar_sensor: str = entry.data.get(CONF_SOLAR_SENSOR, "sensor.solar_power")
    grid_sensor: str = entry.data.get(CONF_GRID_SENSOR, "sensor.grid_power")

    def find(domain: str, unique_suffix: str) -> str:
        """Caută entity_id-ul real din registry după unique_id."""
        eid = ent_reg.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{unique_suffix}")
        if eid:
            return eid
        # Fallback cu suggested_object_id (instalări noi)
        slug = unique_suffix
        return f"{domain}.rolls_{slug}"

    # ── Entități globale ────────────────────────────────────────────────────
    sw_auto = find("switch", "control_automat")
    sn_surplus = find("sensor", "surplus_solar")
    nb_motor = find("number", "putere_motor")
    nb_delay = find("number", "timp_stabilizare")

    # ── Secțiuni per jaluzea ────────────────────────────────────────────────
    cover_blocks: list[str] = []
    for cover_eid in covers_list:
        s = _cover_slug(cover_eid)
        name = _cover_friendly_name(cover_eid)
        sw_activ = find("switch", f"activ_{s}")
        sn_status = find("sensor", f"status_{s}")
        nb_pozitie = find("number", f"pozitie_{s}")

        cover_blocks.append(
            f"\n"
            f"  # ── {name} {'─' * max(1, 60 - len(name))}\n"
            f"  - type: vertical-stack\n"
            f"    cards:\n"
            f"      - type: markdown\n"
            f"        content: \"### {name}\"\n"
            f"\n"
            f"      - type: grid\n"
            f"        columns: 3\n"
            f"        square: false\n"
            f"        cards:\n"
            f"          - type: tile\n"
            f"            entity: {cover_eid}\n"
            f"            name: Jaluzea\n"
            f"            icon: mdi:window-shutter\n"
            f"          - type: tile\n"
            f"            entity: {sn_status}\n"
            f"            name: Status\n"
            f"            icon: mdi:robot-outline\n"
            f"          - type: gauge\n"
            f"            entity: {cover_eid}\n"
            f"            name: \"Poziție\"\n"
            f"            attribute: current_position\n"
            f"            min: 0\n"
            f"            max: 100\n"
            f"            needle: false\n"
            f"            severity:\n"
            f"              green: 60\n"
            f"              yellow: 20\n"
            f"              red: 0\n"
            f"\n"
            f"      - type: entities\n"
            f"        show_header_toggle: false\n"
            f"        state_color: true\n"
            f"        entities:\n"
            f"          - entity: {sw_activ}\n"
            f"            name: \"Include în automatizare\"\n"
            f"          - entity: {nb_pozitie}\n"
            f"            name: \"Deschidere țintă (%)\"\n"
            f"          - type: attribute\n"
            f"            entity: {sn_status}\n"
            f"            attribute: stare_automatizare\n"
            f"            name: \"Stare automatizare\"\n"
            f"            icon: mdi:state-machine\n"
        )

    covers_yaml = "".join(cover_blocks)

    # ── Card overview rapid (sus / stop / jos pentru toate jaluzelele) ──────
    overview_entities = "\n".join(
        f"      - entity: {c}\n        name: \"{_cover_friendly_name(c)}\""
        for c in covers_list
    )
    overview_card = (
        f"  # ── Jaluzele — control rapid (sus / stop / jos) "
        f"{'─' * 29}\n"
        f"  - type: entities\n"
        f"    title: \"Jaluzele\"\n"
        f"    show_header_toggle: false\n"
        f"    entities:\n"
        f"{overview_entities}\n"
        f"\n"
    )

    # ── Template Jinja2 pentru log (scăpăm {} cu dublare) ──────────────────
    log_entity = sn_surplus
    log_card = (
        "  - type: markdown\n"
        "    title: Activitate recentă\n"
        "    content: >-\n"
        f"      {{% set log = state_attr('{log_entity}', 'action_log') | default([]) %}}\n"
        "      {% if log %}\n"
        "      {% for line in log %}\n"
        "      `{{ line }}`\n\n"
        "      {% endfor %}\n"
        "      {% else %}\n"
        "      _Nicio activitate înregistrată_\n"
        "      {% endif %}\n"
    )

    # ── Asamblare YAML complet ───────────────────────────────────────────────
    content = (
        f"# Auto-generat de Rolls Solar Controller\n"
        f"# Regenerat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Importă în HA: Settings → Dashboards → Add → From YAML\n"
        f"\n"
        f"title: Jaluzele Solare\n"
        f"path: jaluzele-solare\n"
        f"icon: mdi:window-shutter-open\n"
        f"badges: []\n"
        f"cards:\n"
        f"\n"
        f"  - type: markdown\n"
        f"    content: |\n"
        f"      ## 🪟 Rolls Solar Controller\n"
        f"      Jaluzele deschise automat din surplus fotovoltaic.\n"
        f"\n"
        f"  # ── Producție · Rețea · Surplus ─────────────────────────────────────\n"
        f"  - type: grid\n"
        f"    columns: 3\n"
        f"    square: false\n"
        f"    cards:\n"
        f"      - type: tile\n"
        f"        entity: {solar_sensor}\n"
        f"        name: \"Producție\"\n"
        f"        icon: mdi:solar-power\n"
        f"        color: amber\n"
        f"      - type: tile\n"
        f"        entity: {grid_sensor}\n"
        f"        name: \"Rețea\"\n"
        f"        icon: mdi:transmission-tower\n"
        f"        color: blue\n"
        f"      - type: tile\n"
        f"        entity: {sn_surplus}\n"
        f"        name: \"Surplus\"\n"
        f"        icon: mdi:solar-power-variant\n"
        f"        color: green\n"
        f"\n"
        f"  # ── Control automat + jaluzele deschise azi ──────────────────────────\n"
        f"  - type: grid\n"
        f"    columns: 2\n"
        f"    square: false\n"
        f"    cards:\n"
        f"      - type: tile\n"
        f"        entity: {sw_auto}\n"
        f"        name: \"Control automat\"\n"
        f"        icon: mdi:robot-outline\n"
        f"        color: green\n"
        f"      - type: tile\n"
        f"        entity: {sn_surplus}\n"
        f"        name: \"Deschise azi\"\n"
        f"        icon: mdi:window-shutter-open\n"
        f"        attribute: jaluzele_deschise\n"
        f"\n"
        f"  # ── Setări globale ───────────────────────────────────────────────────\n"
        f"  - type: entities\n"
        f"    title: \"Setări automatizare\"\n"
        f"    show_header_toggle: false\n"
        f"    state_color: true\n"
        f"    entities:\n"
        f"      - entity: {nb_motor}\n"
        f"        name: \"Prag motor (W)\"\n"
        f"        icon: mdi:flash\n"
        f"      - entity: {nb_delay}\n"
        f"        name: \"Stabilizare (s)\"\n"
        f"        icon: mdi:timer-outline\n"
        f"\n"
        f"{overview_card}"
        f"  # ════════════════════════════════════════════════════════════════════\n"
        f"  # JALUZELE ({len(covers_list)} configurate) — fiecare grupat în vertical-stack\n"
        f"  # ════════════════════════════════════════════════════════════════════\n"
        f"{covers_yaml}\n"
        f"  # ── Activitate recentă ───────────────────────────────────────────────\n"
        f"{log_card}"
        f"\n"
        f"  # ── Grafic surplus + producție (2h) ──────────────────────────────────\n"
        f"  - type: history-graph\n"
        f"    title: \"Surplus solar (2h)\"\n"
        f"    hours_to_show: 2\n"
        f"    entities:\n"
        f"      - entity: {sn_surplus}\n"
        f"        name: Surplus (W)\n"
        f"      - entity: {solar_sensor}\n"
        f"        name: \"Producție (W)\"\n"
    )

    www_dir = hass.config.path("www")

    def _write() -> None:
        os.makedirs(www_dir, exist_ok=True)
        path = os.path.join(www_dir, "rolls_ha_dashboard.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        _LOGGER.info(
            "Rolls HA: dashboard generat la %s (%d jaluzele)",
            path,
            len(covers_list),
        )

    await hass.async_add_executor_job(_write)
