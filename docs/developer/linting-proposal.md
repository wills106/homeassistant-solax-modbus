# Code Linting and Formatting Proposal

**Task:** #157.1 - Set up automatic code linting  
**Date:** October 30, 2025

## Overview

Establish automated code linting and formatting to maintain consistent code quality across multiple developers.

## Proposed Tools

### Python Code

**Black** (Code Formatter)
- Auto-formats Python code to consistent style
- Minimal configuration needed
- Widely adopted standard
- Non-negotiable formatting rules

**Flake8** (Style Checker)
- PEP 8 compliance checking
- Error and code smell detection
- Configurable rules

**Pylint** (Static Analyzer)
- Deferred for future consideration
- More opinionated, deeper analysis
- Can be added later after Black/Flake8 are stable

**Decision:** Start with **Black + Flake8** only.

### YAML Files

**yamllint**
- YAML syntax validation
- Style consistency checking
- Already used in Home Assistant ecosystem

### JSON Files

**jsonlint** or built-in JSON validation
- JSON syntax validation
- Format checking

### Markdown Files

**markdownlint**
- Markdown style consistency
- Document formatting standards

### Spelling

**codespell**
- Catch common spelling mistakes
- Technical term dictionary
- Low false-positive rate

**typos** (Alternative)
- Fast Rust-based spell checker
- Good for CI/CD pipelines

**Recommendation:** **codespell** (already common in Python projects)

## Configuration Files

### .editorconfig

```ini
# EditorConfig for consistent IDE settings
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
indent_style = space
indent_size = 4
max_line_length = 120

[*.{yaml,yml}]
indent_style = space
indent_size = 2

[*.{json,md}]
indent_style = space
indent_size = 2

[Makefile]
indent_style = tab
```

### pyproject.toml (Black configuration)

```toml
[tool.black]
line-length = 120
target-version = ['py311']
include = '\.pyi?$'
exclude = '''
/(
    \.git
  | \.hg
  | \.mypy_cache
  | \.tox
  | \.venv
  | _build
  | buck-out
  | build
  | dist
)/
'''
```

### .flake8 (Flake8 configuration)

```ini
[flake8]
max-line-length = 120
exclude = 
    .git,
    __pycache__,
    .venv,
    build,
    dist
ignore = 
    E203,  # Whitespace before ':' (conflicts with Black)
    E501,  # Line too long (Black handles this)
    W503,  # Line break before binary operator (Black handles this)
```

### .yamllint

```yaml
extends: default

rules:
  line-length:
    max: 120
    level: warning
  indentation:
    spaces: 2
  comments:
    min-spaces-from-content: 1
```

### .markdownlint.json

```json
{
  "default": true,
  "MD013": false,
  "MD033": false,
  "MD041": false
}
```

### .codespellrc

```ini
[codespell]
skip = .git,*.pyc,*.pyo,__pycache__
ignore-words-list = hass,homeassistant
```

## GitHub Actions Workflow

### .github/workflows/lint.yml

```yaml
name: Lint

on:
  push:
  pull_request:

jobs:
  black:
    name: Black
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: psf/black@stable
        with:
          options: "--check --diff"
          src: "./custom_components"

  flake8:
    name: Flake8
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install flake8
      - run: flake8 custom_components/

  yamllint:
    name: YAML Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install yamllint
      - run: yamllint .

  markdownlint:
    name: Markdown Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DavidAnson/markdownlint-cli2-action@v16
        with:
          globs: "**/*.md"

  codespell:
    name: Codespell
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: codespell-project/actions-codespell@v2
```

## Pre-commit Hooks

### .pre-commit-config.yaml

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.10.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/flake8
    rev: 7.1.1
    hooks:
      - id: flake8

  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks:
      - id: yamllint

  - repo: https://github.com/igorshubovych/markdownlint-cli
    rev: v0.42.0
    hooks:
      - id: markdownlint

  - repo: https://github.com/codespell-project/codespell
    rev: v2.3.0
    hooks:
      - id: codespell
        args: [--ignore-words-list=hass]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-added-large-files
```

## Manual Lint Script

### scripts/lint.sh

```bash
#!/bin/bash
# Manual linting script - run checks without committing

echo "🔍 Running Black..."
black --check --diff custom_components/

echo ""
echo "🔍 Running Flake8..."
flake8 custom_components/

echo ""
echo "🔍 Running yamllint..."
yamllint .

echo ""
echo "🔍 Running markdownlint..."
markdownlint "**/*.md"

echo ""
echo "🔍 Running codespell..."
codespell

echo ""
echo "✅ All linting checks complete!"
```

### scripts/format.sh

```bash
#!/bin/bash
# Auto-fix formatting issues

echo "🔧 Running Black (auto-fix)..."
black custom_components/

echo ""
echo "🔧 Running codespell (auto-fix)..."
codespell --write-changes

echo ""
echo "✅ Auto-formatting complete!"
echo "💡 Run ./scripts/lint.sh to verify"
```

## Implementation Plan

### Phase 1: Setup and Configuration
1. Add `.editorconfig`
2. Add `pyproject.toml` (Black config, line-length=120)
3. Add `.flake8` (lenient configuration)
4. Add `.yamllint`
5. Add `.markdownlint.json`
6. Add `.codespellrc`
7. Create `scripts/lint.sh` (manual check script)
8. Create `scripts/format.sh` (auto-fix script)

**Status:** Linting is **optional** at this phase

### Phase 2: Test on Subset
1. Apply Black to `__init__.py` only
2. Apply Black to `plugin_solax.py` only
3. Fix flake8 issues in these files (lenient rules)
4. Test that integration still works
5. Commit formatted subset

**Scope:** Limited to 2 core files for initial validation

### Phase 3: GitHub Actions (Optional)
1. Add `.github/workflows/lint.yml`
2. Set to informational only (won't block PRs)
3. Test on small PR
4. Gather feedback

**Enforcement:** Warnings only, not required

### Phase 4: Expand Scope
1. Apply to remaining plugin files (plugin_growatt.py, etc.)
2. Fix issues incrementally
3. Test each plugin separately

**Track:** Completion % per plugin

### Phase 5: Pre-commit Hooks (Optional)
1. Add `.pre-commit-config.yaml`
2. Document installation for contributors
3. Keep optional (not enforced)

### Phase 6: Documentation Files
1. Apply markdownlint to docs/
2. Fix formatting issues
3. Apply codespell

### Phase 7: Make Required (Future)
1. Evaluate feedback from Phases 1-6
2. Decide if linting should become required
3. Update PR template if making required
4. Add to contribution guidelines

## Rollout Strategy

### Conservative Approach (Recommended)

1. **Start with formatting only** (Black, yamllint)
   - Less likely to find issues
   - Easy to auto-fix
   - Quick wins

2. **Add style checks gradually** (Flake8, markdownlint)
   - May require code changes
   - Review and fix incrementally

3. **Add static analysis last** (Pylint)
   - Most opinionated
   - May disagree with some choices
   - Optional/future consideration

### Aggressive Approach

1. Add all tools at once
2. Fix all issues in one large PR
3. Pros: Done quickly
4. Cons: Large changeset, potential for issues

**Recommendation:** Conservative approach to avoid disrupting development

## Expected Issues

### Python Code (plugin_solax.py ~9,700 lines)

**Black formatting:**
- Estimate: 50-200 lines affected
- Impact: Whitespace, line breaks
- Risk: Low (Black is safe)

**Flake8:**
- Estimate: 100-500 issues
- Common: Line length, unused imports, undefined names
- Risk: Medium (may require code review)

### YAML Files (docs/*.md)

**yamllint:**
- Estimate: 10-50 issues
- Common: Indentation, line length
- Risk: Low

### Markdown Files

**markdownlint:**
- Estimate: 20-100 issues
- Common: Line length, heading styles
- Risk: Low (documentation only)

### Spelling

**codespell:**
- Estimate: 10-30 issues
- Common: Technical terms, variable names
- Risk: Low (can whitelist terms)

## Benefits

### Code Quality
- ✅ Consistent style across all files
- ✅ Catch common errors early
- ✅ Improve readability

### Developer Experience
- ✅ Clear standards for contributors
- ✅ Automated feedback in PRs
- ✅ Less manual code review time

### Maintenance
- ✅ Easier code reviews
- ✅ Fewer style-related discussions
- ✅ Professional project appearance

## Next Steps

1. Review this proposal
2. Decide on tool selection
3. Create configuration files
4. Test on small subset of code
5. Proceed with full rollout

## Decisions Made

1. **Line length:** ✅ 120 characters
2. **Black:** ✅ Apply to subset first (__init__.py, plugin_solax.py)
3. **Flake8:** ✅ Start lenient, tighten gradually
4. **Pylint:** ✅ Deferred for future
5. **Enforcement:** ✅ Optional initially, evaluate after Phase 6

## Progress Tracking

Track completion via phases:
- [ ] Phase 1: Setup and Configuration
- [ ] Phase 2: Test on Subset (__init__.py, plugin_solax.py)
- [ ] Phase 3: GitHub Actions (optional, informational only)
- [ ] Phase 4: Expand Scope (remaining plugins)
- [ ] Phase 5: Pre-commit Hooks (optional)
- [ ] Phase 6: Documentation Files
- [ ] Phase 7: Evaluate for Required Status

