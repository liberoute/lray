# Systemd Service

## Install

```bash
# Copy binary
sudo cp lray /usr/local/bin/lray

# Create config directory
sudo mkdir -p /etc/lray /var/log/lray
sudo cp config.example.json /etc/lray/config.json
sudo nano /etc/lray/config.json  # edit auth_key and script_id

# Install service
sudo cp deploy/systemd/lray.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lray
sudo systemctl start lray
```

## Commands

```bash
sudo systemctl status lray
sudo systemctl restart lray
sudo journalctl -u lray -f
```
