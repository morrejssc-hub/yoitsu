# TODO: Bundle Isolation

**Status:** In Progress
**Date:** 2026-04-07
**Scope:** Replace `team` and global evo fallback with `bundle` as the only isolation unit.

## Goal

Make `bundle` the single execution boundary across contracts, Trenni, Palimpsest, and `evo/`.

This means:

- no global `evo/roles`, `evo/tools`, or `evo/contexts` fallback
- no Trenni control-plane `team` semantics
- no ambiguous ownership for roles, tools, contexts, prompts, runtime config, or observations

## Target State

1. Directory layout is bundle-only:
   `evo/<bundle>/{roles,tools,contexts,prompts,lib,scripts,evolved}/`
2. Role, tool, and context resolution only look inside `evo/<bundle>/...`
3. `bundle` is an envelope field, not a role param
4. Trenni runtime and scheduling config are keyed by bundle
5. Observation, budget, concurrency, and generated artifacts all remain bundle-scoped
6. `default` is treated only as an ordinary bundle name, never as a global fallback

## Success Criteria

- A task with explicit `{bundle, role}` runs end-to-end without any global evo layer
- Empty or missing bundle does not resolve bundle resources implicitly
- `params` cannot shadow canonical fields like `role` or `bundle`
- `evo/factorio/` works as a self-contained bundle sample
- Tests assert bundle-only behavior and no global fallback

## Constraints

- `env_allowlist` replacement is explicit, not merged
- `pod_name` keeps three states: inherit default, explicit none, explicit value
- External event sources must supply bundle ownership explicitly
- Bundle propagation must remain visible across trigger, spawn, runtime, and observation paths

## Not In Scope

- bundle manifests
- multi-repo bundle distribution
- backward compatibility shims for old `team` payloads
- further factorio role topology expansion unless real tasks require it

## Follow-ups

- decide publication path for the local commit stack
- continue cleaning stale `team` terminology in older ADRs and docs where needed
