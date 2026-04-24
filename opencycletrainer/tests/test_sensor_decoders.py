from __future__ import annotations

from datetime import datetime, timezone

import pytest

from opencycletrainer.core.sensors import SensorStreamDecoder
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
)

# Byte payload fixtures for BLE notification decoding tests.
CPS_SAMPLE_1 = bytes.fromhex("2000fa00e8030008")
CPS_SAMPLE_2 = bytes.fromhex("2000ff00ea03000c")
HRS_SAMPLE_8BIT = bytes.fromhex("0048")
HRS_SAMPLE_16BIT = bytes.fromhex("012c01")
CSC_SAMPLE_1 = bytes.fromhex("03102700000008c8000008")
CSC_SAMPLE_2 = bytes.fromhex("031a270000000cca00000c")
FTMS_SAMPLE_WITH_POWER_CADENCE_HR = bytes.fromhex("4402100eb400fa0096")
FTMS_SAMPLE_SPEED_ONLY = bytes.fromhex("0000100e")


def test_cps_decoding_produces_power_and_stateful_cadence():
    decoder = SensorStreamDecoder()

    sample_1 = decoder.decode_notification(CPS_MEASUREMENT_CHARACTERISTIC_UUID, CPS_SAMPLE_1)
    sample_2 = decoder.decode_notification(CPS_MEASUREMENT_CHARACTERISTIC_UUID, CPS_SAMPLE_2)

    assert sample_1 is not None
    assert sample_1.power_watts == 250
    assert sample_1.cadence_rpm is None
    assert sample_1.heart_rate_bpm is None
    assert sample_1.speed_mps is None

    assert sample_2 is not None
    assert sample_2.power_watts == 255
    assert sample_2.cadence_rpm == pytest.approx(120.0)


def test_hrs_decoding_supports_8bit_and_16bit_formats():
    decoder = SensorStreamDecoder()

    sample_8bit = decoder.decode_notification(HRS_MEASUREMENT_CHARACTERISTIC_UUID, HRS_SAMPLE_8BIT)
    sample_16bit = decoder.decode_notification(HRS_MEASUREMENT_CHARACTERISTIC_UUID, HRS_SAMPLE_16BIT)

    assert sample_8bit is not None
    assert sample_8bit.heart_rate_bpm == 72
    assert sample_8bit.power_watts is None
    assert sample_8bit.cadence_rpm is None
    assert sample_8bit.speed_mps is None

    assert sample_16bit is not None
    assert sample_16bit.heart_rate_bpm == 300


def test_csc_decoding_produces_speed_and_stateful_cadence():
    decoder = SensorStreamDecoder()

    sample_1 = decoder.decode_notification(CSC_MEASUREMENT_CHARACTERISTIC_UUID, CSC_SAMPLE_1)
    sample_2 = decoder.decode_notification(CSC_MEASUREMENT_CHARACTERISTIC_UUID, CSC_SAMPLE_2)

    assert sample_1 is not None
    assert sample_1.speed_mps is None
    assert sample_1.cadence_rpm is None

    assert sample_2 is not None
    assert sample_2.speed_mps == pytest.approx(21.05, rel=1e-3)
    assert sample_2.cadence_rpm == pytest.approx(120.0)


def test_ftms_decoding_produces_power_cadence_hr_and_speed():
    decoder = SensorStreamDecoder()

    sample = decoder.decode_notification(
        FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
        FTMS_SAMPLE_WITH_POWER_CADENCE_HR,
    )

    assert sample is not None
    assert sample.power_watts == 250
    assert sample.cadence_rpm == pytest.approx(90.0)
    assert sample.heart_rate_bpm == 150
    assert sample.speed_mps == pytest.approx(10.0)


def test_missing_fields_decode_as_none_when_not_present():
    decoder = SensorStreamDecoder()

    sample = decoder.decode_notification(
        FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
        FTMS_SAMPLE_SPEED_ONLY,
    )

    assert sample is not None
    assert sample.speed_mps == pytest.approx(10.0)
    assert sample.power_watts is None
    assert sample.cadence_rpm is None
    assert sample.heart_rate_bpm is None


def test_sensor_sample_is_timestamped_on_receipt():
    decoder = SensorStreamDecoder()
    explicit_timestamp = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)

    sample = decoder.decode_notification(
        HRS_MEASUREMENT_CHARACTERISTIC_UUID,
        HRS_SAMPLE_8BIT,
        received_at_utc=explicit_timestamp,
    )

    assert sample is not None
    assert sample.timestamp_utc == explicit_timestamp
    assert sample.source_characteristic_uuid == HRS_MEASUREMENT_CHARACTERISTIC_UUID


def test_unknown_characteristic_returns_none():
    decoder = SensorStreamDecoder()
    sample = decoder.decode_notification("0000ffff-0000-1000-8000-00805f9b34fb", b"\x00")
    assert sample is None


# Crank counter rollover: previous=65534, new=2 (4 actual revolutions), time delta=1 second.
# After fix: (2 - 65534) % 65536 = 4 → 240 RPM (valid, within cap).
_CSC_CRANK_ROLLOVER_PACKET_1 = bytes.fromhex("02feff0000")
_CSC_CRANK_ROLLOVER_PACKET_2 = bytes.fromhex("0202000004")

# Crank delta of 6 revolutions in 1 second → 360 RPM, which exceeds the sanity cap.
_CSC_CADENCE_OUT_OF_RANGE_PACKET_1 = bytes.fromhex("0264000000")
_CSC_CADENCE_OUT_OF_RANGE_PACKET_2 = bytes.fromhex("026a000004")

# CPS: same 360 RPM scenario via power meter crank data.
_CPS_CADENCE_OUT_OF_RANGE_PACKET_1 = bytes.fromhex("2000c80064000000")
_CPS_CADENCE_OUT_OF_RANGE_PACKET_2 = bytes.fromhex("2000c8006a000004")

_CPS_WITH_PEDAL_BALANCE_AND_TORQUE_1 = bytes.fromhex("2500fa00403412e8030008")
_CPS_WITH_PEDAL_BALANCE_AND_TORQUE_2 = bytes.fromhex("2500ff00403812e903000a")

_CPS_WITH_WHEEL_AND_CRANK_1 = bytes.fromhex("3000fa00640000000004e8030008")
_CPS_WITH_WHEEL_AND_CRANK_2 = bytes.fromhex("3000ff00650000000006e903000a")

# FTMS: cadence_raw=65535 → 32767.5 RPM, far beyond any sane value.
_FTMS_CADENCE_OUT_OF_RANGE = bytes.fromhex("04000000ffff")


def test_csc_crank_counter_rollover_produces_correct_cadence():
    decoder = SensorStreamDecoder()

    sample_1 = decoder.decode_notification(CSC_MEASUREMENT_CHARACTERISTIC_UUID, _CSC_CRANK_ROLLOVER_PACKET_1)
    sample_2 = decoder.decode_notification(CSC_MEASUREMENT_CHARACTERISTIC_UUID, _CSC_CRANK_ROLLOVER_PACKET_2)

    assert sample_1 is not None
    assert sample_1.cadence_rpm is None

    assert sample_2 is not None
    assert sample_2.cadence_rpm == pytest.approx(240.0)


def test_csc_cadence_out_of_range_is_rejected():
    decoder = SensorStreamDecoder()

    decoder.decode_notification(CSC_MEASUREMENT_CHARACTERISTIC_UUID, _CSC_CADENCE_OUT_OF_RANGE_PACKET_1)
    sample_2 = decoder.decode_notification(CSC_MEASUREMENT_CHARACTERISTIC_UUID, _CSC_CADENCE_OUT_OF_RANGE_PACKET_2)

    assert sample_2 is not None
    assert sample_2.cadence_rpm is None


def test_cps_cadence_out_of_range_is_rejected():
    decoder = SensorStreamDecoder()

    decoder.decode_notification(CPS_MEASUREMENT_CHARACTERISTIC_UUID, _CPS_CADENCE_OUT_OF_RANGE_PACKET_1)
    sample_2 = decoder.decode_notification(CPS_MEASUREMENT_CHARACTERISTIC_UUID, _CPS_CADENCE_OUT_OF_RANGE_PACKET_2)

    assert sample_2 is not None
    assert sample_2.cadence_rpm is None


def test_cps_cadence_skips_optional_fields_before_crank_data():
    decoder = SensorStreamDecoder()

    sample_1 = decoder.decode_notification(
        CPS_MEASUREMENT_CHARACTERISTIC_UUID,
        _CPS_WITH_PEDAL_BALANCE_AND_TORQUE_1,
    )
    sample_2 = decoder.decode_notification(
        CPS_MEASUREMENT_CHARACTERISTIC_UUID,
        _CPS_WITH_PEDAL_BALANCE_AND_TORQUE_2,
    )

    assert sample_1 is not None
    assert sample_1.cadence_rpm is None

    assert sample_2 is not None
    assert sample_2.cadence_rpm == pytest.approx(120.0)


def test_cps_cadence_skips_wheel_data_before_crank_data():
    decoder = SensorStreamDecoder()

    sample_1 = decoder.decode_notification(
        CPS_MEASUREMENT_CHARACTERISTIC_UUID,
        _CPS_WITH_WHEEL_AND_CRANK_1,
    )
    sample_2 = decoder.decode_notification(
        CPS_MEASUREMENT_CHARACTERISTIC_UUID,
        _CPS_WITH_WHEEL_AND_CRANK_2,
    )

    assert sample_1 is not None
    assert sample_1.cadence_rpm is None

    assert sample_2 is not None
    assert sample_2.cadence_rpm == pytest.approx(120.0)


def test_ftms_cadence_out_of_range_is_rejected():
    decoder = SensorStreamDecoder()

    sample = decoder.decode_notification(FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID, _FTMS_CADENCE_OUT_OF_RANGE)

    assert sample is not None
    assert sample.cadence_rpm is None
