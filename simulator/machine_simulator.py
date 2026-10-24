import argparse
import asyncio
import logging
import math
import random
import time

from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("machine-simulator")

HOST = "0.0.0.0"
PORT = 5020
UPDATE_SECONDS = 1.0

STATE_CODES = {"IDLE": 0, "RUN": 1, "FAULT": 2}
TOWER_CODES = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def encode_u32(value):
    value = max(0, min(int(value), 0xFFFFFFFF))
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]


class Machine:
    def __init__(self, scenario="normal"):
        self.scenario = scenario
        self.started = time.monotonic()
        self.parts = 0
        self.temperature = 43.0
        self.phase = 0.0

    def sample(self):
        elapsed = time.monotonic() - self.started
        self.phase += 0.12

        state = "RUN"
        vibration = 2.1 + 0.25 * math.sin(self.phase) + random.uniform(-0.08, 0.08)
        temperature_target = 44.0 + 0.4 * math.sin(self.phase / 5)
        current = 7.2 + 0.5 * math.sin(self.phase / 2) + random.uniform(-0.15, 0.15)

        if self.scenario == "overheat":
            temperature_target += min(18.0, elapsed * 0.15)

        if self.scenario == "high_vibration":
            vibration = 8.2 + 0.4 * math.sin(self.phase) + random.uniform(-0.1, 0.1)

        if self.scenario == "fault":
            state = "FAULT"
            current = 0.0

        if self.scenario == "idle":
            state = "IDLE"
            current = 0.4
            vibration = 0.2

        self.temperature += (temperature_target - self.temperature) * 0.08
        temperature = self.temperature

        if state == "RUN":
            self.parts += 1

        if vibration >= 7.0 or temperature >= 75.0 or state == "FAULT":
            tower = "RED"
        elif vibration >= 4.5 or temperature >= 60.0:
            tower = "YELLOW"
        else:
            tower = "GREEN"

        emergency_stop = 1 if tower == "RED" else 0

        return {
            "vibration": round(vibration, 2),
            "bearing_temperature": round(temperature, 2),
            "motor_current": round(current, 2),
            "parts_count": self.parts,
            "machine_state": state,
            "signal_tower": tower,
            "emergency_stop": emergency_stop,
        }


def make_registers(data):
    parts_hi, parts_lo = encode_u32(data["parts_count"])
    return [
        max(0, min(round(data["vibration"] * 10), 65535)),
        max(0, min(round(data["bearing_temperature"] * 10), 65535)),
        max(0, min(round(data["motor_current"] * 100), 65535)),
        parts_hi,
        parts_lo,
        STATE_CODES[data["machine_state"]],
        TOWER_CODES[data["signal_tower"]],
        data["emergency_stop"],
    ]


async def update_registers(context, machine):
    while True:
        data = machine.sample()
        registers = make_registers(data)
        context[0].setValues(3, 0, registers)
        log.info(
            "vibration=%.2f mm/s | bearing=%.2f C | current=%.2f A | "
            "parts=%d | state=%s | tower=%s | emergency_stop=%d",
            data["vibration"],
            data["bearing_temperature"],
            data["motor_current"],
            data["parts_count"],
            data["machine_state"],
            data["signal_tower"],
            data["emergency_stop"],
        )
        await asyncio.sleep(UPDATE_SECONDS)


async def main():
    parser = argparse.ArgumentParser(description="IIoT machine Modbus simulator")
    parser.add_argument(
        "--scenario",
        choices=["normal", "overheat", "high_vibration", "fault", "idle"],
        default="normal",
        help="Select a demonstration scenario",
    )
    args = parser.parse_args()

    machine = Machine(args.scenario)
    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(0, [0] * 8),
    )
    context = ModbusServerContext(slaves=store, single=True)

    asyncio.create_task(update_registers(context, machine))
    log.info("Starting machine simulator: %s on %s:%d", args.scenario, HOST, PORT)
    await StartAsyncTcpServer(context=context, address=(HOST, PORT))


if __name__ == "__main__":
    asyncio.run(main())
