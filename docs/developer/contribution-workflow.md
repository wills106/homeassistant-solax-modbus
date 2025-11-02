# Contribution Workflow

How to contribute to the SolaX Modbus integration.

## Quick Start

1. **Fork** the repository on GitHub
2. **Clone** your fork locally
3. **Create** a feature branch
4. **Make** your changes
5. **Test** with real hardware (if possible)
6. **Push** to your fork
7. **Create** a pull request

**That's it!** Automated checks will run and provide feedback.

## Detailed Workflow

### 1. Fork and Clone

```bash
# Fork on GitHub: https://github.com/wills106/homeassistant-solax-modbus

# Clone your fork
git clone https://github.com/YOUR_USERNAME/homeassistant-solax-modbus.git
cd homeassistant-solax-modbus

# Add upstream remote
git remote add upstream https://github.com/wills106/homeassistant-solax-modbus.git
```

### 2. Create Feature Branch

```bash
# Update main branch
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/my-awesome-feature

# Or for bug fixes:
git checkout -b fix/bug-description
```

### 3. Make Changes

**Edit code:**
- Keep framework generic (no inverter-specific code in `__init__.py`)
- Put inverter-specific code in plugins
- Follow existing patterns
- Don't worry about formatting (Black handles it)

**Optional - check locally:**
```bash
./scripts/lint.sh    # Check for issues
./scripts/format.sh  # Auto-fix formatting
```

**Commit often:**
```bash
git add .
git commit -m "feat: Add awesome feature

Detailed description of what and why.
"
```

### 4. Test Your Changes

**Minimum testing:**
- ✅ Integration loads without errors
- ✅ No errors in Home Assistant logs
- ✅ Existing functionality works

**Better testing:**
- ✅ Test with real hardware
- ✅ Test in parallel mode (if applicable)
- ✅ Test edge cases

**Include in PR:**
- Describe your testing
- Share log excerpts
- Include screenshots if relevant

### 5. Push to Your Fork

```bash
git push origin feature/my-awesome-feature
```

### 6. Create Pull Request

**On GitHub:**
1. Go to your fork
2. Click "Pull Request"
3. Select your feature branch
4. Fill out the PR template
5. **Mark as draft** if work in progress
6. Click "Create Pull Request"

**PR Checklist:**
- [ ] Clear description of changes
- [ ] Testing details included
- [ ] Documentation updated (if needed)
- [ ] Screenshots/logs (if relevant)

### 7. Respond to Feedback

**Automated checks:**
- GitHub Actions will run automatically
- Informational only - won't block your PR
- Fix any issues flagged (or discuss if false positives)

**Code review:**
- Maintainers will review your PR
- Respond to comments and suggestions
- Make requested changes
- Push updates to same branch (PR updates automatically)

**Iterate:**
```bash
# Make requested changes
git add .
git commit -m "Address review feedback"
git push origin feature/my-awesome-feature
```

## Syncing with Upstream

**Keep your fork up-to-date:**

```bash
# Update main branch
git checkout main
git fetch upstream
git merge upstream/main
git push origin main

# Update feature branch
git checkout feature/my-awesome-feature
git merge main  # Or rebase: git rebase main
```

## Common Scenarios

### Adding New Sensor

1. Add sensor definition to plugin file
2. Test that sensor appears in Home Assistant
3. Verify sensor updates correctly
4. Document in PR what the sensor provides

### Fixing Bug

1. Identify root cause
2. Create minimal fix
3. Test that bug is fixed
4. Test that existing functionality still works
5. Describe bug and fix in PR

### Adding Documentation

1. Place in appropriate `docs/` directory
2. Use clear, concise language
3. Include examples
4. Link to related documentation

### Performance Optimization

1. **Measure first** (see [performance-testing.md](performance-testing.md))
2. Identify bottleneck
3. Implement optimization
4. **Measure again** to confirm improvement
5. Include before/after metrics in PR
6. **Remove measurement code** before committing!

## Development Tools

### Optional Tools for Local Development

Install these if you want local linting (not required):

```bash
# Python tools
pip install black flake8

# YAML/Markdown/Spelling
pip install yamllint markdownlint-cli codespell

# Or use system package manager (e.g., for Alpine Linux)
apk add py3-black py3-flake8 py3-yamllint py3-codespell
```

**Or just rely on GitHub Actions** - they'll check everything automatically!

### Pre-commit Hooks (Optional)

If you want automatic local checks before commit:

```bash
pip install pre-commit
pre-commit install
```

Now checks run automatically on `git commit`.

**To skip (if needed):**
```bash
git commit --no-verify
```

## Tips for Contributors

### First-Time Contributors

- ✅ Start with documentation improvements (easier)
- ✅ Small, focused PRs are better than large ones
- ✅ Ask questions in PR discussions
- ✅ Draft PRs welcome for early feedback

### Regular Contributors

- ✅ Create draft PRs early
- ✅ Test on real hardware when possible
- ✅ Update documentation with code changes
- ✅ Consider performance impact for hot paths

### Maintainers

- ✅ Review PRs promptly
- ✅ Be constructive in feedback
- ✅ Help new contributors
- ✅ Keep CI/CD informational (not blocking)

## What NOT to Do

- ❌ Don't commit code with errors (test first!)
- ❌ Don't bypass git hooks without reason (`--no-verify`)
- ❌ Don't include credentials in code/commits
- ❌ Don't make massive PRs (split into smaller ones)
- ❌ Don't add inverter-specific code to framework
- ❌ Don't commit performance measurement code

## Getting Help

- **Questions:** Open an issue or discussion
- **Bug reports:** Use bug report template
- **Feature ideas:** Use feature request template
- **PR feedback:** Maintainers will help in PR comments

## Summary

**Simple workflow:**
1. Fork → Branch → Code → Test → Push → PR
2. Automated checks provide feedback
3. Respond to review comments
4. Merge when approved

**Remember:** Don't worry about formatting - it's automated! Focus on writing good code and testing it. 🚀

