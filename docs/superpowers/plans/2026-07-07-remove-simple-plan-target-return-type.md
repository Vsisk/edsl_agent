# Remove SimplePlan Target Return Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove target datatype generation and validation from the SimpleExpressionPlan value-generation path.

**Architecture:** Delete the field from the strict Pydantic plan model, remove it from the LLM prompt, and remove the final target comparison while retaining inferred expression types for all internal checks.

**Tech Stack:** Python, Pydantic v2, pytest

---

### Task 1: Lock the simplified contract

- [ ] Add failing tests that `SimpleExpressionPlan` rejects `target_return_type`, planner prompt omits it, and normal validation succeeds without it.
- [ ] Run focused tests and confirm RED.
- [ ] Remove the model field, prompt text, target mismatch branch, and obsolete mismatch test/helper parameters.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit `refactor: remove simple plan target return type`.

### Task 2: Verify value generation

- [ ] Run simple planner, expression validation, end-to-end value generation, and debug tests.
- [ ] Run the complete suite in the main workspace after merge.
- [ ] Confirm no expression-generation prompt or result emits target datatype metadata.
