#!/bin/bash
# Setup script for Vocal Reference Generator Web App
# Run this as the webadmin user (or root, then chown to webadmin)

set -e

APP_DIR="/home/webadmin/vocal-web"
VENV_DIR="$APP_DIR/venv"

echo "=========================================="
echo "Vocal Reference Generator — Web Setup"
echo "=========================================="
echo ""

# Check if running as webadmin or root
if [ "$EUID" -eq 0 ]; then
    RUN_USER="webadmin"
    echo "Running as root. Will create files owned by $RUN_USER."
else
    RUN_USER="$USER"
    echo "Running as $RUN_USER."
fi

# Create app directory
echo "Creating app directory at $APP_DIR..."
mkdir -p "$APP_DIR"

# Copy application files (assumes you're running this from the project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Copying app files from $SCRIPT_DIR..."
cp -r "$SCRIPT_DIR"/* "$APP_DIR/"

# Ensure uploads/outputs exist
mkdir -p "$APP_DIR/uploads" "$APP_DIR/outputs"

# Create virtual environment
echo "Creating Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Activate and install dependencies
echo "Installing Python packages (this may take a few minutes)..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Copy the systemd service file:"
echo "   sudo cp $APP_DIR/vocal-web.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable vocal-web"
echo "   sudo systemctl start vocal-web"
echo ""
echo "2. Add Apache proxy rules to your Virtualmin site:"
echo "   In Virtualmin, go to:"
echo "   Services -> Configure Website -> Edit Directives"
echo ""
echo "   Add these lines BEFORE the closing </VirtualHost>:"
echo ""
echo '   <IfModule mod_proxy.c>'
echo '       ProxyPass /vocal-ref http://127.0.0.1:5000'
echo '       ProxyPassReverse /vocal-ref http://127.0.0.1:5000'
echo '   </IfModule>'
echo ""
echo "3. Restart Apache:"
echo "   sudo systemctl restart apache2"
echo ""
echo "4. Visit: https://yourdomain.com/vocal-ref"
echo ""
