# AST Validation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and TDD.

**Goal:** Make AST validation the only pre-render validation gate in value generation.

**Architecture:** Remove SimplePlanValidator from ValueLogicGenerator, catch parse/build/validate failures by stage, and expose structured errors/debug data.

**Tech Stack:** Python, Pydantic v2, pytest

- [ ] Write failing end-to-end tests proving the pre-parse validator is not called, AST validation failure is structured, renderer is gated, and debug keys changed.
- [ ] Implement staged parse/build/validate handling and remove obsolete dependencies.
- [ ] Run focused and complete tests; commit.
