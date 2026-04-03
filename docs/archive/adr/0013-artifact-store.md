# ADR-0013: Artifact Store

- Status: Proposed
- Date: 2026-04-02
- Related: ADR-0003, ADR-0012

## Context

Job outputs are currently transmitted through a single channel: `git_ref`
(`branch:sha`) written into `JobCompletedData`. This works for git-native
code tasks but creates friction elsewhere:

1. **Non-git tasks have no output channel.** Any task whose output is not a
   git commit has nowhere to record what it produced. The event stream
   records that the job completed, but the physical output is invisible.

2. **Workspace is simultaneously execution environment and output medium.**
   The git working directory serves as both. If a container crashes after
   work is done but before publication, all output is lost. There is no
   durable intermediate state between "in progress" and "published to git
   remote".

3. **Event payloads are the wrong place for large objects.** Pasloe events
   carry structured metadata. Embedding file trees, reports, or binary
   snapshots in event data violates the separation between "what happened"
   (events) and "what was produced" (artifacts).

4. **Job-to-job data transfer is implicit.** When Trenni sets up a
   downstream job's workspace from a prior job's `git_ref`, the data
   dependency is encoded in Trenni's spawn expansion logic, not in a
   general-purpose reference.

The redesign exploration (see `docs/archive/event-artifact-runtime-redesign.md`
and `docs/archive/notes/2026-04-01-subagent-event-runtime-ideas.md`) identified artifact
storage as the core infrastructure gap. After discussion, the following
proposals from that exploration were evaluated and **rejected**:

- Splitting the four-stage pipeline into independent attempt types. The four
  stages are causally sequential; the ordering is a dependency chain, not a
  design choice.
- Event-driven stage selection within an attempt. The stage sequence is
  fixed; an event-driven kernel that always walks 1->2->3->4 adds overhead
  without flexibility.
- Evolvable decision policy in Trenni. Task decomposition belongs to the
  planner role; Trenni's state machine remains deterministic.
- TaskView as a control-plane concept distinct from context. The current
  context system already projects task state.

What remains is the artifact store: a content-addressed object store that
gives every job output a stable, referenceable identity independent of
workspace, git branch, or process memory.

This ADR defines the physical artifact layer only: object model, reference
format, store/materialize interface, and the copy-in/copy-out execution
contract. How the runtime consumes artifacts (relation semantics, Trenni
wiring, preparation/publication protocol changes) is deferred to a
subsequent runtime ADR.

## Decisions

### D1. Artifact store is a content-addressed object store

The artifact store holds immutable physical objects identified by content
digest. Once written, an object is never modified.

The store supports two object kinds in the first version:

- **blob** -- an immutable byte sequence.
- **tree** -- a directory snapshot.

What physical form a given producer's output takes (blob vs tree, compressed
vs raw) is decided by the producer and materializer, not by the store.
The store is agnostic to the content it holds.

A third kind, **bundle** (an ordered collection of refs with metadata), is
reserved for future use but not implemented in the first version. Bundle
requires its own canonical serialization format and digest rules to satisfy
the content-addressing guarantee; these will be defined when a concrete
use case arises.

### D2. ArtifactRef is a physical identifier only

```python
@dataclass(frozen=True)
class ArtifactRef:
    store_id: str          # backend-assigned content address
    object_kind: str       # "blob" | "tree" (first version)
    digest: str            # content hash (e.g. "sha256:<hex>")
    size_bytes: int
    encoding: str = ""     # optional: "raw", "gzip"
```

First version: `object_kind` accepts only `"blob"` and `"tree"`.
`"bundle"` is reserved for future use; the backend rejects it and no
producer emits it. When bundle support is added, the kind value is already
part of the schema and requires no migration.

ArtifactRef carries no semantic information. It does not know what the
content represents. The same ref can serve different purposes in different
contexts.

Reasons for keeping refs semantics-free:

1. The same physical object can serve different roles in different jobs.
2. Semantic labels evolve; physical identity should not drift with them.
3. Embedding semantics turns the ref into a half-state object.
4. What an object "is" is determined by whoever references it, not by the
   ref itself.

### D3. ArtifactBinding pairs a ref with a semantic role

```python
@dataclass
class ArtifactBinding:
    ref: ArtifactRef
    relation: str
    path: str = ""
    metadata: dict = field(default_factory=dict)
```

ArtifactBinding is the unit that appears in event payloads and job
configurations. It pairs a physical ref with a `relation` string that gives
the ref meaning in a specific context.

This ADR defines the `ArtifactBinding` structure but does **not** define a
standard set of relations. Relation semantics are a runtime protocol concern
and will be defined in a subsequent ADR that addresses how the four-stage
pipeline consumes and produces artifact bindings.

### D4. Canonical tree format for stable content addressing

For content addressing to hold (identical content -> identical digest),
tree snapshots must be produced deterministically. The canonical tree format
is a tar archive with the following normalization rules:

- Entries sorted lexicographically by full path.
- All timestamps set to Unix epoch (0).
- All uid/gid set to 0.
- Permission bits: only the executable/non-executable distinction is
  preserved (directories 0755, executable files 0755, non-executable files
  0644). All other mode bits (group, other, setuid, setgid, sticky) are
  stripped. **This is a lossy normalization.** The first version does not
  attempt full mode fidelity; fine-grained permission preservation can be
  added in a future revision if a concrete use case requires it.
- Symlinks preserved as-is (target path stored, not resolved).
- No extended headers, no device nodes.
- No default exclusion set. `store_tree` accepts an optional `exclude`
  parameter; when empty, the entire directory is stored faithfully. Callers
  (preparation_fn, publication_fn) decide what to exclude. The store itself
  is neutral.

The digest is computed over the resulting canonical tar byte stream. Two
calls to `store_tree` on directories with identical effective content
(after normalization and exclusion) produce identical `ArtifactRef` values.

Compression (gzip) is applied after canonicalization and recorded in
`ArtifactRef.encoding`. The digest is always computed over the uncompressed
canonical tar.

### D5. ArtifactBackend is an abstract interface

```python
class ArtifactBackend(Protocol):
    def store_blob(self, data: bytes) -> ArtifactRef: ...
    def store_tree(self, path: Path, *,
                   exclude: Sequence[str] = ()) -> ArtifactRef: ...
    def retrieve_blob(self, ref: ArtifactRef) -> bytes: ...
    def materialize_tree(self, ref: ArtifactRef,
                         target: Path) -> None: ...
    def exists(self, ref: ArtifactRef) -> bool: ...
```

Bundle operations (`store_bundle`, `resolve_bundle`) will be added when
bundle support is implemented.

First implementation: `LocalFSBackend`. Content-addressed directory layout:

```
<store_root>/
  blobs/
    sha256/<first-2-hex>/<full-hex>
  trees/
    sha256/<first-2-hex>/<full-hex>.tar       # or .tar.gz
```

Future backends (Pasloe HTTP, S3) implement the same protocol.

### D6. Copy-in / copy-out execution contract

The artifact store is the authoritative location for physical objects.
A job never works directly against the store. The execution contract is:

1. **Copy-in (preparation):** Input artifacts are copied out of the store
   and materialized into the job's ephemeral workspace. `materialize_tree`
   extracts a tree to a local path. `retrieve_blob` copies blob content to
   a local file. After materialization, the job's workspace is a private
   copy with no live reference to the store.

2. **Execution (interaction):** The job works exclusively against its
   private workspace copy. The store is not accessed during execution.

3. **Copy-out (publication):** After execution, the job stores its outputs
   as new artifacts via `store_tree` / `store_blob`. Each store call is
   atomic: content is written to a temporary location and renamed into the
   content-addressed path. The resulting `ArtifactRef` values are included
   in the job's completion event.

4. **No in-place mutation:** The store never exposes a mutable path. There
   is no "update" operation. Each store call produces a new immutable object.
   If a job's output is identical to a previous artifact, content addressing
   produces the same ref and no new bytes are written.

This contract ensures that:

- Job failures cannot corrupt stored artifacts.
- Concurrent jobs cannot interfere with each other's store writes.
- The store remains the single authoritative copy; workspaces are ephemeral.

### D7. Trenni owns the store instance; job containers must not modify it directly

Palimpsest runs inside Podman containers. The artifact store is a host-level
directory managed by Trenni:

```yaml
# trenni.yaml
artifact_store:
  backend: local_fs
  path: /var/lib/yoitsu/artifacts
```

**Structural constraint:** The job container must not be able to mutate
existing artifacts in the store. How this constraint is enforced is an
implementation concern (read-only mount + a write sidecar, a socket proxy,
a staging directory that Trenni promotes post-job, etc.) and is not
prescribed by this ADR. What this ADR requires is:

1. A job can **read** artifacts it has been given refs for (copy-in).
2. A job can **write** new artifacts (copy-out), but the write is mediated
   — the job does not place files directly into the content-addressed
   layout.
3. A job **cannot** overwrite or delete existing artifacts.

Trenni itself does not read or write artifact content. It reads
`ArtifactRef` values from event payloads and passes them through to
downstream job configurations.

### D8. git_ref is a compatibility receipt, not the canonical output

Under the new model, the canonical output of any job is a set of
`ArtifactBinding` values in the completion event. For jobs that also push to
a git remote, `git_ref` is an additional technical receipt recording the
remote-side coordinate — useful for external collaboration (PRs, CI) but
not the system's internal truth.

Migration path:

1. `JobCompletedData` gains an `artifact_bindings` field alongside the
   existing `git_ref`.
2. Roles that currently produce `git_ref` additionally store a tree artifact
   and include it in `artifact_bindings`.
3. Downstream consumers (Trenni spawn expansion, eval job setup) begin using
   `artifact_bindings` when present, falling back to `git_ref`.
4. Once all roles produce artifact bindings, `git_ref` is deprecated to a
   compatibility-only field.

No existing behavior breaks at any step.

### D9. Artifact lifecycle and retention

Artifacts are append-only. There is no deletion API in the first version.

- The store grows monotonically. At current scale (max_workers=4), storage
  growth is manageable.
- Future retention policy will use event references to determine
  reachability.
- Garbage collection is explicitly out of scope for this ADR.

## Implementation Components

### yoitsu-contracts

| File | Change |
|---|---|
| `artifact.py` (new) | `ArtifactRef`, `ArtifactBinding` frozen dataclasses |
| `artifact_backend.py` (new) | `ArtifactBackend` protocol definition |
| `local_fs_backend.py` (new) | `LocalFSBackend` implementation (canonical tar, atomic writes) |
| `events.py` | Add optional `artifact_bindings: list[ArtifactBinding]` to `JobCompletedData` |
| `config.py` | Add `ArtifactStoreConfig` dataclass |

### Trenni

| File | Change |
|---|---|
| `config.py` | Add `artifact_store` section to `TrenniConfig` |
| `runtime_builder.py` | Configure artifact store access for job container (mechanism per D7) |

### Palimpsest

| File | Change |
|---|---|
| `runner.py` | Instantiate `ArtifactBackend` from runtime configuration; attach to `RuntimeContext` |
| `runtime/context.py` | `RuntimeContext` gains `artifact_backend: ArtifactBackend \| None` field |

How preparation and publication stages consume the backend is deferred to a
subsequent runtime protocol ADR.

## Verification

1. `store_tree` on two directories with identical file content (but
   different mtime, uid, etc.) produces identical `ArtifactRef` values.
2. `store_tree` followed by `materialize_tree` to a new path reproduces file
   bytes, paths, symlinks, and the executable/non-executable distinction
   under the canonical normalization rules.
3. Two concurrent `store_tree` calls with identical content do not corrupt
   each other; both succeed and produce the same ref.
4. Two concurrent `store_tree` calls with different content produce
   different refs and both artifacts are intact.
5. `ArtifactRef` and `ArtifactBinding` round-trip through JSON serialization
   (Pasloe event payloads).
6. The job container can store and retrieve artifacts through the
   configured access mechanism.
7. The job container cannot overwrite or delete existing artifacts in the
   store.
8. Existing jobs that do not produce `artifact_bindings` continue to work
   via `git_ref` fallback.

## Scope Exclusions

- **Relation semantics and standard relation set.** Deferred to runtime
  protocol ADR.
- **Trenni spawn expansion changes for artifact forwarding.** Deferred to
  runtime protocol ADR.
- **Preparation and publication stage changes.** Deferred to runtime
  protocol ADR.
- **Garbage collection and retention policy.** First version is append-only.
- **Remote artifact backend (Pasloe HTTP, S3).** Interface is ready;
  implementation deferred.
- **Artifact store as independent service.** First version assumes
  single-host deployment, but the access mechanism is left open by D7.
- **Bundle object kind.** Reserved; canonical format and digest rules to be
  defined with first concrete use case.
- **Cross-host artifact transfer.** First version assumes single-host
  deployment.
- **Git pack as native artifact format.** Deferred.
- **Automatic git pull/push from artifact trees.** Deferred.

## Issues and Suggestions

### 1. Tree storage: tar vs manifest

Trees are stored as canonical tar archives. An alternative is manifest-based
trees (a JSON manifest pointing to individual blob refs, similar to git tree
objects). Manifests give finer-grained deduplication (shared files across
trees stored once) but add significant complexity. Tar is correct for the
first version; manifest-based trees can be introduced as a `LocalFSBackend`
optimization without changing `ArtifactRef` or `ArtifactBackend` signatures.

### 2. Digest algorithm

First version uses SHA-256. The digest field includes the algorithm prefix
(`sha256:<hex>`) so future migration to other algorithms requires no format
changes.

### 3. Large tree performance

Storing a full working directory as a tar can be large. Two mitigations
available without architecture changes:

- Callers pass an `exclude` list to `store_tree` to filter out regenerable
  content (dependency directories, build artifacts, etc.).
- Compression via `encoding=gzip` reduces storage footprint.

Both are caller decisions or `LocalFSBackend` implementation details, not
interface changes.

### 4. Concurrent write safety

Content addressing makes concurrent writes safe: different content produces
different paths; identical content produces the same path. The only race is
two writers targeting the same digest simultaneously. `LocalFSBackend`
handles this via write-to-temp-then-atomic-rename, which is safe on local
filesystems. The loser's rename overwrites with identical content.
