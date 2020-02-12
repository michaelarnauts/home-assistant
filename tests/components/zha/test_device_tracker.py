"""Test ZHA Device Tracker."""
from datetime import timedelta
import time

import pytest
import zigpy.zcl.clusters.general as general
import zigpy.zcl.foundation as zcl_f

from homeassistant.components.device_tracker import DOMAIN, SOURCE_TYPE_ROUTER
from homeassistant.components.zha.core.registries import (
    SMARTTHINGS_ARRIVAL_SENSOR_DEVICE_TYPE,
)
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_UNAVAILABLE
import homeassistant.util.dt as dt_util

from .common import (
    async_enable_traffic,
    find_entity_id,
    make_attribute,
    make_zcl_header,
)

from tests.common import async_fire_time_changed


@pytest.fixture
def zigpy_device_dt(zigpy_device_mock):
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            "in_clusters": [
                general.Basic.cluster_id,
                general.PowerConfiguration.cluster_id,
                general.Identify.cluster_id,
                general.PollControl.cluster_id,
                general.BinaryInput.cluster_id,
            ],
            "out_clusters": [general.Identify.cluster_id, general.Ota.cluster_id],
            "device_type": SMARTTHINGS_ARRIVAL_SENSOR_DEVICE_TYPE,
        }
    }
    return zigpy_device_mock(endpoints)


async def test_device_tracker(
    hass, zha_gateway, zha_device_joined_restored, zigpy_device_dt
):
    """Test zha device tracker platform."""

    zha_device = await zha_device_joined_restored(zigpy_device_dt)
    cluster = zigpy_device_dt.endpoints.get(1).power
    entity_id = await find_entity_id(DOMAIN, zha_device, hass)
    assert entity_id is not None

    # test that the device tracker was created and that it is unavailable
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    zigpy_device_dt.last_seen = time.time() - 120
    next_update = dt_util.utcnow() + timedelta(seconds=30)
    async_fire_time_changed(hass, next_update)
    await hass.async_block_till_done()

    # allow traffic to flow through the gateway and device
    await async_enable_traffic(hass, zha_gateway, [zha_device])

    # test that the state has changed from unavailable to not home
    assert hass.states.get(entity_id).state == STATE_NOT_HOME

    # turn state flip
    attr = make_attribute(0x0020, 23)
    hdr = make_zcl_header(zcl_f.Command.Report_Attributes)
    cluster.handle_message(hdr, [[attr]])

    attr = make_attribute(0x0021, 200)
    cluster.handle_message(hdr, [[attr]])

    zigpy_device_dt.last_seen = time.time() + 10
    next_update = dt_util.utcnow() + timedelta(seconds=30)
    async_fire_time_changed(hass, next_update)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_HOME

    entity = hass.data[DOMAIN].get_entity(entity_id)

    assert entity.is_connected is True
    assert entity.source_type == SOURCE_TYPE_ROUTER
    assert entity.battery_level == 100

    # test adding device tracker to the network and HA
    cluster.bind.reset_mock()
    cluster.configure_reporting.reset_mock()
    await zha_gateway.async_device_initialized(zigpy_device_dt)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_HOME
    assert cluster.bind.call_count == 1
    assert cluster.bind.await_count == 1
    assert cluster.configure_reporting.call_count == 2
    assert cluster.configure_reporting.await_count == 2
