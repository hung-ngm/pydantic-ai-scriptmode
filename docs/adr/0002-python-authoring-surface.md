---
status: accepted
---

# The model writes Python, not callscript's JavaScript

callscript's authoring surface is JavaScript. ScriptMode uses a Python subset instead: the
standard library `ast` module parses it, tool calls are keyword calls that map one to one onto
Pydantic AI tool schemas, the catalog can be rendered with core's `ToolDefinition.render_signature`,
and it matches what harness `CodeMode` already teaches models in this ecosystem
(`await tool_name(arg=value)`, `await asyncio.gather(...)`). The cost is that callscript's language
card, validator messages, and JSON plans do not transfer; plans are not interchangeable between
the two projects.

## Considered options

- JavaScript surface with a Python JS parser (`esprima` port, unmaintained since 2018) or a
  hand-written parser: rejected, adds a parser to maintain and teaches models a second dialect
  next to `CodeMode`.
- Both surfaces over one plan: rejected for v1, doubles the compiler and test matrix.
