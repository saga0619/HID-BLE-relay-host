# list ble devices

from bleak import BleakScanner
import asyncio

async def scan():
    devices = await BleakScanner.discover()
    for device in devices:
        print(device)

run = asyncio.run(scan())