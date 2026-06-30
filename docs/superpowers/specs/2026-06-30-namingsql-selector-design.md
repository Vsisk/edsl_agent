# NamingSQL Selector MVP Design

## Status

Approved in design discussion on 2026-06-30. This document defines the MVP architecture and contracts only; it does not authorize implementation changes.

## Problem

A BO can contain more than 100 NamingSQL definitions. Sending all definitions to an LLM is expensive and makes selection unreliable. The system needs a dedicated route that builds compact profiles, narrows the search space programmatically, verifies parameter bindability, and exposes only a small candidate set to an optional LLM reviewer.

The current expression flow filters BO resources and then passes each selected BO's NamingSQL list to the planner. The planner can therefore perform a second, implicit NamingSQL selection. The new design moves that responsibility into a standalone selector. The planner consumes the selector result and must not select again.

## Goals

- Provide a standalone `NamingSqlSelector` that can also be used inside expression generation.
- Build a compact `NamingSqlProfile` while resources are loaded.
- Generate one `DataAccessSpec` that drives both BO selection and NamingSQL selection.
- Retrieve candidates programmatically before any LLM review.
- Reject candidates whose required parameters cannot be bound reliably.
- Keep full-table SQL out of normal competition and expose it only as a controlled fallback.
- Return the selected SQL, fallback candidates, parameter bindings, rejected candidates, and reasons.
- Add only new modules and thin integration points; do not move NamingSQL-specific behavior into the planner or the core resource-filtering logic.
- Keep real LLM calls optional in the MVP.

## Non-Goals

- Persisting `DataAccessSpec` across sessions or onto EDSL nodes.
- Building a vector database or external indexing service.
- Allowing the development knowledge base to introduce resources that were not loaded by the resource manager.
- Refactoring the existing planner or resource manager beyond the fields and thin integration points required by this capability.
- Learning profile overrides from selection results.

## Key Decisions

### Structured routing signal first

Expression generation first reads `structured_spec.requires_naming_sql`. If the field is absent, a compatibility classifier may infer the route from lookup or datasource language in the specification. The structured signal always takes precedence.

### One DataAccessSpec for both stages

The selector generates one `DataAccessSpec` from the node, parent node, query, structured specification, visible context, and retrieved development knowledge. It is used first to resolve one BO and then to rank NamingSQL definitions inside that BO.

### BO selection always produces one BO

If `bo_name` is supplied, it defines the confirmed scope and must exist in the loaded resources. If it is absent, the selector programmatically recalls a small BO candidate set and asks an optional reviewer to choose one. When the reviewer is unavailable or invalid, deterministic top-1 is used. There is no ambiguous or unselected BO result.

### Development skill is a knowledge base

The development skill is treated as a site-specific knowledge base containing BO, function, context, alias, parameter-source, and usage information. A retriever injects only relevant knowledge into `DataAccessSpec` generation and BO/NamingSQL review. Knowledge can enrich loaded resources but cannot make an unloaded resource selectable.

### Full-table SQL is fallback-only

SQL with no effective filter, including `WHERE 1=1` without another effective predicate, does not compete with scoped SQL. It can be selected automatically only when `DataAccessSpec.allow_full_table` is true. Otherwise it is returned as a fallback and the result requires review.

## Architecture

The selector is an independent pipeline:

```text
NamingSqlSelectionRequest
  -> load resources and NamingSqlProfile cache
  -> retrieve relevant development knowledge
  -> generate DataAccessSpec
  -> resolve exactly one BO
  -> recall NamingSQL candidates inside that BO
  -> build parameter binding plans
  -> apply hard constraints
  -> score surviving candidates
  -> optionally review top-k
  -> NamingSqlSelectionResult
```

Components have narrow responsibilities:

- `NamingSqlProfileBuilder`: parses raw NamingSQL definitions into searchable profiles.
- `DevelopmentKnowledgeRetriever`: retrieves a small site-specific evidence set.
- `DataAccessSpecGenerator`: produces the session-local data access requirements.
- `BoResolver`: selects exactly one loaded BO.
- `NamingSqlCandidateRetriever`: recalls candidates only within that BO.
- `ParamBindingPlanner`: maps required parameters to available values.
- `NamingSqlRanker`: applies hard constraints, fallback policy, and scoring.
- `BoReviewer` and `NamingSqlReviewer`: optional top-k reviewer interfaces.
- `NamingSqlSelector`: orchestrates these components and exposes the public API.

The candidate retrievers are interfaces. The MVP uses local normalized-token and field indexes; a vector-backed implementation can replace them later without changing selector contracts.

## MVP Data Contracts

### NamingSqlProfile

```text
site_id
bo_name
naming_sql_id
sql_name
label_name
sql_description
params                 # name, data_type, is_list
filter_fields
scope_tags
is_full_table
search_text
```

Profiles contain only `site_id`; they do not persist a compound `source_key`. Existing `project_id` inputs may remain at resource-loading boundaries for compatibility but do not become profile identity.

Resource fingerprints and cache invalidation metadata stay inside the cache implementation and are not part of the domain model. A separate persisted `BoProfile` is unnecessary; BO recall text is built from the BO definition and aggregated NamingSQL profiles.

### DataAccessSpec

```text
requires_naming_sql
business_terms         # fee, free-resource, AR Trans, etc.
scope_terms            # account, subscriber, customer, etc.
bo_hints               # explicit BO names and business hints
filter_requirements
available_values       # name, source_ref, data_type, semantic_tags
allow_full_table
```

`DataAccessSpec` lives only for one generation call. It does not carry revision history or a complex evidence graph. Short reason strings are sufficient for MVP diagnostics.

### ParamBindingPlan

```text
bindings               # param_name -> source_ref, confidence, reason
unbound_params
ambiguous_params
is_complete
```

All current `param_list` entries are required because the source metadata has no optional/default markers. Future metadata can relax this rule without changing the plan shape.

Semantic binding is supported. A parameter can have multiple candidates with confidence and reasons, but automatic binding requires one unique high-confidence candidate. Exact normalized name, known alias, compatible type, and development-knowledge evidence contribute to confidence. Unresolved ambiguity prevents primary selection.

### NamingSqlSelectionRequest

```text
site_id
query
node
parent_node
structured_spec
bo_name
available_context
```

The selector retrieves development knowledge internally using `site_id`, query, and node information. It does not require the caller to pass the full knowledge corpus. A caller may optionally provide a pre-generated `DataAccessSpec` through an overload or internal entry point when orchestration already produced it.

### NamingSqlSelectionResult

```text
status                 # selected | needs_review
selected_bo
selected               # SQL identity, score, binding plan, reasons; nullable
fallback_candidates
rejected_candidates    # SQL identity plus reject codes
review_mode            # llm | deterministic_fallback | not_required
```

The binding plan belongs to the selected candidate and is not duplicated at the result root.

## Profile Construction

The BO loader must preserve the raw fields needed for profile construction: `sql_command`, `label_name`, `sql_name`, `sql_description`, and `param_list`. Today, `sql_command` and `label_name` are discarded by `NamingSqlDefTerm`; the thin loader/model extension corrects that loss without changing resource-manager control flow.

For each NamingSQL definition:

- Copy parameters from `param_list`.
- Extract effective filter fields from `WHERE`, `HAVING`, and `JOIN ... ON` predicates.
- Exclude tautologies such as `1=1` from effective filters.
- Build scope tags from SQL name, label, description, filter fields, and parameter names.
- Build normalized `search_text` from the searchable fields.
- Set `is_full_table=true` when no effective filter remains.

Parsing is conservative. A partially parsed SQL can retain recognized fields, but if the builder cannot prove an effective filter exists, it treats the SQL as fallback-only. One malformed SQL must not prevent other resources from loading.

Profiles are cached by `site_id`. Detection of changed source content is a private cache concern.

## Development Knowledge Retrieval

The retriever searches the site-specific knowledge base using the query, node, parent-node summary, structured specification, and current business terms. It returns a bounded evidence set containing relevant aliases, explicit BO suggestions, business scopes, parameter-source hints, or NamingSQL usage guidance.

Before evidence affects selection, all referenced BO and NamingSQL identifiers are checked against loaded resources. Missing identifiers can contribute a diagnostic reason such as `RESOURCE_NOT_LOADED`, but cannot enter the selectable candidate set.

Knowledge retrieval failure is non-fatal. Selection continues using the resource profiles and request context.

## BO Resolution

When a valid `bo_name` is supplied, `BoResolver` returns it directly. An explicit BO that is absent from loaded resources is an input-scope error and is not silently replaced.

Without `bo_name`, BO recall uses:

- explicit BO hints from the structured specification or development knowledge;
- business entity terms;
- account/subscriber/customer scope terms;
- BO name, description, and field terms;
- aggregated NamingSQL profile terms.

Only the top-k compact BO summaries are passed to `BoReviewer`. The reviewer must return one candidate ID. If it is unavailable, fails, or returns an invalid ID, the deterministic top-1 candidate is used and `review_mode=deterministic_fallback` is recorded.

## NamingSQL Recall, Filtering, and Ranking

Recall is restricted to the selected BO and uses normalized overlap with:

- `search_text`;
- filter fields;
- parameter names;
- scope tags;
- explicit NamingSQL guidance from development knowledge.

Full-table SQL is immediately moved into a separate fallback pool.

For every scoped candidate, `ParamBindingPlanner` builds a plan from `DataAccessSpec.available_values`. The ranker then applies hard constraints:

- every required parameter is bound;
- no parameter has unresolved ambiguity;
- required filter semantics are covered.

Rejected candidates use a small stable code set:

- `PARAM_UNBOUND`
- `PARAM_AMBIGUOUS`
- `FILTER_NOT_COVERED`
- `LOW_RELEVANCE`

Full-table candidates are not duplicated in `rejected_candidates`; their fallback reason is `FULL_TABLE_FALLBACK_ONLY`.

Survivors are scored using explicit SQL/knowledge matches, required-filter coverage, binding confidence, business-entity and scope compatibility, and name/description relevance. Sorting must be deterministic after score ties.

Programmatic top-1 may be returned without LLM review when an explicitly named SQL has complete deterministic bindings, or when top-1 clearly leads and all bindings are deterministic. Semantic bindings, close scores, or conflicting knowledge trigger optional `NamingSqlReviewer` review over top-k only. If the reviewer is unavailable, the programmatic top-1 remains selected and the fallback review mode is recorded.

When no scoped candidate survives, full-table candidates remain in `fallback_candidates`. They are selected only when `allow_full_table=true`; otherwise `selected=null` and `status=needs_review`.

## Expression Generation Integration

The integration is a thin route before ordinary resource selection:

```text
structured_spec.requires_naming_sql
  -> true: call NamingSqlSelector
  -> false: continue ordinary resource selection
  -> absent: use compatibility inference, then choose one path
```

When the selector returns a selected candidate:

- the filtered environment contains only the selected BO and selected NamingSQL;
- contexts referenced by the binding plan are included;
- the planner receives the selected SQL and fixed parameter binding plan;
- the planner never receives the BO's complete NamingSQL list.

A post-plan constraint check verifies that generated fetch nodes use the selected SQL name and the selector-provided parameter bindings. This prevents planner-side reselection or parameter rebinding while still allowing the planner to compose the fetch with broader expression logic.

If the selector returns `needs_review` with no selected SQL, expression generation stops. The planner must not bypass the selector or choose a full-table fallback itself.

Standalone calls and expression-route calls use the same selector request/result contracts.

## Failure and Degradation Rules

- Invalid explicit BO: fail as an input-scope error.
- No input BO: always resolve one BO using reviewer or deterministic top-1.
- Selected BO has no NamingSQL: return `needs_review` with no selection.
- Unbound or ambiguous parameters: reject that candidate.
- Only full-table candidates: return them as fallbacks unless full-table access is explicitly allowed.
- Malformed SQL: build a conservative fallback profile without aborting the resource load.
- Development knowledge unavailable: continue without knowledge enrichment.
- Reviewer unavailable or invalid: use deterministic top-1 from the supplied candidates.
- Reviewer invents an identifier: reject the response and use deterministic fallback.

## Test Strategy

Unit tests should cover:

- preservation of `sql_command` and `label_name` through resource loading;
- effective-filter extraction and `WHERE 1=1` classification;
- conservative behavior for malformed SQL;
- profile isolation and caching by `site_id`;
- DataAccessSpec generation from node, parent, query, structured specification, visible context, and retrieved knowledge;
- forced single-BO resolution and deterministic reviewer fallback;
- exact, alias, type-compatible, semantic, ambiguous, and missing parameter bindings;
- full-table fallback separation;
- hard rejection codes and deterministic ranking;
- rejection of knowledge-only resources that are not loaded;
- reviewer validation and degradation;
- equivalent standalone and expression-route results;
- planner visibility of only one selected NamingSQL;
- post-plan rejection of SQL or parameter changes.

Small integration tests should verify the complete expression route without requiring a real LLM by using fake reviewer implementations.

## MVP Completion Criteria

The framework is complete when callers can invoke `NamingSqlSelector` independently, expression generation can route through it, profiles are built from all required raw fields, BO resolution returns exactly one BO, NamingSQL candidates are filtered by binding feasibility, full-table SQL is controlled, and the planner receives only the selector-approved SQL and binding plan. Optional reviewer interfaces must work with deterministic fallbacks, but a live LLM integration is not required.
