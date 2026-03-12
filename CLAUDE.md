# Project Name
OpenCycleTrainer

## Overview
OpenCycleTrainer is a cross-platform open-source workout player for indoor bike training for desktop devices based on Python and PySide6.

## Tech Stack
* Python
* PySide6 GUI
* Bleak for BLE comms
* fit-tool for writing FIT files out
* pytest

## How to Run Tests
python -m pytest

## Conventions
Comment classes and methods succinctly. Do not comment method code inline unless something atypical or counterintuitive is being done. Follow existing structure and style. If in doubt, follow PEP-8 guidelines.

## Agent Delegation
- **Always** use the `codebase-explorer` agent for reading files, searching code, or understanding structure. Do not use Read, Grep, Glob, or Bash directly in the main agent for exploration UNLESS exact code contents are required.
- **Always** use the `test-runner` agent to run tests. Do not run pytest directly in the main agent. Specify the exact command (full suite or targeted test file/test name).
- For multi-area exploration, launch multiple `codebase-explorer` agents in parallel in a single message.
- In the TDD workflow: use `codebase-explorer` to understand existing patterns before writing tests, then `test-runner` to confirm they fail for the right reason, then `test-runner` again after implementation.
  
## Development Workflow
- Write tests before implementing new features (TDD)
- Tests should reflect the intended behavior and interface, not the implementation
- Get tests failing for the right reason before writing code to pass them
- For larger features, write tests incrementally — one behavior at a time

## Documentation
When implementing items from TODOs.md, **always** mark them done once completed and passing tests.