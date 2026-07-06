# Return Type Static Infrastructure Design

## Scope

Add standalone static-type infrastructure for expression return types. This change does not integrate with the planner and does not modify the expression-generation main flow, validators, or renderers.

## Architecture

The implementation lives in `agent/expression_generation/type_system.py` and has no dependency on planner or AST behavior. It contains immutable-style Pydantic value models plus in-memory registries. Tests live in `tests/test_type_system.py`.

## Type Model and Normalization

`TypeRef` represents `basic`, `bo`, `logic`, `extattr`, `list`, `map`, `void`, and `unknown`. Scalar named types use `name`; lists use `element_type`; maps use `key_type` and `value_type`. `nullable` defaults to `True`.

`normalize_return_type(raw_return_type)` accepts an existing resource return-type Pydantic model or a mapping with `data_type`, `data_type_name`, and `is_list`. It returns:

- a named scalar for recognized `basic`, `bo`, `logic`, and `extattr` categories;
- a list wrapping that scalar when `is_list` is true;
- `void` for a void category or void type name;
- `unknown` for absent, malformed, unsupported, or incomplete input.

Type names retain the spelling supplied by resources, including `String`, `int`, and BO names.

## Type Registry

An object type definition associates an owner `TypeRef` with a mapping of field names to field `TypeRef` values. `TypeRegistry.register_type(type_def)` replaces any prior definition for the same owner type. `resolve_field(owner_type, field_name)` returns the registered field type or `None` when the owner or field is unknown.

## Method Registry

A method signature contains an owner type pattern, method name, argument type patterns, and return type pattern. `MethodRegistry.register_method(method_sig)` stores signatures in registration order. `match(owner_type, method_name, arg_types)` returns the instantiated return `TypeRef` for the first exact compatible signature, or `None` when no signature matches.

Generic matching uses an internal type-variable representation so the same `T` is consistently bound across owner, arguments, and return type. This supports `List<T>` and `Map<String, T>` without weakening basic-type matching. `find{expr}` and `findAll{expr}` are registered as literal method names with no ordinary arguments in this phase.

An explicit built-in registration function installs only the requested String, Date, int, long, List, and Map methods. Importing the module does not mutate a shared global registry.

## Error Handling

Normalization is tolerant and produces `unknown` for unusable resource metadata. Registry lookup is non-throwing and returns `None` for misses. Invalid model construction remains subject to Pydantic validation.

## Testing

Tests are written first and observed failing before production implementation. They cover all required normalization examples, BO field registration and resolution, basic String method lookup, Date return resolution, and generic List method lookup. Additional focused coverage verifies Map generic substitution and representative built-in signatures without coupling tests to planner, validator, renderer, or expression generation.

