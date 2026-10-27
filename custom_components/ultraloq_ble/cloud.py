"""Battery percentage polled from the U-tec cloud.

Bluetooth only reports a 4-step battery level. The U-tec cloud device list
(the same one used at setup) carries ``params.battery_percent``, so this polls
it on a slow schedule. Lock control and state stay on Bluetooth; a cloud
failure only leaves this sensor showing its last known value.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import LOGGER
from .util import async_fetch_api_devices

CLOUD_BATTERY = "cloud_battery"
CLOUD_BATTERY_INTERVAL = timedelta(hours=6)


def battery_percents(api_devices: Any) -> dict[str, int | None]:
    """Map each device's BLE address to its cloud battery percent.

    The cloud uses placeholders when it has no reading (-99, and 0 seen on a
    lock whose level byte says High), so only 1-100 counts as a real value.
    """

    records = api_devices.values() if isinstance(api_devices, dict) else api_devices
    result: dict[str, int | None] = {}
    for record in records or []:
        if not isinstance(record, dict) or not record.get("uuid"):
            continue
        params = record.get("params")
        raw = params.get("battery_percent") if isinstance(params, dict) else None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = None
        result[str(record["uuid"]).lower()] = value if value and 1 <= value <= 100 else None
    return result


class UltraloqCloudBatteryCoordinator(DataUpdateCoordinator[dict[str, int | None]]):
    """Poll the U-tec cloud for battery percentages."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, cached_devices: Any
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Ultraloq cloud battery",
            update_interval=CLOUD_BATTERY_INTERVAL,
        )
        self._entry = entry
        # Start from the device list saved at setup so startup needs no network.
        self.data = battery_percents(cached_devices)

    async def _async_update_data(self) -> dict[str, int | None]:
        try:
            api_devices = await async_fetch_api_devices(
                self.hass,
                self._entry.data[CONF_EMAIL],
                self._entry.data[CONF_PASSWORD],
            )
        except Exception as err:  # noqa: BLE001 - any cloud failure is non-fatal
            raise UpdateFailed(f"U-tec cloud battery update failed: {err}") from err
        return battery_percents(api_devices)
