# Development Environment Setup

Guide for setting up a development environment for the SolaX Modbus integration.

## Overview

This guide focuses on development using **Home Assistant OS (HAOS) with the SSH add-on**, which provides a complete development environment running directly on your Home Assistant instance.

## Prerequisites

### Required
- ✅ Home Assistant OS installation
- ✅ SSH & Web Terminal add-on installed and configured
- ✅ Git configured (username, email)
- ✅ GitHub account

### Recommended
- ✅ GitHub Personal Access Token (for pushing changes)
- ✅ Basic knowledge of git, Python, and shell commands

## Quick Setup

### Option 1: Automated Setup (Recommended)

```bash
# SSH into your Home Assistant instance
ssh root@homeassistant.local

# Navigate to config directory
cd /config

# Run automated dependency installer
./scripts/install-dependencies.zsh
```

**This installs:**
- Python linting tools (black, flake8)
- YAML/Markdown/Spelling tools (yamllint, markdownlint, codespell)
- Development tools (gh CLI)
- Documentation tools (mdbook, yq)
- Optional tools (todo.ai - personal preference, not required)

### Option 2: Manual Setup

If you prefer to install tools individually, see [Manual Installation](#manual-installation) below.

## Development Workflow

### 1. Fork and Clone

**On GitHub:**
1. Go to https://github.com/wills106/homeassistant-solax-modbus
2. Click "Fork" → Create fork in your account

**On your Home Assistant:**
```bash
# Navigate to custom components directory
cd /config/custom_components

# Clone your fork
git clone https://github.com/YOUR_USERNAME/homeassistant-solax-modbus.git solax_modbus_dev

# Add upstream remote
cd solax_modbus_dev
git remote add upstream https://github.com/wills106/homeassistant-solax-modbus.git
```

### 2. Create Development Branch

```bash
# Update main from upstream
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/my-feature
```

### 3. Make Changes

**Edit files directly:**
```bash
# Edit in your preferred editor
vi custom_components/solax_modbus/plugin_solax.py

# Or use the built-in editor in SSH add-on web interface
```

**Optional - check formatting:**
```bash
./scripts/lint.sh    # Check code style
./scripts/format.sh  # Auto-fix formatting
```

### 4. Test Changes

**Reload integration without restart:**
```bash
# Using Home Assistant API
ha-api --service reload_config_entry --domain homeassistant --data '{"entry_id": "ENTRY_ID"}' --json
```

**Check logs:**
```bash
ha core logs -f | grep solax_modbus
```

### 5. Commit and Push

```bash
git add .
git commit -m "feat: Add awesome feature"
git push origin feature/my-feature
```

### 6. Create Pull Request

1. Go to your fork on GitHub
2. Click "Pull Request"
3. Fill out PR template
4. Submit for review

## Development Tools

### Installed via install-dependencies.zsh

**Python Development:**
- `black` - Code formatter (version 25.1.0+)
- `flake8` - Style checker (version 7.2.0+)
- `codespell` - Spell checker

**Documentation:**
- `mdbook` - Handbook generator
- `yamllint` - YAML linter
- `markdownlint` - Markdown linter

**Utilities:**
- `gh` - GitHub CLI (version 2.40.1+)
- `yq` - YAML processor
- `todo.ai` - Task management (optional, personal preference of @fxstein)

**Image Processing:**
- `imagemagick` - Image manipulation
- `libjpeg-turbo` - JPEG support

### Optional Tools

**Pre-commit hooks** (run checks before commit):
```bash
# Install pre-commit (if pip available)
pip install pre-commit

# Enable hooks
cd /config/custom_components/solax_modbus_dev
pre-commit install
```

Now hooks run automatically on `git commit`.

## Home Assistant OS Specifics

### File System

```
/config/                           # Home Assistant configuration
├── custom_components/
│   ├── solax_modbus/             # Active integration (symlink)
│   └── solax_modbus_dev/         # Your development clone
├── scripts/
│   └── install-dependencies.zsh  # Dependency installer
└── www/                          # Web-accessible files
```

### SSH Add-on Configuration

The SSH add-on provides:
- ✅ Full shell access (zsh)
- ✅ Root permissions
- ✅ Git pre-installed
- ✅ Direct file system access
- ✅ Home Assistant CLI (`ha` command)

**Configuration:**
```yaml
# SSH add-on configuration
authorized_keys: []
password: ""
apks:
  - git
  - curl
  - wget
init_commands:
  - /config/scripts/install-dependencies.zsh
```

**Key benefit:** `init_commands` runs dependency installer on every SSH add-on restart, keeping tools updated.

### Alpine Linux Considerations

**Package manager:** `apk` (not apt/yum)

**Python packages:** Limited - use apk when possible:
```bash
apk add py3-black py3-flake8 py3-yamllint py3-codespell
```

**No pip install:** Can't install arbitrary Python packages (musl-based system)

## Hot Reload Development

**Best practice:** Test changes without restarting Home Assistant

```bash
# Reload integration via API
ha-api --service reload_config_entry --domain homeassistant \
  --data '{"entry_id": "YOUR_ENTRY_ID"}' --json

# Find entry_id:
ha-api --domain homeassistant --list-config-entries | grep solax
```

**Benefits:**
- ✅ No system disruption
- ✅ Fast iteration
- ✅ Logs stay continuous
- ✅ Other integrations unaffected

## Testing Your Changes

### Local Testing

**Minimum:**
```bash
# Check logs for errors
ha core logs | grep -i error | grep solax

# Verify integration loaded
ha-api --domain homeassistant --list-config-entries | grep solax

# Check sensor updates
ha-api --entity sensor.solax_1_pv_power_1
```

### Automated Checks

**GitHub Actions will run automatically when you push:**
- Black: Code formatting check
- Flake8: Style check
- Hassfest: Home Assistant validation
- HACS: Integration validation

**You don't need to run these locally** - push and let CI/CD check!

## Troubleshooting

### Tools Not Found

```bash
# Re-run dependency installer
./scripts/install-dependencies.zsh

# Verify installation
which black flake8 yamllint todo.ai
```

### Git Authentication Failed

```bash
# Verify GitHub token in secrets.yaml
yq e '.github_token' /config/secrets.yaml

# Re-configure git
./scripts/install-dependencies.zsh  # Runs configure_github()
```

### Integration Won't Reload

```bash
# Check for syntax errors
ha core check

# View recent logs
ha core logs -n 50 | grep solax

# Hard reload (if needed)
ha core restart  # Ask permission first!
```

### Pre-commit Hooks Failing

```bash
# Skip hooks if needed
git commit --no-verify

# Or fix issues
./scripts/format.sh  # Auto-fix formatting
./scripts/lint.sh    # Check what's wrong
```

## Manual Installation

### Python Linting Tools

```bash
apk add py3-black py3-flake8 py3-codespell
```

### YAML/Markdown Tools

```bash
apk add py3-yamllint
# markdownlint requires npm (not available in HAOS)
```

### GitHub CLI

```bash
# Download and install
wget https://github.com/cli/cli/releases/download/v2.40.1/gh_2.40.1_linux_amd64.tar.gz
tar -xzf gh_2.40.1_linux_amd64.tar.gz
mv gh_2.40.1_linux_amd64/bin/gh /usr/local/bin/
chmod +x /usr/local/bin/gh
```

### todo.ai

```bash
curl -o /usr/local/bin/todo.ai https://raw.githubusercontent.com/fxstein/todo.ai/main/todo.ai
chmod +x /usr/local/bin/todo.ai
```

## Common Development Tasks

### Update Main Branch

```bash
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
```

### Sync Feature Branch

```bash
git checkout feature/my-feature
git merge main
```

### View Sensor Data

```bash
# List all solax entities
ha-api --domain sensor --entities | grep solax

# Get sensor value
ha-api --entity sensor.solax_1_pv_power

# Watch sensor updates
watch -n 5 'ha-api --entity sensor.solax_1_pv_power'
```

### Check Integration Status

```bash
# List config entries
ha-api --domain homeassistant --list-config-entries

# View integration info
ha info | grep solax
```

## Best Practices

### Development Cycle

1. **Small changes** - Iterate quickly
2. **Test locally** - Reload integration after each change
3. **Check logs** - Ensure no errors
4. **Commit often** - Small, focused commits
5. **Push regularly** - Get automated feedback early

### Code Quality

- ✅ Let Black handle formatting (don't manually format)
- ✅ Run `./scripts/lint.sh` before pushing (optional)
- ✅ Check GitHub Actions results after push
- ✅ Fix any issues flagged by automated checks

### Performance

- ✅ Keep hot path code fast (< 1 µs per sensor)
- ✅ Measure before optimizing (see [performance-testing.md](performance-testing.md))
- ✅ Cache function references (30% improvement)
- ✅ Remove measurement code before committing

## Resources

- **Coding Standards:** [coding-standards.md](coding-standards.md)
- **Contribution Workflow:** [contribution-workflow.md](contribution-workflow.md)
- **Performance Testing:** [performance-testing.md](performance-testing.md)
- **Plugin Validation:** [plugin-validation-function.md](plugin-validation-function.md)

## Summary

**Quick Start:**
1. Run `./scripts/install-dependencies.zsh`
2. Clone your fork to `/config/custom_components/solax_modbus_dev`
3. Create feature branch
4. Edit → Test → Commit → Push
5. Create PR

**Remember:**
- Automated tools handle formatting
- Test with hot reload (no restart needed)
- GitHub Actions provide feedback automatically
- Focus on code quality, not style! 🚀

