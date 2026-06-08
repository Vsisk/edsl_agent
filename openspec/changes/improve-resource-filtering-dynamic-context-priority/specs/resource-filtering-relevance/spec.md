## ADDED Requirements

### Requirement: Difficulty router emits a resource count hint
The system SHALL allow the difficulty router to return a bounded resource count hint representing the number of resources explicitly mentioned in the user query plus a buffer.

#### Scenario: Router returns explicit resource count
- **WHEN** the difficulty router LLM response includes a valid resource count hint
- **THEN** the route result MUST expose that hint alongside BO and function routing decisions

#### Scenario: Router response omits resource count
- **WHEN** the difficulty router LLM response does not include a valid resource count hint
- **THEN** the route result MUST use a conservative default hint without changing existing BO and function routing behavior

### Requirement: Resource filtering uses dynamic limits
The system SHALL size resource filtering limits from the route resource count hint while keeping disabled resource groups at zero.

#### Scenario: BO route is disabled
- **WHEN** the route disables BO resources and includes a positive resource count hint
- **THEN** BO candidates MUST remain disabled with a limit of zero

#### Scenario: Query mentions multiple resources
- **WHEN** the route enables a resource group and the resource count hint is larger than the current default
- **THEN** the filtering limit for that group MUST increase up to a configured upper bound

### Requirement: Explicit context area and field mentions are recalled
The system SHALL recall context variables when the query explicitly mentions a context area and field name even if the full `$ctx$` path is not written.

#### Scenario: billStatement fromDate used as naming SQL parameter
- **WHEN** the query asks to use a `billStatement` `fromDate` context value as a naming SQL query condition
- **THEN** the filtered environment MUST include the matching `$ctx$.billStatement.*fromDate*` context resource when it exists in the registry

#### Scenario: Mixed natural language and resource names
- **WHEN** the query contains resource-name tokens adjacent to non-ASCII natural-language text, such as a `billStatement` token immediately followed by prose and a `fromDate` token
- **THEN** resource filtering MUST normalize those tokens sufficiently to match equivalent registry names such as `billStatement`, `fromDate`, `fromdate`, or `FROM_DATE`

### Requirement: billStatement contexts receive recall priority
The system SHALL prioritize global context variables under `$ctx$.billStatement` during candidate recall when the query mentions bill statement context.

#### Scenario: Multiple billStatement date fields match
- **WHEN** several `$ctx$.billStatement` date fields match the query tokens with similar scores
- **THEN** the specifically mentioned field MUST be selected before unrelated sibling date fields whenever the field token is present

#### Scenario: Non-billStatement exact match is stronger
- **WHEN** the query explicitly names a non-billStatement context path or field with a stronger exact match
- **THEN** billStatement priority MUST NOT override that stronger exact match

### Requirement: Keyword search does not discard better fallback context selections
The system SHALL merge keyword search results with semantic fallback selections so broad context-area matches do not remove more specific or more relevant context candidates.

#### Scenario: Broad billStatement keyword search
- **WHEN** keyword search matches only the broad `billStatement` parent area for global contexts
- **THEN** the final global context selection MUST preserve a fallback-selected specific field such as `fromDate` if it is present in the candidates

#### Scenario: Exact context path keyword search
- **WHEN** keyword search matches a full context path that appears in the search space
- **THEN** the final global context selection MUST include that exact context resource deterministically

### Requirement: Existing fallback behavior is preserved
The system SHALL keep resource filtering usable when LLM routing, LLM keyword search, or LLM reranking is unavailable or invalid.

#### Scenario: LLM services are unavailable
- **WHEN** LLM routing or resource filtering cannot be used
- **THEN** the system MUST fall back to local scoring and return bounded selected resources

#### Scenario: LLM returns invalid resource IDs
- **WHEN** LLM reranking returns resource IDs outside the candidate pool
- **THEN** the system MUST ignore invalid IDs and fill the selection from local candidate order
