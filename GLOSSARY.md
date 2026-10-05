# Harness Kit

## Language

**Install plan**:
The complete ordered work for one selected harness scope.
_Avoid_: Deployment plan, Execution plan

**Operational policy**:
The checked-in defaults for how agents run, optionally specialized by a machine-specific policy. Concrete per-agent, per-harness model and reasoning-effort defaults belong here; model tiers and separate Pi provider routing are not part of this model.
_Avoid_: Agent metadata

**Agent definition**:
The authored identity, instructions, and allowed tool capabilities of an agent, independent of machine-specific execution choices. Harness adapters translate capability names but cannot change which capabilities an agent has.
_Avoid_: Agent policy
