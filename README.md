# AI Context Map

A CLI tool that helps developers and AI agents navigate codebases faster by identifying relevant files and guiding task-focused exploration.

## Why it matters

- developers and AI tools waste time opening irrelevant files
- large repos are hard to navigate
- fixes are often too local and miss system-level impact

## Example

```bash
aicontext plan "fix API bug"
```

The intended result is a short, task-focused reading list: likely entry points, important related modules, and the files most likely to be affected by the change.

In the current prototype, that planning data is generated with `aicontext generate` and exposed through `aicontext inspect-routes`.

## What it does

- builds repository structure
- ranks important files
- groups related code
- produces task-aware plans

## How it works

- Structure: scans source files and builds a lightweight dependency graph.
- Memory: writes a shared `.ai/context.yaml` file with ranked modules, anchors, hotspots, and task routes.
- Planning: uses those precomputed routes to narrow where an agent should start for a bugfix, feature, API change, config change, or test task.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `aicontext` CLI entry point from [`pyproject.toml`](/Users/avi/Documents/AIcontextMap/pyproject.toml:1).

## Usage

```bash
aicontext init
aicontext generate
aicontext inspect-routes
```

Generated files live under `.ai/`.

## Status

Experimental prototype.
