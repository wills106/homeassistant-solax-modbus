# Computed Sensor Readiness

Computed sensors have no Modbus register of their own. Their `value_function`
derives a value from other entries in the hub data dictionary. They must not be
evaluated during entity registration, because the first successful Modbus poll
may not have populated their inputs yet.

## Shared evaluation path

All register-less computed sensors are evaluated by
`SolaXModbusHub.evaluate_computed_sensor`. The evaluator:

- leaves a new entity unknown until its readiness contract is satisfied;
- accepts numeric zero and boolean false as valid inputs;
- rejects missing, `None`, NaN and infinite required inputs;
- preserves the last coherent value briefly when inputs/results are invalid;
- expires each measured input after three of its own configured intervals,
  including complete polling silence;
- requires every mandatory input to have an accepted, unexpired observation;
  dependencies may span device groups and independently configured intervals;
- permits bounded reuse of both raw inputs and computed intermediates, without
  treating the reuse as a new source observation;
- prevents a stale computed intermediate from releasing a downstream calculation;
- resolves computed-on-computed chains in dependency order.

The Energy Dashboard refresh path uses the same evaluator. It resolves the
actual source selected by the parallel setting, rather than accepting an
unrelated alternative. Every contributing hub supplies its own accepted,
bounded-age interval snapshots. Missing contributors yield `None` (HA unknown),
never a partial sum or zero. A topology refresh does not authorize computing
from an unvalidated cache.

## Description contract

Every description with `register < 0` and a `value_function` must explicitly
declare `depends_on`, even when the list is empty.

```python
BaseModbusSensorEntityDescription(
    key="pv_power",
    value_function=value_function_pv_power,
    depends_on=["pv_voltage", "pv_current"],
)
```

The available fields are:

- `depends_on`: every applicable key is required. An empty list means there
  are no readiness inputs; it is appropriate for a true constant or a value
  obtained from external state captured by the function.
- `depends_on_any`: each tuple is an alternative group. At least one
  applicable, valid and fresh key from every group is required.
- `optional_depends_on`: only valid, accepted values are passed to the function;
  invalid or stale values are removed from its private input dictionary.
  Alternatives are filtered identically, so a stale preferred value cannot
  shadow a fresh fallback. When a sensor has no mandatory or alternative inputs, an
  applicable optional input must be fresh to trigger recalculation.
- `readiness_validator`: optional domain-specific validation after the generic
  checks. It receives the source data dictionary and must return a boolean.
- `dependency_selector`: select `(required, optional)` sets from filtered data
  and applicable keys, replacing the static required/alternative gate. Static
  declarations still list every possible input for ordering and polling;
  unused inputs are removed before calculation.
- `recompute_each_poll`: use only for time-dependent calculations or values
  maintained by local control code, whose result can change without a Modbus
  dependency becoming fresh.
- `allow_none`: explicitly publish `None` as unknown, for example when local
  remote control is inactive. Use an empty dependency contract for identity
  values maintained by local code, not a self-reference requiring numeric input.

An optional correction requiring several measurements must explicitly check
that its complete correction input set survived filtering. Otherwise use the
documented base calculation, not zero-filled partial correction terms.

## Age and interval boundaries

The availability timer uses the absolute deadline inherited from accepted
inputs. Publication, invalid or discarded groups cannot renew it. Expiry
preserves the last numeric value internally but exposes `unavailable`; a later
accepted zero or nonzero measurement restores availability. The timer is
cancelled on entity removal. A result inherits the earliest deadline of its
accepted inputs, each bounded by three configured polling intervals,
not the communication-failure slowdown interval.

An explicit empty input contract with no additional readiness or source mapping
has no measured-input expiry; see `is_inputless_computed_sensor`. Communication
diagnostics are published separately after poll accounting and remain available
during slowdown or polling silence.

Cross-interval input reuse is deliberately narrower than arbitrary cache use:
only accepted, unexpired raw or computed dependencies qualify; invalid inputs
or failed intermediates still block the calculation. At least one
declared input must be freshly observed for an ordinary calculation. The
latest completed snapshot replaces the previous snapshot even on partial or
discarded reads, and rebuilding polling blocks clears all snapshots. Inputs
from independently scheduled groups/hubs are bounded in age, not simultaneous
physical measurements. No data dictionary or freshness set is modified by the
input overlay. `force=True` is not used to accept cross-hub cache data.

Dependencies not present in the active inverter's description set or data are
ignored. This lets one description cover model variants while still requiring
every input that is applicable to the detected inverter.

## Observation identity and final publication

`InputObservation` records monotonic measurement time, value, absolute deadline
and input references. Each raw read creates a distinct observation, including an
unchanged value. Reusing the same selected observations avoids duplicate
calculations. Group observations are staged until validation; rejected groups
invalidate attempted inputs. Block rebuilds also clear observation records and
cached controller payloads.

Internal computations remain available before `readFollowUp`. Final computed
callbacks publish once per key after all interval groups finish. Reconciliation
checks committed inputs so a trailing failed group cannot publish an obsolete
result or renew its lease. Unchanged topology may reuse accepted ED power
without changing its timestamp or deadline; Master topology requires PM data.

## Riemann energy integrals

Integrals consume completed source-hub snapshots, including failed/discarded
intervals. Power must be finite numeric data before and after filtering; zero
is valid, while booleans and numeric strings are rejected. Integration uses the
selected source's monotonic observation time. Duplicate callbacks and unrelated
intervals cannot add energy or renew availability.

Invalid, missing or expired power preserves the total but breaks the integration
interval. The first valid sample after a gap establishes a baseline; the next
resumes integration. A timer and sample-time gap check cover polling silence and
delayed callbacks. Source/topology changes and dashboard reactivation also break
the interval; cached power from before that boundary cannot establish a baseline.
Power and topology deadlines are both enforced. Missing energy is not backfilled,
and restarting never integrates downtime.

Persist the unrounded total and local reset date through
`RestoreEntity.extra_restore_state_data`: ordinary attributes are omitted when
HA publishes an unavailable entity. Legacy numeric restored states remain
supported. Cold startup without a saved total stays unknown until valid power;
the existing local-midnight reset remains. Round only published energy to three
decimal places, including restored values before the first accepted sample.

## SolaX VPP lifecycle and cadence

Autorepeat runs after all interval device groups. For SolaX, `autorepeat_cadence`
selects the shortest configured raw power interval; settings, topology and BMS
limits affect validity. `FIRST` and `LOOP` share `compute_autorepeat_payload`.
Filters advance once on an owner poll when relevant observations or requests
change. Slower polls supply inputs for the next owner poll; otherwise send the
validated keepalive payload without advancing filters or renewing input deadlines.
Other plugins retain one autorepeat call per interval refresh.

Both SolaX buttons declare fixed inputs across all sub-modes: `depends_on` is
mandatory, `autorepeat_dependencies` is required when installed, and
`autorepeat_parallel_dependencies` defines Free/Master inputs. Free needs no PM
data. `autorepeat_optional_dependencies` contains meter/phase corrections and
total/individual BMS power limits: only valid, unexpired accepted values reach
the controller. Unread or invalid optional inputs are omitted even when an old
value remains in the shared cache. Readiness depends on accepted observations,
without consulting the entity registry or inferring installed battery channels.
Mode 8 keeps the model's total charge-current readback required, so a missing
required current cannot reach the charge helper's guessed 20 A default. The
unchanged helper retains its precedence: positive total power, sum of available
individual BMS limits, then total current. A partial BMS sum remains supported;
an omitted expired channel does not stop control or contribute its old value.
Used optional observations participate in keepalive caching; expiry/removal and
recovery invalidate an old payload without renewing deadlines.
Numeric inputs and computed leaves must be finite; zero
is valid, booleans and strings are rejected. Local requests (`autorepeat_control`)
and filter state remain separate. Regulator equations are unchanged.

Explicit disable, expiry and invalid required inputs invoke `POST`, including on
slower or skipped/failed polls. Serialize lifecycle writes through transport
acknowledgement and retry failed cleanup without rerunning filters. Mode 8 clears
local current setpoints to `None`; recovered inputs require a new trigger.
Device timeout covers loss of communication. Unsupported topology follows the
existing disable/no-op path; Slave modes 1-7 with empty writes remain a no-op.

Profile selectors use a positive valid Gen5 total SoC or require all applicable
battery SoCs. Weighting uses metadata only when both SoCs and capacities are
positive.
BMS selectors use the model's voltage names and dedicated current, or shared
current with an installed peer voltage. Unused fallbacks do not shorten deadlines.
Phase sums require every applicable phase.

## Contributor checks

When adding or changing a computed sensor:

1. Declare every input read by the value function as required, alternative or
   optional. Do not rely on `dict.get(..., 0)` for startup readiness.
2. Use a readiness validator for domain rules; do not treat zero as missing in
   the shared evaluator.
3. Add focused tests for cold start, legitimate zero, invalid input and partial
   polling where relevant.
4. Keep direct sensor `value_function` calls out of the entity platform. The
   structural tests enforce both the explicit contract and shared startup path.
5. For integrals, also test no-callback expiry, duplicate callbacks, source/topology
   changes and restart while unavailable. Check HA publication and retained
   totals as well as arithmetic; use tolerant comparisons for calculated durations.
