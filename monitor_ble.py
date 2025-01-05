import sys
import cv2
import threading
import asyncio
from itertools import count, takewhile
from typing import Iterator

from PyQt5.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QImage, QPixmap

from bleak import BleakClient, BleakScanner, BleakError
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from AVFoundation import AVCaptureDevice
from qtkeystring import qt_key_to_string

# ---- NUS(UART) UUID ----
UART_SERVICE_UUID = "597f1290-5b99-477d-9261-f0ed801fc566"
UART_RX_CHAR_UUID = "597f1291-5b99-477d-9261-f0ed801fc566"  # Write
UART_TX_CHAR_UUID = "597f1292-5b99-477d-9261-f0ed801fc566"  # Notify


# ------------------------------------------------------
def sliced(data: bytes, n: int) -> Iterator[bytes]:
    return takewhile(len, (data[i : i + n] for i in count(0, n)))

# ===================================================
# 1. Video Capture
# ===================================================
class VideoCaptureAsync:
    def __init__(self, src=0):
        self.src = src
        self.cap = cv2.VideoCapture(self.src)
        self.grabbed, self.frame = self.cap.read()
        self.stopped = False
        self.lock = threading.Lock()

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 60)

        # minimize frame buffer
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # OpenCL
        if cv2.ocl.haveOpenCL():
            cv2.ocl.setUseOpenCL(True)
            print("OpenCL Activated.")
        else:
            print("OpenCL failed.")

    def start(self):
        threading.Thread(target=self.update, args=(), daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            try:
                grabbed, frame = self.cap.read()
                if not grabbed:
                    print("Unable to read frame.")
            except cv2.error as e:
                print(f"Capture device error: {e}")
                self.stop()
                break

            with self.lock:
                self.grabbed = grabbed
                self.frame = frame

    def read(self):
        with self.lock:
            if self.grabbed and self.frame is not None:
                return self.grabbed, self.frame.copy()
            else:
                return False, None

    def stop(self):
        self.stopped = True
        self.cap.release()


# ===================================================
# 2. BLE Manager (Nordic UART Service)
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

        # 1) Scan NUS Device
        def match_nus_uuid(device: BLEDevice, adv: AdvertisementData):
            if UART_SERVICE_UUID.lower() in adv.service_uuids:
                return True
            return False

        print("[BLE] Scanning NUS device...")
        device = await BleakScanner.find_device_by_filter(match_nus_uuid)

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
            await client.start_notify(UART_TX_CHAR_UUID, self.handle_rx)
            print("[BLE] Notify on (waiting for data)")

            # 4) Save RX characteristic for write
            nus_service = client.services.get_service(UART_SERVICE_UUID)
            self.rx_char = nus_service.get_characteristic(UART_RX_CHAR_UUID)

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
        """
        PyQt 메인 스레드에서 안전하게 호출할 수 있는 동기 함수.
        내부적으로는 asyncio 코루틴에 태스크를 제출(run_coroutine_threadsafe).
        """
        if not self.connected or not self.rx_char:
            print("[BLE] Not connected or RX characteristic not found.")
            return

        future = asyncio.run_coroutine_threadsafe(
            self._send_data(msg), self.loop
        )
        # 필요하다면 결과를 기다릴 수도 있으나, 여기서는 비동기 제출만 함.
        # e.g. result = future.result()

    async def _send_data(self, msg: str):
        # BLE GATT write (async)
        if not self.rx_char or not self.client:
            print("[BLE] No client or RX characteristic.")
            return

        data = msg.encode()
        max_size = self.rx_char.max_write_without_response_size
        # BLE 패킷 단위로 쪼개서 write
        for chunk in sliced(data, max_size):
            await self.client.write_gatt_char(self.rx_char, chunk, response=False)
        print(f"[BLE] send complete : {msg}")


# ===================================================
# 3. PyQt5 GUI App (Video + BLE)
# ===================================================
class VideoApp(QWidget):
    def __init__(self, video_source=0, source_name="", ble_manager=None):
        super().__init__()
        self.setWindowTitle(f"PyQt5 + OpenCV Async (cam {video_source} : {source_name})")
        self.video_source = video_source
        self.ble_manager = ble_manager

        # Init UI
        self.setGeometry(100, 100, 960, 540)

        # VideoCaptureAsync instance
        self.cap = VideoCaptureAsync(self.video_source).start()

        # QLabel widget(video frame)
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setMinimumSize(1, 1)

        # layout
        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        self.setLayout(layout)

        # 60fps update
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(16)

        # original video size for aspect ratio
        self.original_aspect_ratio = 1920 / 1080

    def update_frame(self):
        grabbed, frame = self.cap.read()
        if grabbed and frame is not None:
            # BGR->RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)

            self.image_label.setPixmap(pixmap.scaled(
                self.image_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            ))

    def resizeEvent(self, event):
        self.update_frame()
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        # key_text = event.text()
        # print(f"Key press: {qt_key_to_string(event.key())} (Key Code: {hex(event.key())}) (Mod Key: {hex(event.nativeModifiers())}) (Virtual Key: {event.nativeVirtualKey()}) (Scancode: {event.nativeScanCode()})")

        # Send BLE
        if self.ble_manager:
            self.ble_manager.send_data_sync(f"P:{hex(event.key())}")

    def keyReleaseEvent(self, event):
        # print(f"Key release: {qt_key_to_string(event.key())} (Key Code: {hex(event.key())}) (Mod Key: {hex(event.nativeModifiers())}) (Virtual Key: {event.nativeVirtualKey()}) (Scancode: {event.nativeScanCode()})")

        # Send BLE
        if self.ble_manager:
            self.ble_manager.send_data_sync(f"R:{hex(event.key())}")

    def closeEvent(self, event):
        print("Program Termination")
        self.timer.stop()
        self.cap.stop()
        event.accept()


def get_camera_names():
    devices = AVCaptureDevice.devicesWithMediaType_("vide")
    camera_names = [device.localizedName() for device in devices]
    return camera_names

def select_camera_by_name(target_name, camera_names):
    for idx, name in enumerate(camera_names):
        if target_name in name:
            return idx
    return -1

# ===================================================
# 4. main 
# ===================================================
def main():
    target_name = "UGREEN-25854"
    camera_names = get_camera_names()
    print("Available Cameras:")
    for idx, name in enumerate(camera_names):
        print(f"{idx}: {name}")

    selected_cam = select_camera_by_name(target_name, camera_names)
    if selected_cam < 0:
        print(f"Camera '{target_name}' not found.")
        sys.exit(1)
    
    print(f"Selected Camera: {camera_names[selected_cam]}")
    # 1) BLE manager
    ble_manager = BleManager()

    # 2) start PyQt5 App
    app = QApplication(sys.argv)

    # cam index

    window = VideoApp(selected_cam, camera_names[selected_cam], ble_manager=ble_manager)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
