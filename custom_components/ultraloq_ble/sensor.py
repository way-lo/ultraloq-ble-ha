"""Sensor platform for Ultraloq integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud import CLOUD_BATTERY, UltraloqCloudBatteryCoordinator
from .const import DOMAIN, UTEC_LOCKDATA
from .entity import UltraloqEntity
from .utecio.ble.lock import UtecBleLock
from .utecio.enums import DeviceBatteryLevel

AUTOLOCK_MODES = {0: "Door Sensor", 1: "Immediate"}


@dataclass(frozen=True, kw_only=True)
class UltraloqSensorDescription(SensorEntityDescription):
    """Description for an Ultraloq sensor."""

    value_fn: Callable[[UtecBleLock], object]


def _battery_level(lock: UtecBleLock) -> str | None:
    """Return a known battery level without rejecting new firmware values."""

    if lock.battery == DeviceBatteryLevel.NOTSET.value:
        return None
    try:
        return DeviceBatteryLevel(lock.battery).name
    except ValueError:
        return None


SENSORS: tuple[UltraloqSensorDescription, ...] = (
    UltraloqSensorDescription(
        key="battery_level",
        device_class=SensorDeviceClass.ENUM,
        options=[level.name for level in DeviceBatteryLevel if level.name != "NOTSET"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery-bluetooth-variant",
        value_fn=_battery_level,
    ),
    UltraloqSensorDescription(
        key="autolock_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        icon="mdi:timer-lock-outline",
        value_fn=lambda lock: lock.autolock_time if lock.autolock_time >= 0 else None,
    ),
    UltraloqSensorDescription(
        key="autolock_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(AUTOLOCK_MODES.values()),
        icon="mdi:timer-lock-outline",
        value_fn=lambda lock: AUTOLOCK_MODES.get(lock.autolock_mode),
    ),
    UltraloqSensorDescription(
        key="last_successful_communication",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda lock: lock.last_successful_communication,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Ultraloq sensors for a config entry."""

    locks: list[UtecBleLock] = hass.data[DOMAIN][entry.entry_id][UTEC_LOCKDATA]
    cloud_battery: UltraloqCloudBatteryCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][CLOUD_BATTERY]
    entities: list[SensorEntity] = []

    for lock in locks:
        for description in SENSORS:
            if (
                description.key.startswith("autolock_")
                and not lock.capabilities.autolock
            ):
                continue
            entities.append(UltraloqSensor(lock, description))
        entities.append(UltraloqCloudBatterySensor(cloud_battery, lock))

    async_add_entities(entities)


class UltraloqSensor(UltraloqEntity, SensorEntity):
    """Representation of an Ultraloq sensor."""

    entity_description: UltraloqSensorDescription

    def __init__(
        self, lock: UtecBleLock, description: UltraloqSensorDescription
    ) -> None:
        """Initialize the sensor."""

        super().__init__(lock, description.key)
        self.entity_description = description
        self._attr_name = self.entity_description.key.replace("_", " ").title()

    @property
    def native_value(self):
        """Return the sensor value."""

        return self.entity_description.value_fn(self.lock)

    @property
    def available(self) -> bool:
        """Keep the last communication visible while the lock is offline."""

        return (
            self.entity_description.key == "last_successful_communication"
            or super().available
        )


class UltraloqCloudBatterySensor(
    CoordinatorEntity[UltraloqCloudBatteryCoordinator], UltraloqEntity, SensorEntity
):
    """Battery percentage from the U-tec cloud (Bluetooth only gives a level)."""

    _attr_name = "Cloud battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _listen_for_updates = False  # updates come from the coordinator, not BLE

    def __init__(
        self, coordinator: UltraloqCloudBatteryCoordinator, lock: UtecBleLock
    ) -> None:
        """Initialize the sensor."""

        CoordinatorEntity.__init__(self, coordinator)
        UltraloqEntity.__init__(self, lock, "cloud_battery")
        self._key = str(lock.mac_uuid).lower()

    @property
    def native_value(self) -> int | None:
        """Return the last known percentage; None (unknown) when the cloud has none."""

        return (self.coordinator.data or {}).get(self._key)

    @property
    def available(self) -> bool:
        """Independent of Bluetooth; keeps the last value if a cloud poll fails."""

        return self._key in (self.coordinator.data or {})
