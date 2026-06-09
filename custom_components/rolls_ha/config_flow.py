"""Config flow for Rolls Solar Controller.

Step 1 — solar:   senzor producție solară + senzor rețea + convenție semn
Step 2 — covers:  lista de cover entities (în ordinea de activare)
Step 3 — setări:  putere motor, timp stabilizare

Options flow: editare setări din Step 3 fără reinstalare.
Reconfigure flow: schimbare senzori + covers.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_SOLAR_SENSOR,
    CONF_GRID_SENSOR,
    CONF_GRID_POSITIVE_IS_EXPORT,
    CONF_COVERS,
    CONF_MOTOR_POWER,
    CONF_STABILIZATION_DELAY,
    DEFAULT_MOTOR_POWER,
    DEFAULT_STABILIZATION_DELAY,
)

_GRID_CONVENTION_OPTIONS = [
    SelectOptionDict(
        value="import",
        label=(
            "➕ Pozitiv = consum din rețea  |  ➖ Negativ = injecție în rețea "
            "(Shelly EM standard)"
        ),
    ),
    SelectOptionDict(
        value="export",
        label="➕ Pozitiv = injecție în rețea  |  ➖ Negativ = consum din rețea",
    ),
]


# ── Config Flow ────────────────────────────────────────────────────────────────

class RollsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Wizard de configurare în 3 pași."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 1: Senzori solar și rețea."""
        errors: dict = {}

        if user_input is not None:
            if user_input[CONF_SOLAR_SENSOR] == user_input[CONF_GRID_SENSOR]:
                errors["base"] = "same_sensor"
            else:
                self._data[CONF_SOLAR_SENSOR] = user_input[CONF_SOLAR_SENSOR]
                self._data[CONF_GRID_SENSOR] = user_input[CONF_GRID_SENSOR]
                self._data[CONF_GRID_POSITIVE_IS_EXPORT] = (
                    user_input["grid_convention"] == "export"
                )
                return await self.async_step_covers()

        schema = vol.Schema(
            {
                vol.Required(CONF_SOLAR_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_GRID_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("grid_convention", default="import"): SelectSelector(
                    SelectSelectorConfig(
                        options=_GRID_CONVENTION_OPTIONS,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_covers(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Selectare jaluzele (în ordinea de activare)."""
        errors: dict = {}

        if user_input is not None:
            covers = user_input.get(CONF_COVERS, [])
            if not covers:
                errors["base"] = "no_covers"
            else:
                self._data[CONF_COVERS] = covers
                return await self.async_step_settings()

        schema = vol.Schema(
            {
                vol.Required(CONF_COVERS): EntitySelector(
                    EntitySelectorConfig(domain="cover", multiple=True)
                ),
            }
        )
        return self.async_show_form(
            step_id="covers",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 3: Putere motor și timp de stabilizare."""
        if user_input is not None:
            covers_list: list[str] = self._data[CONF_COVERS]
            title = f"Jaluzele solare ({len(covers_list)} cover{'e' if len(covers_list) > 1 else ''})"
            return self.async_create_entry(
                title=title,
                data=self._data,
                options={
                    CONF_MOTOR_POWER: user_input[CONF_MOTOR_POWER],
                    CONF_STABILIZATION_DELAY: user_input[CONF_STABILIZATION_DELAY],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MOTOR_POWER, default=DEFAULT_MOTOR_POWER
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=10,
                        max=5000,
                        step=10,
                        unit_of_measurement="W",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_STABILIZATION_DELAY, default=DEFAULT_STABILIZATION_DELAY
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=300,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Permite schimbarea senzorilor și listei de covers fără reinstalare."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        current = entry.data if entry else {}
        errors: dict = {}

        if user_input is not None:
            if user_input[CONF_SOLAR_SENSOR] == user_input[CONF_GRID_SENSOR]:
                errors["base"] = "same_sensor"
            elif not user_input.get(CONF_COVERS):
                errors["base"] = "no_covers"
            else:
                new_data = {
                    CONF_SOLAR_SENSOR: user_input[CONF_SOLAR_SENSOR],
                    CONF_GRID_SENSOR: user_input[CONF_GRID_SENSOR],
                    CONF_GRID_POSITIVE_IS_EXPORT: (
                        user_input.get("grid_convention", "import") == "export"
                    ),
                    CONF_COVERS: user_input[CONF_COVERS],
                }
                return self.async_update_reload_and_abort(entry, data=new_data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOLAR_SENSOR,
                    default=current.get(CONF_SOLAR_SENSOR),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_GRID_SENSOR,
                    default=current.get(CONF_GRID_SENSOR),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    "grid_convention",
                    default=(
                        "export"
                        if current.get(CONF_GRID_POSITIVE_IS_EXPORT, True)
                        else "import"
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_GRID_CONVENTION_OPTIONS,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_COVERS,
                    default=current.get(CONF_COVERS, []),
                ): EntitySelector(
                    EntitySelectorConfig(domain="cover", multiple=True)
                ),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "RollsOptionsFlow":
        """Returnează options flow pentru editarea setărilor după setup."""
        return RollsOptionsFlow(config_entry)


# ── Options Flow ───────────────────────────────────────────────────────────────

class RollsOptionsFlow(config_entries.OptionsFlow):
    """Editare putere motor + timp stabilizare + convenție rețea."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Pagină unică: setări ajustabile."""
        opts = self._entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_convention = opts.get(
            "grid_convention_override",
            "export" if self._entry.data.get(CONF_GRID_POSITIVE_IS_EXPORT, True) else "import",
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MOTOR_POWER,
                    default=opts.get(CONF_MOTOR_POWER, DEFAULT_MOTOR_POWER),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=10,
                        max=5000,
                        step=10,
                        unit_of_measurement="W",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_STABILIZATION_DELAY,
                    default=opts.get(CONF_STABILIZATION_DELAY, DEFAULT_STABILIZATION_DELAY),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=300,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    "grid_convention_override",
                    default=current_convention,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_GRID_CONVENTION_OPTIONS,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
