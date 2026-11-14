"""Workflow orchestration layer — revision engine for the Director Studio.

Not an Agent. Deterministic bookkeeping: given a human edit, decide which
downstream stages are invalidated, then re-run only those stages via the
existing Agents. Mirrors cursor.md — cognition stays in Agents, this module
only sequences deterministic execution.
"""
