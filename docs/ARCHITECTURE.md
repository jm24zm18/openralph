# Architecture

Major modules:

- `settings.py`: global + repo config merge
- `gitignore.py`: managed `.gitignore` block
- `tooling.py`: check/install pylsp, node servers, Playwright; doctor report
- `git_manager.py`: branch/checkpoint/rollback helpers
- `memory/`: sqlite db, index, query, vacuum
- `loop.py`: orchestration scaffold for native agents with memory context
