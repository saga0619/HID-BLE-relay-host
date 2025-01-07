import sys
import threading
import asyncio
from PyQt5.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtMultimedia import QCamera, QCameraInfo, QCameraViewfinderSettings
from PyQt5.QtMultimediaWidgets import QCameraViewfinder
from PyQt5.QtGui import QImage, QPixmap
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from itertools import count, takewhile
from typing import Iterator
# ---- TARGET CAPTURE BOARD NAME ----
TARGET_CAMERA_NAME = "UGREEN-25854"

# ---- TARGET CAPTURE RESOLUTION ----
TARGET_CAPTURE_WIDTH = 1920
TARGET_CAPTURE_HEIGHT = 1080

# ---- TARGET CAPTURE FPS ----
TARGET_CAPTURE_FPS = 60

# ---- TARGET BLE DEVICE ----
TARGET_BLE_NAME = "HID BLE Relay"

# ---- NUS(UART) UUID ----
HID_SERVICE_UUID = "597f1290-5b99-477d-9261-f0ed801fc566"
HID_RX_CHAR_UUID = "597f1291-5b99-477d-9261-f0ed801fc566"  # Write
HID_TX_CHAR_UUID = "597f1292-5b99-477d-9261-f0ed801fc566"  # Notify

# ------------------------------------------------------
def sliced(data: bytes, n: int) -> Iterator[bytes]:
    return takewhile(len, (data[i : i + n] for i in count(0, n)))

# ===================================================
# 1. BLE Manager (Nordic UART Service)
# ===================================================
class BleManager:
    def __init__(self):
        self.client: BleakClient | None = None
        self.connected = False
        self.rx_char: BleakGATTCharacteristic | None = None

        
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        while True:
            try:
                self.loop.run_until_complete(self.connect_and_run())
            except Exception as e:
                print(f"[BLE] Exeption : {e}")
                self.loop.stop()
                break

    async def connect_and_run(self):
        # find and connect to NUS device, then register notify

        # 1) Scan Name 
        def match_hid_device(device: BLEDevice, adv: AdvertisementData):
            if device.name and TARGET_BLE_NAME in device.name:
                print(f"[BLE] Found HID Device: {device.name}")
                if HID_SERVICE_UUID.lower() in [s.lower() for s in adv.service_uuids]:
                    return True
            return False

        print("[BLE] Scanning NUS device...")
        device = await BleakScanner.find_device_by_filter(match_hid_device, timeout=10.0)
        # print(device)

        if device is None:
            print("[BLE] NUS Device not found.")
            return  # exit

        def handle_disconnect(_: BleakClient):
            print("[BLE] Device disconnected.")
            for task in asyncio.all_tasks():
                task.cancel()

        # 2) connect to NUS device
        print(f"[BLE] Connecting to {device.address}...")
        async with BleakClient(device, disconnected_callback=handle_disconnect) as client:
            self.client = client
            self.connected = True
            print("[BLE] Connected!")

            # 3) Notify configuration (UART_TX_CHAR_UUID)
            await client.start_notify(HID_TX_CHAR_UUID, self.handle_rx)
            print("[BLE] Notify on (waiting for data)")

            # 4) Save RX characteristic for write
            nus_service = client.services.get_service(HID_SERVICE_UUID)
            self.rx_char = nus_service.get_characteristic(HID_RX_CHAR_UUID)

            try:
                while True:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass
            finally:
                print("[BLE] connection closed.")
                self.connected = False
                self.client = None

    def handle_rx(self, _: BleakGATTCharacteristic, data: bytearray):
        print("[BLE] Recevied :", data)

    def send_data_sync(self, msg: str):
        if not self.connected or not self.rx_char:
            print("[BLE] Not connected or RX characteristic not found.")
            return

        future = asyncio.run_coroutine_threadsafe(
            self._send_data(msg), self.loop
        )
        # e.g. result = future.result()

    async def _send_data(self, msg: str):
        # BLE GATT write (async)
        if not self.rx_char or not self.client:
            print("[BLE] No client or RX characteristic.")
            return

        data = msg.encode()
        max_size = self.rx_char.max_write_without_response_size
        # sliced write for BLE packet size limit
        for chunk in sliced(data, max_size):
            await self.client.write_gatt_char(self.rx_char, chunk, response=False)
        # print(f"[BLE] send complete : {msg}")


# ===================================================
# 2. PyQt5 GUI App (QtMultimedia Camera + BLE)
# ===================================================
class VideoApp(QWidget):
    def __init__(self, camera_index=0, ble_manager=None):
        super().__init__()
        self.setWindowTitle(f"PyQt5 + QtMultimedia (Camera {camera_index})")
        self.ble_manager = ble_manager

        # Init UI
        self.setGeometry(100, 200, 960, 540)

        # QCamera and QCameraViewfinder
        self.camera_viewfinder = QCameraViewfinder(self)
        self.layout = QVBoxLayout()
        self.layout.addWidget(self.camera_viewfinder)

        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        # Select and configure camera
        cameras = QCameraInfo.availableCameras()
        if not cameras:
            print("No cameras available.")
            sys.exit()

        viewfinder_settings = QCameraViewfinderSettings()
        viewfinder_settings.setResolution(TARGET_CAPTURE_WIDTH, TARGET_CAPTURE_HEIGHT)
        viewfinder_settings.setMinimumFrameRate(TARGET_CAPTURE_FPS) 
        viewfinder_settings.setMaximumFrameRate(TARGET_CAPTURE_FPS) 

        self.camera = QCamera(cameras[camera_index])
        self.camera.setViewfinder(self.camera_viewfinder)

        self.camera.setViewfinderSettings(viewfinder_settings)
        self.camera.start()
        print("Available Resolution : ", self.camera.supportedViewfinderResolutions())
        print("Current resolution: ", self.camera.viewfinderSettings().resolution())

    def keyPressEvent(self, event):
        # print(f"Key Pressed: {hex(event.key())}")
        if self.ble_manager:
            self.ble_manager.send_data_sync(f"KP:{hex(event.key())}")

    def keyReleaseEvent(self, event):
        if self.ble_manager:
            self.ble_manager.send_data_sync(f"KR:{hex(event.key())}")

    def closeEvent(self, event):
        print("Program Termination")
        self.camera.stop()
        event.accept()

    def get_video_display_rect(self):
        resolution = self.camera.viewfinderSettings().resolution()
        video_width, video_height = resolution.width(), resolution.height()

        viewfinder_rect = self.camera_viewfinder.geometry()
        viewfinder_width, viewfinder_height = viewfinder_rect.width(), viewfinder_rect.height()

        aspect_video = video_width / video_height
        aspect_viewfinder = viewfinder_width / viewfinder_height

        if aspect_video > aspect_viewfinder:
            display_width = viewfinder_width
            display_height = int(viewfinder_width / aspect_video)
            offset_x = 0
            offset_y = (viewfinder_height - display_height) // 2
        else:
            display_width = int(viewfinder_height * aspect_video)
            display_height = viewfinder_height
            offset_x = (viewfinder_width - display_width) // 2
            offset_y = 0

        return offset_x, offset_y, display_width, display_height, video_width, video_height

    def mousePressEvent(self, event):
        x_fs, y_fx, width, height, rw, rh = self.get_video_display_rect()

        pos_x = int((event.pos().x() - x_fs)/width*32767)
        pos_y = int((event.pos().y() - y_fx)/height*32767)
        # print
        # print(f"pos: {self.camera.geometry()} ")
        # print(f"Mouse Pressed: {event.pos()} -> {widget_pos}")
        if event.button() == Qt.LeftButton:
            # print(f"Mouse Left Pressed: {event.pos()}")
            if self.ble_manager:
                self.ble_manager.send_data_sync(f"ML:{pos_x},{pos_y}")
        elif event.button() == Qt.RightButton:
            # print(f"Mouse Right Pressed: {event.pos()}")
            if self.ble_manager:
                self.ble_manager.send_data_sync(f"MR:{pos_x},{pos_y}")

    def mouseReleaseEvent(self, event):
        x_fs, y_fx, width, height,rw,rh = self.get_video_display_rect()

        pos_x = int((event.pos().x() - x_fs)/width*32767)
        pos_y = int((event.pos().y() - y_fx)/height*32767)

        # print(f"Mouse Released: {event.pos()}")
        if event.button() == Qt.LeftButton:
            if self.ble_manager:
                self.ble_manager.send_data_sync(f"MS:{pos_x},{pos_y}")
        elif event.button() == Qt.RightButton:
            if self.ble_manager:
                self.ble_manager.send_data_sync(f"ME:{pos_x},{pos_y}")

    def mouseMoveEvent(self, event):
        x_fs, y_fx, width, height,rw,rh = self.get_video_display_rect()

        pos_x = int((event.pos().x() - x_fs)/width*32767)
        pos_y = int((event.pos().y() - y_fx)/height*32767)
        # print(f"Mouse Moved: {event.pos()}")
        if self.ble_manager:
            self.ble_manager.send_data_sync(f"ML:{pos_x},{pos_y}")


# ===================================================
# 3. Main Function
# ===================================================
def main():
    app = QApplication(sys.argv)

    # BLE manager
    ble_manager = BleManager()
    selected_camera_index = 0

    target_found = False
    # Select the first available camera
    cameras = QCameraInfo.availableCameras()
    print("Available Cameras:")
    for idx, camera_info in enumerate(cameras):
        print(f"{idx}: {camera_info.description()}")
        if TARGET_CAMERA_NAME in camera_info.description():
            selected_camera_index = idx
            target_found = True
            break

    if not target_found:
        print(f"Target Camera {TARGET_CAMERA_NAME} not found. Selecting the first available camera.")

    if not cameras:
        print("No cameras detected.")
        sys.exit(1)

    print(f"Selected Camera: {selected_camera_index}: {cameras[selected_camera_index].description()}")

    # Start the PyQt5 application
    window = VideoApp(selected_camera_index, ble_manager=ble_manager)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
