# Phase B Implementation Status

## Progress Summary

**Completed:** 1/17 files  
**F405 Errors:** 8,236 remaining (160 fixed)  
**Tests:** ✅ All 61 tests passing

## Files Processed

### ✅ plugin_solax_ev_charger.py (Smallest - 14 symbols)
- Removed star import
- Added 17 explicit imports from const.py
- Added 8 HA unit imports
- Added 3 value functions
- Tests passing

## Remaining Files (by complexity)

1. plugin_solis_old.py (14 symbols)
2. plugin_srne.py (15 symbols)
3. plugin_Enertech.py (18 symbols)
4. plugin_alphaess.py (19 symbols)
5. plugin_solax_a1j1.py (19 symbols)
6. plugin_swatten.py (19 symbols)
7. plugin_sofar_old.py (20 symbols)
8. plugin_solax_mega_forth.py (20 symbols)
9. plugin_solinteg.py (22 symbols)
10. plugin_solis_fb00.py (22 symbols)
11. plugin_solis.py (23 symbols)
12. plugin_sunway.py (25 symbols)
13. plugin_growatt.py (27 symbols)
14. plugin_solax_lv.py (27 symbols)
15. plugin_sofar.py (29 symbols)
16. plugin_solax.py (39 symbols) - Largest

## Tooling Created

- ✅ `scripts/analyze_star_imports.py` - Analyzes symbol usage across files
- ✅ `scripts/generate_imports.py` - Generates import statements for a file
- ✅ Manual process validated and working

## Next Steps (After Review)

1. **Automate Processing:** Create script to batch-process remaining files
2. **Process Files:** Complete remaining 16 files using proven pattern
3. **Enable Import Sorting:** Update pyproject.toml to enable `select = ["I"]`
4. **Final Testing:** Verify F405 errors = 0, all tests pass
5. **Documentation:** Update design doc with actual implementation details

## Known Requirements per File

Each file typically needs:
- Base entity description classes (Button, Number, Select, Sensor, Switch)
- Register type constants (REGISTER_U16, REG_HOLDING, etc.)
- HA imports (UnitOfPower, EntityCategory, SensorDeviceClass, etc.)
- Value functions (varies by file)
- Plugin base class

## Estimated Completion

- **Per File:** ~5-10 minutes (find symbols, update imports, test)
- **Remaining 16 files:** ~2-3 hours with automation
- **Import sorting:** ~30 minutes (enable, test, fix any issues)
- **Total:** ~3-4 hours to complete Phase B

## Validation Strategy

After each file:
1. Run `pytest tests/unit/test_imports.py -k <file>` 
2. Verify no NameErrors
3. Commit with descriptive message
4. Check F405 error count reduction

Final validation:
1. `uv run ruff check --select F405` → 0 errors
2. `uv run pytest` → All passing
3. Enable import sorting and run `ruff check --select I --fix`
4. Verify tests still pass
