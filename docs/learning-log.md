# Learning log

One line per session: what was built and the one idea worth remembering.

| Date | Milestone | Built | Worth remembering |
| --- | --- | --- | --- |
| 2026-10-30 | M0 | Monorepo, contracts, 23-table schema, LLM gateway, Temporal smoke workflow, CI | Check the budget against the worst case before calling a model; record the real cost after. |
| 2026-10-30 | M0 | Fixed first real-model call: Claude 5.5 and GPT-6 Sol reject a custom temperature | Fakes do not know provider rules; also test through LiteLLM mock mode, which runs the real parameter checks. |
