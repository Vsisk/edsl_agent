## ADDED Requirements

### Requirement: Scope-aware root priority
The system SHALL prioritize typed-context roots by explicit query reference and then by lexical scope distance, with `$iter$` ahead of `$local$` and `$local$` ahead of `$ctx$`. Functions and derived templates SHALL remain available only after required context roots have been admitted.

#### Scenario: Near scopes compete with global context
- **WHEN** `$iter$`, `$local$`, and `$ctx$` roots compete under a constrained item budget
- **THEN** the emitted roots are admitted in `$iter$`, `$local$`, `$ctx$` order

#### Scenario: Explicit global path overrides distance
- **WHEN** the query explicitly references a selected `$ctx$` path and the item budget is constrained
- **THEN** that root is treated as required and admitted before non-explicit roots regardless of scope distance

### Requirement: Two-stage item budgeting
The system SHALL budget root admission separately from field-detail expansion so a large structured root cannot consume the entire budget before other higher-priority roots are represented. The final emitted context MUST NOT exceed `max_items` under the existing item-counting contract.

#### Scenario: Large iterator does not hide local roots
- **WHEN** `$iter$` expands to more fields than the remaining budget and a visible `$local$` root exists
- **THEN** the local root is admitted before the remaining budget is allocated to iterator field details

#### Scenario: Budget remains a hard ceiling
- **WHEN** the candidate typed context contains more roots, fields, catalog entries, and patterns than `max_items`
- **THEN** the sum of emitted budgeted items does not exceed `max_items`

### Requirement: Relevant details are emitted first
Within the same scope tier, the system SHALL rank field details using explicit path or field-name matches, node-name relevance, annotation relevance, and a deterministic fallback order.

#### Scenario: Query-relevant field wins a constrained slot
- **WHEN** only one field-detail slot remains and one field matches the query more strongly than its siblings
- **THEN** the matching field is emitted

#### Scenario: Equal relevance is deterministic
- **WHEN** fields have equal relevance scores
- **THEN** repeated builds with the same input emit the same field order

### Requirement: Type-level method deduplication
The system SHALL emit method signatures once per referenced return type through `method_catalog` and SHALL NOT repeat the same method list on every root or access view.

#### Scenario: Multiple string values share one catalog entry
- **WHEN** multiple emitted roots or fields have return type `basic.String`
- **THEN** `basic.String` method signatures appear in one method-catalog entry and are absent from the individual value views

#### Scenario: Unreferenced type is omitted
- **WHEN** truncation removes every value of a type
- **THEN** the method catalog does not contain an entry for that type

### Requirement: Observable truncation
The system SHALL add a deterministic warning when applicable candidates are omitted due to the typed-context item budget.

#### Scenario: Context is truncated
- **WHEN** one or more roots, fields, catalog entries, or patterns are omitted because `max_items` is exhausted
- **THEN** the returned context contains a warning indicating budget truncation

#### Scenario: Context fits the budget
- **WHEN** all applicable typed-context items fit within `max_items`
- **THEN** no budget-truncation warning is added
