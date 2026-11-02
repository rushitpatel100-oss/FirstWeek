# ADR 0025: A static demo page for the portfolio

## Decision
The project is for a portfolio, not public hosting. `apps/demo` is a Vite + React page with no
server, published free on GitHub Pages by `.github/workflows/pages.yml`.

- **Code runs for real**: pytest runs in the visitor's browser through Pyodide (Python compiled
  to WebAssembly, loaded from a CDN) inside a Web Worker, so a hung test can be terminated.
- **AI replies are recorded**: colleague answers, the Tech Lead review and the supervisor's
  verdict are written ahead of time in `recorded.ts` and labelled "recorded sample" on screen.
  The live app (`apps/web` + `apps/api`) uses a model; the demo costs nothing and cannot run out of quota.
- **No answer key**: `scripts/export_demo_data.py` writes `src/data.json` from `public_view()`
  and the starter files only.

## Consequences
Cost is zero and there is nothing to keep running. The replies do not react to what the visitor
types (they vary by colleague and by test result). The deployment kit (ADR 0024) is only needed
if the project is ever hosted live.
