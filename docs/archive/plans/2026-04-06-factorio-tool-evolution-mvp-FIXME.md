# Task 1 & Task 2 Event Model Fix

## Problem
Task 2 passes `ToolRepetitionData` (payload model) directly to `gateway.emit()`, but EventGateway only accepts BaseEvent objects with event_type field.

## Solution
Task 1 needs to add BaseEvent wrappers for observation events.

## Changes Required

### In Task 1 (yoitsu-contracts/observation.py)

After Step 2 (adding ToolRepetitionData/ContextLateLookupData), add Step 3:

```python
from yoitsu_contracts.events import BaseEvent

class ObservationToolRepetitionEvent(BaseEvent):
    """Event wrapper for tool repetition observation."""
    event_type: str = OBSERVATION_TOOL_REPETITION
    data: ToolRepetitionData

class ObservationContextLateLookupEvent(BaseEvent):
    """Event wrapper for context late lookup observation."""
    event_type: str = OBSERVATION_CONTEXT_LATE_LOOKUP
    data: ContextLateLookupData
```

### In Task 2 (palimpsest/stages/interaction.py)

Change emit code from:
```python
event = ToolRepetitionData(...)
gateway.emit(event)
```

To:
```python
from yoitsu_contracts.observation import ObservationToolRepetitionEvent, ToolRepetitionData

event = ObservationToolRepetitionEvent(
    data=ToolRepetitionData(
        job_id=job_id,
        task_id=task_id,
        role=role_name,
        team=team,
        tool_name=r.tool_name,
        call_count=r.call_count,
        arg_pattern=r.arg_pattern,
        similarity=r.similarity,
    )
)
gateway.emit(event)
```

This ensures the event has event_type field and conforms to BaseEvent interface expected by EventGateway.emit().
