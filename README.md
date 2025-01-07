# HID BLE Relay Host

The **HID BLE Relay Host** is a Python application designed to work with the **HID Relay Dongle** firmware running on an nRF52840 Dongle. It captures HDMI video from a USB capture card and transmits keyboard and mouse input over Bluetooth Low Energy (BLE) to the dongle, which relays the hid inputs to a headless system.

This application has been tested on macOS.

---

## Features

### 1. **HDMI Video Display**
- Captures and displays real-time HDMI video feed via a USB capture card, via pyqt5

### 2. **Keyboard and Mouse Input Transmission via BLE**
- Detects and processes key and mouse press and release events when the application is focused.
- Sends key events and absolute mouse event to the **HID Relay Dongle** using a custom Nordic UART Service (NUS) over BLE.

### 3. **Custom BLE UUIDs**
The application communicates with the dongle using the following custom UUIDs:
- **Service UUID**: `597f1290-5b99-477d-9261-f0ed801fc566`
- **RX Characteristic UUID**: `597f1291-5b99-477d-9261-f0ed801fc566`
- **TX Characteristic UUID**: `597f1292-5b99-477d-9261-f0ed801fc566`

---

## Dependencies

### Hardware
- **USB Capture Card**: For HDMI video input (e.g., UGREEN Capture Card).
- **nRF52840 Dongle**: Running the [HID Relay Dongle](https://github.com/saga0619/HID_BLE_relay_dongle) firmware.

### Software
- **Python 3.10+**
- Python packages (install with `pip`):
  - `PyQt5`
  - `bleak`
  - `qtkeystring`

---

## Setup and Installation

### 1. Clone the Repository
```bash
git clone https://github.com/saga0619/HID_BLE_relay_host.git
cd HID-Relay-Host
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Application
```bash
python main.py
```

---

## Usage

### Connecting to HID Relay Dongle
1. Power on the nRF52840 Dongle with the [HID Relay Dongle](https://github.com/saga0619/HID_BLE_relay_dongle) firmware installed.
2. The application scans for BLE devices supporting the custom Nordic UART Service UUIDs.
3. The BLE connection is established automatically upon finding the dongle.

### HDMI Video Input
1. Connect your USB capture card to the system.
2. The application lists all available video devices at startup and selects the predefined target (default: `UGREEN-25854`).
3. If the target device is not found, update the `target_name` variable in `main()`.

### Keyboard Input
- While the application window is in focus:
  - **Key Press**: Sends a BLE message in the format `KP:<KeyCode>` to the dongle.
  - **Key Release**: Sends a BLE message in the format `KR:<KeyCode>` to the dongle.

### Mouse Input
- While the application window is in focus:
  - **Mouse Press**: Sends a BLE message in the format `M<Action>:<Xcoordinate>,<Ycoordinate>` to the dongle.
  - **Mouse Release**: Sends a BLE message in the format `M<Action>:<Xcoordinate>,<Ycoordinate>` to the dongle.

### Closing the Application
- Exit the application window to stop video capture and BLE communication.

---

## Related Project: HID Relay Dongle

The **HID BLE Relay Host** works in conjunction with the **HID Relay Dongle** firmware. The dongle bridges the BLE keyboard input from this host application to a USB-connected server or headless system.

Learn more about the HID Relay Dongle:  
[HID Relay Dongle](https://github.com/saga0619/HID_BLE_relay_dongle)

---

## Troubleshooting

### BLE Connection Issues
- Ensure the nRF52840 Dongle is powered on and running the correct firmware.
- Restart the application to retry the BLE connection process.

### Video Not Displayed
- Verify the USB capture card is connected and supported by your system.
- Ensure the correct device name matches the target in the code.

### Key Events Not Transmitted
- Ensure the application window is in focus while typing.
- Check logs for errors related to BLE communication or key detection.

---

## Acknowledgments

This project integrates:
- Nordic UART Service for BLE communication.
- OpenCV for video capture and display.
- PyQt5 for GUI development.
- The [HID Relay Dongle](https://github.com/saga0619/HID_BLE_relay-dongle) firmware for seamless integration.
