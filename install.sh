#!/bin/bash
set -euo pipefail

UDEV_RULE_PATH="/etc/udev/rules.d/99-odid-rider.rules"
SERVICE_PATH="/etc/systemd/system/odid-slip-reader@.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR"
PROPRIETARY_DIR="$SCRIPT_DIR/proprietary"
CURRENT_USER="$(whoami)"
CURRENT_GROUP="$(id -gn)"

usage() {
    echo "Usage: $0 --output <output_directory>"
    echo ""
    echo "  --output <dir>   Directory where logs and JSONL data will be written."
    echo "                   A datetime-stamped file is created per connection."
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

# --- Proprietary OpenDroneID parser (optional) ---
if [[ -d "$PROPRIETARY_DIR" ]]; then
    echo "==> Attempting proprietary OpenDroneID parser installation"
    PYLIBODID_INSTALLED=false

    if "$INSTALL_DIR/venv/bin/pip" install --quiet \
            --find-links "$PROPRIETARY_DIR" --no-index pylibopendroneid 2>/dev/null; then
        PYLIBODID_INSTALLED=true
        echo "    pylibopendroneid: installed"
    else
        echo "Warning: pylibopendroneid installation failed — proprietary ODID parser will not be available"
    fi

    PYODID_WHEEL="$(find "$PROPRIETARY_DIR" -maxdepth 1 -name "pyopendroneid-*.whl" | sort | tail -1)"
    if [[ "$PYLIBODID_INSTALLED" == "true" ]]; then
        if [[ -n "$PYODID_WHEEL" ]]; then
            "$INSTALL_DIR/venv/bin/pip" install --quiet "$PYODID_WHEEL"
            echo "    pyopendroneid: installed from $(basename "$PYODID_WHEEL")"
        else
            echo "Warning: no pyopendroneid wheel found in $PROPRIETARY_DIR — parser may not function correctly"
        fi
    fi
else
    echo "Note: no proprietary/ directory found — skipping proprietary parser"
fi
# --------------------------------------------------

echo "==> Writing wrapper script"
cat > "$INSTALL_DIR/run_slip_reader.sh" << WRAPPER_EOF
#!/bin/bash
# Invoked by the systemd service. Argument: kernel device name (e.g. ttyUSB0)
DEVICE="/dev/\$1"
OUTPUT_DIR="${OUTPUT_DIR}"
TIMESTAMP=\$(date +"%Y%m%d_%H%M%S")
LOG_FILE="\${OUTPUT_DIR}/\${TIMESTAMP}_\$1.log"
exec "${INSTALL_DIR}/venv/bin/python" "${INSTALL_DIR}/odid_slip_reader.py" \
    -p "\$DEVICE" --init "2A0A0A" --storage "${OUTPUT_DIR}" >> "\$LOG_FILE" 2>&1
WRAPPER_EOF
chmod +x "$INSTALL_DIR/run_slip_reader.sh"

echo "==> Installing systemd service: $SERVICE_PATH"
sudo tee "$SERVICE_PATH" > /dev/null << SERVICE_EOF
[Unit]
Description=ODID SLIP Reader on /dev/%I
After=dev-%i.device
BindsTo=dev-%i.device

[Service]
Type=simple
User=${CURRENT_USER}
Group=${CURRENT_GROUP}
ExecStart=${INSTALL_DIR}/run_slip_reader.sh %I
Restart=always
RestartSec=5
StartLimitIntervalSec=0
StandardOutput=null
StandardError=null
SERVICE_EOF

sudo systemctl daemon-reload

echo "==> Installing udev rule: $UDEV_RULE_PATH"
# Dronetag RIDER identification from dtmux.rules:
#   idVendor 10c4, idProduct ea60, serial 0x6969 -> symlink ttyDRI
sudo tee "$UDEV_RULE_PATH" > /dev/null << UDEV_EOF
# Dronetag RIDER — ODID SLIP Reader
# Starts odid-slip-reader@.service; data goes to ${OUTPUT_DIR}/<timestamp>_<dev>.jsonl
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
sudo udevadm control --reload-rules
sudo udevadm trigger

echo ""
echo "Done."
echo "  Install dir : $INSTALL_DIR"
echo "  Output dir  : $OUTPUT_DIR"
echo "  Udev rule   : $UDEV_RULE_PATH"
echo "  Service     : $SERVICE_PATH"
echo ""
echo "Plug in the Dronetag RIDER (ttyDRI) to start capturing."
echo "Per connection:"
echo "  JSONL data : $OUTPUT_DIR/<YYYYMMDD_HHMMSS>_<device>.jsonl"
echo "  stdout log : $OUTPUT_DIR/<YYYYMMDD_HHMMSS>_<device>.log"
