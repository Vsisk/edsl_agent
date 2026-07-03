# Context Manager README Design

## Goal

Create a maintainer-focused guide at `agent/context_manager/README.md` and link it from the repository root README. A new engineer should be able to understand the Context Manager boundaries, find the correct extension points, run its tests, and diagnose failures without reading the entire implementation.

## Audience

The primary audience is engineers who maintain or extend Context Manager. The guide may include a minimal invocation example, but it is not primarily an end-user API reference.

## Document Structure

The module README will cover:

1. goals and non-goals;
2. the `ValueLogicGenerator -> NamingSqlSelector -> ContextManager -> Planner` flow;
3. package layout and module responsibilities;
4. core request, asset, context, candidate, and response contracts;
5. fixed resolver execution order and evidence tracing;
6. the boundaries between embedding recall, lexical supplementation, LLM reranking, and LLM organization;
7. configuration and a minimal integration example;
8. procedures for adding a resolver, asset type, or context-building chain;
9. test commands, fake clients, and common failure codes;
10. security constraints and a maintainer checklist.

The root `README.md` will retain its short overview and add a direct link to the module guide.

## Accuracy Rules

- Examples must use the current public classes and field names.
- The guide must distinguish implemented `namingsql_selection` behavior from model-level extension points.
- It must not describe deterministic scores as final ordering; final Top-K ordering belongs to the LLM organizer.
- It must state that candidates and evidence must resolve to authoritative loaded resources.
- It must reuse the existing LLM module and describe the separate embedding adapter accurately.
- Configuration names must match `.env.example` and current settings code.
- Failure behavior must be fail-closed for required embedding and LLM stages.

## Verification

- Check every referenced path and public symbol against the repository.
- Run Markdown-oriented static checks for broken local links and stale legacy identifiers.
- Ask a fresh reader agent to answer architecture, extension, configuration, and troubleshooting questions using only the completed README.
- Correct any ambiguity or unsupported claim found during reader testing.
