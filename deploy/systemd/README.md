# Systemd Service Files

## Install

```bash
# Copy service files
sudo cp lray.service /etc/systemd/system/
sudo cp lray@.service /etc/systemd/system/

# Create directories
sudo mkdir -p /etc/lray
sudo mkdir -p /var/log/lray

# Copy your config
sudo cp /opt/projects/lray/config.json /etc/lray/config.json

# Reload systemd
sudo systemctl daemon-reload
```

## Usage

### Default instance (uses /etc/lray/config.json)

```bash
sudo systemctl start lray
sudo systemctl enable lray      # auto-start on boot
sudo systemctl status lray
sudo journalctl -u lray -f      # live logs
```

Logs:
- `/var/log/lray/access.log` — INFO level (requests, connections)
- `/var/log/lray/error.log` — WARNING/ERROR level (failures, issues)

### Named instances (multiple configs)

```bash
# Create config for instance "test1"
sudo cp config.json /etc/lray/test1.json
# Edit with different port, script_id, etc.

# Start instance
sudo systemctl start lray@test1
sudo systemctl enable lray@test1
```

Logs for `test1`:
- `/var/log/lray/test1/access.log`
- `/var/log/lray/test1/error.log`

### Multiple instances example

```bash
# Instance for personal use (port 8085)
sudo systemctl start lray@personal

# Instance for family (port 8086, different GAS script)
sudo systemctl start lray@family

# Instance for testing (port 9000, debug logging)
sudo systemctl start lray@testing
```

Each reads `/etc/lray/{name}.json` and logs to `/var/log/lray/{name}/`.

## Log Rotation

Create `/etc/logrotate.d/lray`:

```
/var/log/lray/*.log /var/log/lray/*/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

## Uninstall

```bash
sudo systemctl stop lray
sudo systemctl disable lray
sudo rm /etc/systemd/system/lray.service
sudo rm /etc/systemd/system/lray@.service
sudo systemctl daemon-reload
```
