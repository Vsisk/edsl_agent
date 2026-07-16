# ContextPack Current-Node Projection Design

## Goal

Make the complete matched current-tree node available to downstream spec and planner stages without recursively including its child subtree. This ensures existing expression fields, including `data_expression` and `edsl_semi_struct`, survive the bounded ContextPack prompt projection.

## Current Behavior

`CurrentTreeProvider` resolves each recalled item back to its canonical JSON value and stores that value in `ContextItem.content["value"]`. The shared `ContextPackPromptRenderer` then drops `content` and emits only the item identity, authority, type, summary, and facts. Downstream consumers therefore cannot see expression data that is already present in the ContextPack item.

## Design

The underlying ContextPack model, providers, retrieval order, and ranking remain unchanged. The change is limited to the shared downstream prompt projection.

For every item in the `current_tree` section whose `item_type` is `node` or `field`, the renderer will add a `node` property containing a deep, JSON-compatible projection of `item.content["value"]`.

The projected node will:

- retain every top-level node field, including expression, semi-structured EDSL, type, data-source, local-context, iteration-context, and AB configuration fields;
- omit the top-level `children` property entirely;
- avoid mutating the canonical value stored in the ContextPack or the request tree;
- be omitted when `content["value"]` is not an object.

Items from `dev_skill` and `ootb_edsl`, and non-node current-tree items such as individual local or iteration variables, retain the existing compact projection.

## Data Flow

```text
CurrentTreeProvider
  -> ContextItem.content.value (canonical node, including children)
  -> ContextPackPromptRenderer
       -> copy canonical node
       -> remove top-level children
       -> emit item.node
  -> spec / typed-context / planner consumers
```

Only the projection is changed. The authoritative ContextPack item continues to hold its original canonical value.

## Budget and Trimming

The existing global `max_items` and `max_chars` limits remain authoritative. A projected node is added atomically:

1. Build the complete item projection, including the childless node.
2. Serialize the complete accumulated prompt value.
3. If it exceeds `max_chars`, remove that complete item rather than truncating its JSON structure.
4. Mark the rendered output with `CONTEXT_PACK_PROMPT_TRIMMED` so consumers and diagnostics can distinguish budget loss from absent source data.

This preserves valid JSON and prevents a partial expression or partial node from reaching downstream stages.

## Compatibility

This is an additive prompt-projection change. Existing item fields remain unchanged. ContextPack serialization outside `ContextPackPromptRenderer` is unaffected. Consumers that ignore the new `node` property continue to work.

Prompt size may increase for current-tree node hits, but excluding `children` bounds the largest source of recursive growth.

## Testing

Focused tests will verify that:

- a current-tree node projection contains `data_expression`, `edsl_semi_struct`, and other arbitrary top-level fields;
- the projected node does not contain `children`, including when the canonical node has nested descendants;
- rendering does not mutate the source tree or `ContextItem.content["value"]`;
- local and iteration items and non-current-tree sections keep the compact projection;
- an oversized node item is removed atomically and produces `CONTEXT_PACK_PROMPT_TRIMMED`;
- the shared projection used by planner paths exposes the node expression.

## Out of Scope

- Changing current-tree recall, ranking, or visibility rules.
- Adding a fourth ContextPack resource type.
- Recursively including descendants or ancestors.
- Changing expression generation or planner semantics.
- Expanding dev-skill or OOTB item projections.
