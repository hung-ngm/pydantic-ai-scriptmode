# Examples

Small agents that each show one thing `ScriptMode` does, in a domain where that thing is the
natural need. Every example is self-contained: its tools work on in-memory data, so it needs only a
model key, and it prints the script the model wrote next to what the script returned.

## Setup

From the repo root:

```bash
make install
uv run examples/basic.py
```

Each example reads `ANTHROPIC_API_KEY` from the environment or a `.env` file and defaults to
`anthropic:claude-sonnet-5`. Set `PYDANTIC_AI_MODEL=provider:model` to run against another model;
you then need that provider's key instead.

## The examples

| Example | Use case | What it shows | Needs a key |
| --- | --- | --- | --- |
| [`basic.py`](basic.py) | Issue triage | Two tools folded into `run_script`; one script lists, filters, guards on the empty case, and fans out the closes | yes |

Every example exposes a `build_agent(model=...)` factory, which `tests/test_examples.py` uses to
build it with a test model and to drive it with a fixed script, and a `main()` that runs one task.
