import argparse
import json
import logging
import os
import time

import paho.mqtt.client as mqtt
from pymodbus.client import ModbusTcpClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("mqtt-gateway")

DEVICE = "machine01"
BASE_TOPIC = f"iiot/workshop/{DEVICE}"
MODBUS_HOST = os.getenv("MODBUS_HOST", "127.0.0.1")
MODBUS_PORT = int(os.getenv("MODBUS_PORT", "5020"))
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "certs/ca.crt")
PUBLISH_INTERVAL = 2.0

FIELDS = {
    "vibration": ("vibration", 0.1, "mm/s"),
    "bearing_temperature": ("bearing_temperature", 0.1, "C"),
    "motor_current": ("motor_current", 0.01, "A"),
}


def decode_registers(registers):
    parts_count = (registers[3] << 16) | registers[4]
    states = {0: "IDLE", 1: "RUN", 2: "FAULT"}
    towers = {0: "GREEN", 1: "YELLOW", 2: "RED"}

    result = {
        "vibration": registers[0] * 0.1,
        "bearing_temperature": registers[1] * 0.1,
        "motor_current": registers[2] * 0.01,
        "parts_count": parts_count,
        "machine_state": states.get(registers[5], "UNKNOWN"),
        "signal_tower": towers.get(registers[6], "UNKNOWN"),
        "emergency_stop": bool(registers[7]),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Modbus-to-MQTT gateway")
    parser.add_argument("--once", action="store_true", help="Publish one sample")
    args = parser.parse_args()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="machine01-gateway",
        clean_session=True,
        protocol=mqtt.MQTTv311,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info("MQTT connection result: %s", reason_code)

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        log.warning("MQTT disconnected: %s", reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    if MQTT_PORT == 8884:
        client.tls_set(ca_certs=MQTT_CA_CERT)
        client.tls_insecure_set(False)

    client.will_set(
        f"{BASE_TOPIC}/status",
        payload="offline",
        qos=1,
        retain=True,
    )

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()

    modbus = ModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT, timeout=3)
    if not modbus.connect():
        client.loop_stop()
        client.disconnect()
        raise RuntimeError(f"Cannot connect to Modbus server at {MODBUS_HOST}:{MODBUS_PORT}")

    client.publish(f"{BASE_TOPIC}/status", "online", qos=1, retain=True)

    try:
        while True:
            response = modbus.read_holding_registers(address=0, count=8)
            if response.isError():
                log.error("Modbus read failed: %s", response)
            else:
                data = decode_registers(response.registers)
                timestamp = int(time.time())

                for field, (_, _, unit) in FIELDS.items():
                    payload = {
                        "value": data[field],
                        "unit": unit,
                        "ts": timestamp,
                    }
                    info = client.publish(
                        f"{BASE_TOPIC}/{field}/telemetry",
                        json.dumps(payload),
                        qos=1,
                    )
                    if info.rc != 0:
                        log.error(
                            "MQTT publish failed for %s: rc=%s",
                            field, info.rc
                        )
                    else:
                        log.debug("MQTT publish queued: %s", field)

                for field, unit in [
                    ("parts_count", "pcs"),
                    ("machine_state", "code"),
                    ("signal_tower", "code"),
                    ("emergency_stop", "bool"),
                ]:
                    payload = {
                        "value": data[field],
                        "unit": unit,
                        "ts": timestamp,
                    }
                    info = client.publish(
                        f"{BASE_TOPIC}/{field}/telemetry",
                        json.dumps(payload),
                        qos=1,
                    )
                    if info.rc != 0:
                        log.error(
                            "MQTT publish failed for %s: rc=%s",
                            field, info.rc
                        )
                    else:
                        log.debug("MQTT publish queued: %s", field)

                log.info("Published machine telemetry: %s", data)

            if args.once:
                break
            time.sleep(PUBLISH_INTERVAL)
    finally:
        modbus.close()
        client.publish(f"{BASE_TOPIC}/status", "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
