#!/bin/bash
set -euo pipefail

UDEV_RULE_PATH="/etc/udev/rules.d/99-odid-rider.rules"
SERVICE_PATH="/etc/systemd/system/odid-slip-reader@.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR"

usage() {
    echo "Usage: $0 --output <output_directory>"
    echo ""
    echo "  --output <dir>   Directory where slip reader logs will be written"
    echo "                   A datetime-stamped log file is created per connection."
    exit 1
}

OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output)
            OUTPUT_DIR="$(realpath "$2")"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            ;;
    esac
done

if [[ -z "$OUTPUT_DIR" ]]; then
    usage
fi

if [[ "$EUID" -ne 0 ]]; then
    echo "Error: this script must be run as root (use sudo)"
    exit 1
fi

echo "==> Creating output directory: $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

echo "==> Creating Python virtual environment"
python3 -m venv "$INSTALL_DIR/venv"

echo "==> Installing Python dependencies"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet pyserial-asyncio betterproto
"$INSTALL_DIR/venv/bin/pip" install --quiet git+https://github.com/dronetag/python-odid
if [[ -f "$INSTALL_DIR/dtproto_receiver-2.1.0-py3-none-any.whl" ]]; then
    "$INSTALL_DIR/venv/bin/pip" install --quiet "$INSTALL_DIR/dtproto_receiver-2.1.0-py3-none-any.whl"
fi

echo "==> Writing wrapper script"
cat > "$INSTALL_DIR/run_slip_reader.sh" << WRAPPER_EOF
#!/bin/bash
# Wrapper invoked by the systemd service. Argument: kernel device name (e.g. ttyUSB0)
DEVICE="/dev/\$1"
OUTPUT_DIR="${OUTPUT_DIR}"
TIMESTAMP=\$(date +"%Y%m%d_%H%M%S")
OUTPUT_FILE="\${OUTPUT_DIR}/\${TIMESTAMP}_\$1.log"
mkdir -p "\$OUTPUT_DIR"
exec "${INSTALL_DIR}/venv/bin/python" "${INSTALL_DIR}/odid_slip_reader.py" \
    -p "\$DEVICE" --init "2A0A0A" >> "\$OUTPUT_FILE" 2>&1
WRAPPER_EOF
chmod +x "$INSTALL_DIR/run_slip_reader.sh"

echo "==> Installing systemd service: $SERVICE_PATH"
cat > "$SERVICE_PATH" << SERVICE_EOF
[Unit]
Description=ODID SLIP Reader on /dev/%I
After=dev-%i.device

[Service]
Type=simple
ExecStart=${INSTALL_DIR}/run_slip_reader.sh %I
Restart=no
StandardOutput=null
StandardError=null
SERVICE_EOF

systemctl daemon-reload

echo "==> Installing udev rule: $UDEV_RULE_PATH"
# Dronetag RIDER identification from dtmux.rules:
#   idVendor 10c4, idProduct ea60, serial 0x6969 -> symlink ttyDRI
cat > "$UDEV_RULE_PATH" << UDEV_EOF
# Dronetag RIDER — ODID SLIP Reader
# Starts odid-slip-reader@.service and logs output to ${OUTPUT_DIR}/<timestamp>_<dev>.log
ACTION!="add", GOTO="odid_rider_end"

SUBSYSTEM=="tty",\
 ATTRS{idVendor}=="10c4",\
 ATTRS{idProduct}=="ea60",\
 ATTRS{serial}=="0x6969",\
 SYMLINK+="ttyDRI",\
 TAG+="systemd",\
 ENV{SYSTEMD_WANTS}+="odid-slip-reader@%k.service",\
 MODE="0666"

LABEL="odid_rider_end"
UDEV_EOF

echo "==> Reloading udev rules"
udevadm control --reload-rules
udevadm trigger

echo ""
echo "Done."
echo "  Install dir : $INSTALL_DIR"
echo "  Output dir  : $OUTPUT_DIR"
echo "  Udev rule   : $UDEV_RULE_PATH"
echo "  Service     : $SERVICE_PATH"
echo ""
echo "Plug in the Dronetag RIDER (ttyDRI) to start capturing."
echo "Each connection creates: $OUTPUT_DIR/<YYYYMMDD_HHMMSS>_<device>.log"
