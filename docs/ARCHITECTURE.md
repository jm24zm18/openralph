# Architecture

Major modules:

- `settings.py`: global + repo config merge
- `opencode_manager.py`: bundle OpenCode binary into `.ralph/bin`
- `opencode_config.py`: generate `opencode.json`
- `skills_generator.py`: generate `.opencode/skills/*/SKILL.md`
- `gitignore.py`: managed `.gitignore` block
- `tooling.py`: check/install pylsp, node servers, Playwright; doctor report
- `git_manager.py`: branch/checkpoint/rollback helpers
- `memory/`: sqlite db, index, query, vacuum
- `loop.py`: orchestration scaffold calling OpenCode with memory context
