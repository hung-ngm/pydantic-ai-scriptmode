---
status: accepted
---

# No JavaScript surface: the item is closed, not deferred

ADR 0002 chose a Python subset over callscript's JavaScript and rejected "both surfaces over one
plan" for v1. The backlog kept a JS surface as item 5 in case the facts changed. Two of them have:
callscript's own surface is now JavaScript text (`packages/callscript/src/js.ts`, 1235 lines over
`acorn`, plus its own 424-line expression parser and 613-line evaluator), and Python has maintained
JavaScript parsers again (`tree-sitter-javascript` 0.25.0, 2025-09; `calmjs.parse` 1.3.4, 2025-11),
so "no maintained parser exists" is no longer the reason. The reasons that hold are the ones about
the model and the copy, not the parser. Every model this package has been trialled on writes the
Python subset first time or after one teaching retry (`HANDOFF.md`, trial findings), and harness
`CodeMode` teaches the same `await tool(arg=value)` spelling, so a JS surface would not fix a
failure anyone has seen. The `run_script` description, the grammar table, the worked example, and
the 35 teaching templates in `_teaching.py` are all written in Python spelling; a second surface
either doubles them (two tables in one description, which is the 1.5k tokens the trials say already
dominate the cost at small sizes) or rewrites each template to read correctly in both languages,
which makes every rejection message vaguer for the language that is actually in use. Expressions
are the deepest cost: `_expr.py` evaluates Python `ast` nodes, so a JS expression must be translated
into that `ast` (and `===`, `?.`, `??`, template literals, arrow functions in `map`/`filter`,
`Math.*`, `Object.keys`, and `typeof` each need a documented mapping, some lossy: `==` versus
`===` cannot both exist) or get a second evaluator with its own `NodeBudget` and dunder guard. The
decision is to not build it and to record the reasons here so the item is closed: the package has
one surface, Python, and `ToolDefinition.metadata['code_arg_language']` stays `'python'`, which is
what Logfire renders. The glossary does not gain **Surface**, since there is only one and nothing
needs to name it.

The cost is what a JS surface would have bought. Some models write tighter JavaScript than Python;
none in the trials needed to. callscript's language card and its `js.test.ts` cases would have
transferred; instead they stay a reference for behaviour, as `HANDOFF.md` lists them. A user whose
workload is JavaScript-first (an agent whose tools are already described in TypeScript, say) has
no option but the Python subset, and the retry loop teaches it in one turn. If a trial ever shows a
model that cannot write the subset after the teaching copy, that is the new fact that reopens this;
the rejected options below record how it would be built so the reopening starts from a plan.

## Considered options

- Build it with a hand-written recursive-descent parser for the subset in `_js.py`, no dependency:
  rejected. The subset is small (`const x = await tool({...})`, `const x = expr`, `if (c) return v`,
  `Promise.all(xs.slice(0, N).map(...))`, `for (const i of xs.slice(0, N))`, `try`/`catch`,
  trailing `return`), but the expressions inside it are not: a JS expression grammar with
  precedence, object and array literals, arrow functions, template literals, and optional chaining
  is most of a JS parser, which is why callscript uses `acorn` for both. Every construct the parser
  does not cover would be a `syntax_error` with no teaching copy naming the fix.
- Build it on `tree-sitter-javascript`: rejected. Maintained, but a compiled wheel for a package
  that otherwise depends only on `pydantic-ai-slim`, and the tree it gives is a concrete syntax tree
  with no expression evaluator, so the translation to Python `ast` or the second evaluator is still
  the whole job.
- Translate JS expressions to Python `ast` nodes so `_expr.py` is shared: the right choice if built,
  and recorded as such. It keeps one `NodeBudget` and one dunder guard. The mappings would be:
  `===`/`!==` to `==`/`!=`; `&&`/`||`/`!` to `and`/`or`/`not`; `??` to a ternary on `is None`;
  `?.` to a ternary on `is None`; template literals to f-strings; `x.map(i => e)` and
  `x.filter(i => c)` to comprehensions; `x.length` to `len(x)`; `Math.max`/`min`/`abs`/`round`
  to the builtins; `JSON.stringify`/`parse` to `json.dumps`/`loads`; `Object.keys`/`values`/
  `entries` to the dict methods; `undefined` and `null` to `None`. Not mappable: `typeof`, `==` with
  JS coercion, `Date`, `String(x)` versus `str(x)` on booleans (`true` becomes `True`). A step's
  hash is over the plan, so a step written in either language with the same shape would be reused
  across languages, and the test for it is one plan equality.
- `run_script(script, language='python'|'js')` with one grammar table per language in the
  description: the right choice if built, over a second tool, which would double the catalog.
  `code_arg_language` metadata is per tool definition, so Logfire would label a JS script `python`;
  accepted as a display error.
- A per-language `TEACHING` table: the right choice if built, over rewriting each template to read
  in both languages. Two tables, one key set, and the parametrized test in `tests/test_teaching.py`
  runs over both.
- Defer the item again rather than close it: rejected. Three sessions have carried it forward with
  no fact asking for it; the reopening condition above is specific (a model that cannot write the
  subset after the teaching copy) and the plan is recorded, so nothing is lost by closing.
