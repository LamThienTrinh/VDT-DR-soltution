#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /opt/netbox"
  exit 1
fi

NETBOX_ROOT="$1"
NETBOX_APP="$NETBOX_ROOT/netbox"

if [[ ! -f "$NETBOX_APP/manage.py" ]]; then
  echo "Cannot find $NETBOX_APP/manage.py"
  exit 1
fi

mkdir -p "$NETBOX_APP/dcim/management/commands"
cp generate_viettel_demo.py "$NETBOX_APP/dcim/management/commands/"
mkdir -p "$NETBOX_ROOT/synthetic"
cp viettel_demo.yaml "$NETBOX_ROOT/synthetic/"

echo "Installed command and config."
echo "Next:"
echo "  cd $NETBOX_APP"
echo "  source $NETBOX_ROOT/venv/bin/activate"
echo "  python manage.py help generate_viettel_demo"
