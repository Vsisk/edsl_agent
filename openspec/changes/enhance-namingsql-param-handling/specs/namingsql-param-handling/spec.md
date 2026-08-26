## ADDED Requirements

### Requirement: NamingSQL parameter cardinality is inferred from SQL usage

The system MUST infer each selected NamingSQL parameter's effective `is_list` value from supported SQL command parameter usage. Scalar comparison operators MUST produce `is_list=false`; template `in` and `not_in` usages MUST produce `is_list=true`. When existing metadata conflicts with supported SQL usage, the SQL-derived cardinality MUST be used and the conflict MUST be diagnosable.

#### Scenario: Equality parameter is single
- **WHEN** a selected NamingSQL SQL command contains `CATEGORY = :CATEGORY`
- **THEN** the effective parameter definition for `CATEGORY` has `is_list=false`

#### Scenario: Inequality parameter is single
- **WHEN** a selected NamingSQL SQL command contains `CATEGORY <> :CATEGORY`
- **THEN** the effective parameter definition for `CATEGORY` has `is_list=false`

#### Scenario: Range comparison parameter is single
- **WHEN** a selected NamingSQL SQL command contains `AMOUNT >= :MIN_AMOUNT`
- **THEN** the effective parameter definition for `MIN_AMOUNT` has `is_list=false`

#### Scenario: Template IN parameter is list
- **WHEN** a selected NamingSQL SQL command contains `CATEGORY ${in,:CATEGORY}`
- **THEN** the effective parameter definition for `CATEGORY` has `is_list=true`

#### Scenario: Template NOT IN parameter is list
- **WHEN** a selected NamingSQL SQL command contains `CATEGORY ${not_in,:CATEGORY}`
- **THEN** the effective parameter definition for `CATEGORY` has `is_list=true`

#### Scenario: Metadata conflict uses SQL
- **WHEN** NamingSQL metadata marks `CATEGORY` as single but the SQL command contains `CATEGORY ${in,:CATEGORY}`
- **THEN** the effective parameter definition for `CATEGORY` has `is_list=true`
- **AND** the mismatch is recorded in debug or warning diagnostics

### Requirement: NamingSQL parameters bind to BO fields from SQL conditions

The system MUST bind a selected NamingSQL parameter to the BO field used on the left side of its supported SQL condition when that field can be found reliably in the NamingSQL's BO. The binding MUST expose only `field_name` and `description` as temporary field context.

#### Scenario: Same-name field binding
- **WHEN** a NamingSQL belonging to `BB_BILL_CHARGE` contains `CATEGORY ${in,:CATEGORY}`
- **AND** BO `BB_BILL_CHARGE` has field `CATEGORY` with a description
- **THEN** the effective parameter definition for `CATEGORY` has `linked_field_name= CATEGORY`
- **AND** temporary field context description equals the BO field description

#### Scenario: Different parameter and field names
- **WHEN** a NamingSQL belonging to `BB_BILL_CHARGE` contains `CATEGORY ${in,:CHARGE_TYPE}`
- **AND** BO `BB_BILL_CHARGE` has field `CATEGORY` with a description
- **THEN** the effective parameter definition for `CHARGE_TYPE` has `linked_field_name= CATEGORY`
- **AND** the effective parameter definition for `CHARGE_TYPE` has `is_list=true`

#### Scenario: Unreliable field binding is omitted
- **WHEN** a NamingSQL parameter appears in unsupported or ambiguous SQL usage
- **THEN** the system MUST NOT guess the BO field
- **AND** the effective parameter definition has no `linked_field_name` or has `linked_field_name=None`

### Requirement: NamingSQL profile return fields exclude optimizer hints

The system MUST ignore SQL optimizer hint comments when extracting NamingSQL profile return fields from the SELECT clause. Hint comments beginning with `/*+` MUST NOT appear in `return_fields`, and the actual projected field following the hint MUST still be extracted.

#### Scenario: SELECT optimizer hint is ignored before first field
- **WHEN** a NamingSQL SQL command contains `SELECT /*+ INDEX(BB_BILL_CHARGE IDX_CHARGE) */ BE_ID, ACCT_ID FROM BB_BILL_CHARGE WHERE BE_ID = :BE_ID`
- **THEN** the NamingSQL profile `return_fields` includes `BE_ID` and `ACCT_ID`
- **AND** the NamingSQL profile `return_fields` does not include `INDEX`, `IDX_CHARGE`, `*/`, or any optimizer hint fragment

#### Scenario: SELECT without optimizer hint keeps existing field parsing
- **WHEN** a NamingSQL SQL command contains `SELECT BE_ID, ACCT_ID FROM BB_BILL_CHARGE WHERE BE_ID = :BE_ID`
- **THEN** the NamingSQL profile `return_fields` includes `BE_ID` and `ACCT_ID`

### Requirement: Bound field context remains transient

The system MUST use field context descriptions only as temporary context between resource search and Expression Spec generation. The final ExpressionContextSpec and Planner input MUST contain resolved NamingSQL parameter values but MUST NOT contain BO field descriptions, value semantics, evidence, or field context metadata.

#### Scenario: Final spec stores only resolved literal value
- **WHEN** the user query says `一次性费用`
- **AND** `CATEGORY` is bound to a BO field whose description maps `一次性费用` to `C02`
- **THEN** the final ExpressionContextSpec contains a NamingSQL param binding for `CATEGORY` with literal value `C02` or `["C02"]` according to `is_list`
- **AND** the final ExpressionContextSpec does not contain the BO field description

#### Scenario: Planner receives no bound field description
- **WHEN** Planner is invoked after NamingSQL parameter binding succeeds
- **THEN** Planner input contains the selected NamingSQL and resolved parameter bindings
- **AND** Planner input does not require or include field context descriptions to explain why a business phrase maps to a code

### Requirement: Expression Spec resolves literal values using bound field descriptions

Expression Spec generation MUST resolve NamingSQL literal parameter values using the user query, the parameter name, optional field context description, and effective `is_list`. For list parameters, a single matched business code MUST be emitted as a one-element list. For single parameters, the value MUST be emitted as a scalar.

#### Scenario: Single parameter literal remains scalar
- **WHEN** SQL command contains `CATEGORY = :CATEGORY`
- **AND** the user query and bound field description resolve the value to `C01`
- **THEN** the final param binding is `{"param_name":"CATEGORY","value":{"type":"literal","value":"C01"}}`

#### Scenario: List parameter wraps one matched literal
- **WHEN** SQL command contains `CATEGORY ${in,:CATEGORY}`
- **AND** the user query says `租费`
- **AND** the bound field description maps `租费` to `C01`
- **THEN** the final param binding is `{"param_name":"CATEGORY","value":{"type":"literal","value":["C01"]}}`

#### Scenario: List parameter emits multiple matched literals
- **WHEN** SQL command contains `CATEGORY ${in,:CATEGORY}`
- **AND** the user query says `获取一次性费用`
- **AND** the bound field description maps `一次性费用` to `C01` and `C02`
- **THEN** the final param binding is `{"param_name":"CATEGORY","value":{"type":"literal","value":["C01","C02"]}}`

### Requirement: Expression Spec rejects parameter cardinality mismatches

Expression Spec generation MUST validate literal and resource-backed NamingSQL parameter bindings against effective `is_list`. A single parameter MUST NOT accept multiple values. A list parameter MUST NOT bind to a resource known to return a scalar. A single parameter MUST NOT bind to a resource known to return a list. A resource whose cardinality is unknown MUST NOT be guessed into a final binding; the parameter MUST remain unbound/empty through the existing fallback behavior and the reason MUST be logged. Cardinality failures MUST return `PARAM_CARDINALITY_MISMATCH` or an equivalent structured error before Planner attempts expression generation.

#### Scenario: Multiple literal values for single parameter fail
- **WHEN** SQL command contains `CATEGORY = :CATEGORY`
- **AND** parameter value resolution produces `["C01","C02"]`
- **THEN** Expression Spec generation fails with `PARAM_CARDINALITY_MISMATCH`

#### Scenario: List parameter accepts list resource
- **WHEN** SQL command contains `ACCT_ID ${in,:ACCT_ID}`
- **AND** the final binding uses resource `$local$.acctIdList`
- **AND** `$local$.acctIdList` has return type `list[string]`
- **THEN** Expression Spec generation accepts the binding

#### Scenario: List parameter rejects scalar resource
- **WHEN** SQL command contains `ACCT_ID ${in,:ACCT_ID}`
- **AND** the final binding uses resource `$ctx$.acct.acctId`
- **AND** `$ctx$.acct.acctId` has return type `string`
- **THEN** Expression Spec generation fails with `PARAM_CARDINALITY_MISMATCH`

#### Scenario: Single parameter rejects list resource
- **WHEN** SQL command contains `BILL_CYCLE_ID = :BILL_CYCLE_ID`
- **AND** the final binding uses a resource known to return `list[string]`
- **THEN** Expression Spec generation fails with `PARAM_CARDINALITY_MISMATCH`

#### Scenario: Unknown resource cardinality remains unbound
- **WHEN** SQL command contains `ACCT_ID ${in,:ACCT_ID}`
- **AND** a candidate resource for `ACCT_ID` has no known scalar/list return type
- **THEN** Expression Spec generation does not guess that resource into the final binding
- **AND** the parameter remains unbound or empty according to existing fallback behavior
- **AND** the reason is logged

### Requirement: NamingSQL parameter diagnostics are available

The system MUST provide debug or warning logs sufficient to inspect NamingSQL parameter enrichment and final binding. Logs MUST include parameter name, SQL-bound field when available, effective `is_list`, bound field presence, metadata conflicts, unknown resource cardinality decisions, and final Spec parameter value when resolved.

#### Scenario: Enriched parameter diagnostics are logged
- **WHEN** a NamingSQL parameter is enriched from SQL command and BO field metadata
- **THEN** logs include `param_name`, SQL-bound field name, effective `is_list`, and whether `linked_field_name` and field context were attached

#### Scenario: Final value diagnostics are logged
- **WHEN** Expression Spec generation resolves a NamingSQL parameter value
- **THEN** logs include the parameter name and final literal or resource value without requiring Planner to rederive the value

