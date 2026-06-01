# README

## Setup Instructions

### 1. Create and activate a Python virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate   # On Windows use: venv\Scripts\activate
```

### 2. Install dependencies from `requirements.txt`

```bash
pip install -r requirements.txt
```

### 3. Install the Dronetag Proto Receiver package

Make sure you have the `dtproto_receiver-2.1.0-py3-none-any.whl` file available locally, then run:

```bash
pip install dtproto_receiver-2.1.0-py3-none-any.whl
```

---

## Example Usage

```bash
python odid_slip_reader.py -p /dev/ttyUSB0 --init "2A0A0A"
```

Replace `/dev/ttyUSB0` with your actual serial port name (the Dronetag RIDER appears as `/dev/ttyDRI` after the udev rule is installed).

---

## Automated Installation (udev + systemd)

`install.sh` installs the slip reader into a system-wide virtual environment, creates a udev rule that detects the Dronetag RIDER, and starts the reader automatically each time the device is plugged in. Output is written to a datetime-stamped log file.

### Usage

```bash
sudo ./install.sh --output ./output
```

The `--output` argument sets the directory where log files are written. Each connection creates a new file named `<YYYYMMDD_HHMMSS>_<device>.log` inside that directory.

### What it installs

| Path | Description |
|---|---|
| `/opt/odid_slip_reader/` | Script, wheel, and virtual environment |
| `/etc/udev/rules.d/99-odid-rider.rules` | Udev rule for Dronetag RIDER (VID `10c4`, PID `ea60`, serial `0x6969`) |
| `/etc/systemd/system/odid-slip-reader@.service` | Systemd service template started by the udev rule |

### How it works

1. The udev rule matches the Dronetag RIDER on plug-in and sets `SYSTEMD_WANTS=odid-slip-reader@<dev>.service`.
2. The systemd service calls the wrapper script with the kernel device name.
3. The wrapper opens the serial port and redirects all output to `<output_dir>/<timestamp>_<dev>.log`.

To verify after plugging in:

```bash
systemctl status "odid-slip-reader@ttyUSB0.service"
ls ./output/
```

---

## Notes

- The virtual environment keeps dependencies isolated.
- The wheel package `dtproto_receiver-2.1.0-py3-none-any.whl` must be downloaded or copied to your project folder before installing.
- Your `requirements.txt` should contain all other needed libraries (e.g., `serial_asyncio`).

---

## Message Encoding

### SLIP Encoding

Messages over the serial interface use the [SLIP (Serial Line Internet Protocol)](https://tools.ietf.org/html/rfc1055) format for framing.

SLIP special characters:

- `END` (`0x0A` or `\n`) — marks the end of a message
- `ESC` (`0xDB`) — escape character
- `ESC_END` (`0xDC`) — used to encode `END` inside data
- `ESC_ESC` (`0xDD`) — used to encode `ESC` inside data

#### Encoding Rules

- `END` (`0x0A`) is encoded as `ESC` `ESC_END` (`0xDB 0xDC`)
- `ESC` (`0xDB`) is encoded as `ESC` `ESC_ESC` (`0xDB 0xDD`)
- Encoded messages are terminated with `END` (`0x0A`)

---

### Protobuf Message Framing

The decoded SLIP payload is expected to be:

```
[address][protobuf message]
```

- The first byte (`address`) is used to dispatch the message to the appropriate handler.
- The remainder is a protobuf message, encoded with a **varint-prefixed length** (as used in Protobuf's delimited messages).

#### Protobuf Delimited Format

Each protobuf message is preceded by a varint indicating its size:

```
[varint length][protobuf bytes]
```

This format allows concatenated protobuf messages to be read from a stream.

The script includes a buffering mechanism to reassemble fragmented protobuf messages and remove the varint prefix before deserializing.

---

## Bluetooth Support (Dronetag RIDER)

In addition to serial SLIP communication, the script can also interact with the **Dronetag RIDER** device over **Bluetooth Low Energy (BLE)**.

The Dronetag RIDER exposes a custom **Notify Characteristic** for streaming messages using a Protobuf-based format. Unlike the serial interface, Bluetooth messages are **not SLIP-encoded** — they are raw protobuf messages framed using a **length-prefixed (varint) format**, suitable for stream-based processing.

### Bluetooth UUIDs

The Bluetooth GATT service and characteristic UUIDs used for communication are:

- **Service UUID**:
  ```
  898aa51c-f6be-4ad5-9398-e43f27cd93fc
  ```
- **Notify Characteristic UUID**:
  ```
  edb0b8a3-cf30-485c-bd8f-61f8ce998de8
  ```

### Message Format

Each notification from the characteristic contains:

```
[varint length][protobuf bytes]
```

These messages can be buffered and deserialized using standard Protobuf mechanisms for delimited streams (e.g., `FromString()` after stripping the length prefix).

### Integration Notes

- Notifications are typically sent periodically or upon new data being available.
- Since SLIP framing is not used, message boundaries are determined purely by the varint-prefixed Protobuf framing.

This approach is useful when a BLE connection is preferred over a wired serial interface, such as in mobile or embedded setups where physical access to USB is limited.

---

## Serial Message Address and Activation

When using the serial SLIP interface to communicate with **Dronetag RIDER**, messages carrying Protobuf data are sent with the address:

```
0x2A
```

### Activation Requirement

To begin receiving messages on this channel, you **must first activate it** by sending an initial message. This is handled automatically by the script using the default `--init` value:

```
2A0A0A
```

This message is:

- Address byte: `0x2A`
- Payload: `0x0A 0x0A` (dummy data to trigger the channel)

The script sends this message (SLIP-encoded) right after opening the serial port.

You can modify or disable this activation sequence using the `--init` command-line argument.


---

## OpenDroneID Parser Notice

This sample project is designed to work with **Protobuf messages** that contain OpenDroneID data along with reception metadata (RSSI, MAC address, technology, etc.).

Dronetag uses an **internal Python OpenDroneID parser** to decode and display these messages in a human-readable format. This parser is **not publicly available**.

While the script includes code compatible with the internal parser (`pyopendroneid` and `dtproto_receiver`), full decoding of OpenDroneID data requires access to our proprietary parser.

If you require access for development or integration purposes, please **contact our support team at**:

📧 [support@dronetag.com](mailto:support@dronetag.com)
