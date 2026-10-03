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
- `dependency_selector`: optional selection of `(required, optional)` key sets
  from the filtered input dictionary and applicable keys. Static declarations
  still list every possible input for ordering and polling. A selected branch
  replaces the static required/alternative gate, and unused inputs are removed
  before the value function runs. The accepted computation records the inputs
  it used, including optional inputs, for subsequent invalidation and expiry.
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
inputs, not the time of publication. Invalid or discarded groups cannot renew it. Expiry
preserves the last numeric value internally but exposes `unavailable`; a later
accepted zero or nonzero measurement restores availability. The timer is
cancelled on entity removal. Its limit is three times the slowest configured
raw dependency interval (the default interval for local/no-input descriptions),
not the communication-failure slowdown interval.

The three communication diagnostics are an explicit exception: they describe
the local poll outcome, not a measured input. The hub publishes them after
recording each completed poll, outside the computed evaluator and its expiry
timer. They therefore remain available during slowdown/polling silence rather
than hiding `Degraded` or `Offline`. This exception does not disable expiry for
other time-dependent or dependency-free computed sensors.

Per-key observations distinguish a key not read by a device group from an
attempted but failed, rejected or invalid read. A computed result inherits the
earliest deadline of the accepted inputs used in its calculation; required
dependencies are also checked individually on reuse. A slow input cannot keep
an expired fast input valid. At least one declared input must be freshly
observed for an ordinary calculation. Reading an unchanged numeric value is a
new observation; reading another group is not. Staged observations become
visible to other hubs only after group validation. Rebuilding polling blocks
clears all snapshots and observation records. Inputs
from independently scheduled groups/hubs are bounded in age, not simultaneous
physical measurements. No data dictionary or freshness set is modified by the
input overlay. `force=True` is not used to accept cross-hub cache data.

For Energy Dashboard mappings, validate topology before selecting Free/Master/
Slave input. Topology changes switch the source; unchanged topology may reuse
an accepted computed power without changing its timestamp or deadline. Every
contributing hub must supply valid data. `None` publishes HA `unknown`, while
expiry publishes `unavailable`; repeated unknown publications do not extend the
last valid lease. Mapping/filter functions and entity IDs remain unchanged.

Dependencies not present in the active inverter's description set or data are
ignored. This lets one description cover model variants while still requiring
every input that is applicable to the detected inverter.

## Riemann energy integrals

Riemann energy sensors consume completed, accepted source-hub snapshots rather
than `hub.data` or a cached dashboard mirror. Their callbacks run after the
interval snapshot is published, including failed and discarded intervals.
They validate finite numeric power before and after filtering; zero remains
valid, while booleans and numeric strings are not power measurements.

Integration uses the monotonic observation time of the selected source, not
callback time. Duplicate callbacks or overlays from unrelated scan intervals
cannot re-date a sample, accumulate energy or renew its availability lease.
A newer invalid source interval cannot fall back to an older computed result
from another interval. Source selection and age limits use the actual source
hub, including slave PV variants and parallel-mode mappings.

Invalid/missing/stale power makes the integral unavailable while preserving its
total and breaking the integration interval. The first valid sample after a gap
only establishes a new baseline; the next valid sample resumes integration.
An expiry timer handles complete polling silence, and a sample-time gap check
also protects against delayed timer delivery. Source hub/key changes and
dashboard reactivation likewise break the interval. Missing energy is not
estimated or backfilled: the integral is incomplete across the outage.

Integral expiry and the gap check use the selected source's inherited absolute
deadline, so a mixed-interval computed power cannot bridge expiry of its faster
required input while a slower dependency remains valid.
Mappings with a topology input also inherit that input's deadline. A valid
refresh of unchanged topology renews only the topology component; it never
re-dates power. After topology expiry, a source change or reactivation, cached
power from before that boundary cannot anchor a new integration interval.

The accumulated total and its local reset date are saved through HA's
`RestoreEntity.extra_restore_state_data`, independently of visible availability.
HA omits ordinary extra attributes when an entity is unavailable, so those
attributes alone cannot preserve the total through a restart during an outage.
Legacy numeric restored states remain supported. Cold startup without a saved
total stays unknown until a valid power sample; restart never integrates its
downtime, and the existing local-midnight reset remains in effect.
The accumulator and extra restore data keep the unrounded total. Published
energy uses three decimal places, including the restored-value fallback before
the first accepted power sample. Publication never rounds the stored total.

## Observation identity and final publication

`InputObservation` is an immutable sample containing its measurement timestamp,
value, absolute deadline and references to the inputs used in its calculation.
Each input reference identifies its hub, key and observation. Every raw read
creates a distinct object, including a read with the same numeric value and
timestamp. Equality is by identity, so neither numeric equality nor clock
resolution can collapse a real measurement into a repeated publication.

The observations alone carry freshness, selected dependencies and deduplication
state; there are no separate generation/signature/dependency registries to
commit. A group's observations are staged together until validation accepts
them. A rejected group publishes none of them and invalidates its attempted
inputs. Rebuild clears observations, so retained
numbers cannot authorize a new calculation.

A computed sensor is evaluated again when its selected input observations
change. Reusing the same input objects performs no duplicate calculation.
Time-dependent/local descriptions retain `recompute_each_poll`.
Internal computations remain available before `readFollowUp`, and a new input
in another device group can require another internal computation. Final
computed callbacks run once per key at the end of the interval refresh, after
accepted group commits. A final reconciliation under the poll-data lock
checks the latest committed inputs: a trailing failed or discarded group
cannot publish an earlier ED result or renew an ordinary computed lease.
ED also deduplicates unchanged selected source
observations, including each contributing hub and topology. Riemann callbacks
continue to consume the completed source snapshot, including invalid outcomes.
Known Master topology requires the declared PM source, including before its
first successful read. Unknown topology is unavailable; models without a
topology input retain their default Free source selection.

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
5. For energy integrals, test missing data, no-callback expiry, source-hub
   selection, duplicate callbacks and restart while unavailable. Assert both
   HA publication and preserved restore data, not just internal arithmetic.
   Use controlled integer and fractional clock origins. Compare calculated
   durations with a tight tolerance, but compare saved totals and retained
   observation timestamps exactly against their original values.
