# Prompts

Prompts ship inside the package that uses them, so they are always deployed with their code:

- Research: `services/research/src/firstweek_research/prompts/`

Each file is one version (`classify-role.v1.md`). The system part comes before the `=== user ===` line. Every gateway call logs its `prompt_version`, and stored results record the version that produced them, so changing a prompt means adding a new version file rather than editing the old one.
