# No-Commit Skill

## Rules

1. **Never commit unless the user explicitly says "commit" or asks me to commit.** No auto-committing, no preemptive commits, no committing at the end of a task unless asked.

2. **Commit message format:** Use conventional commits:
   ```
   <type>(<scope?>): <description>
   ```
   Valid types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, `style`.
   Scope is optional. Examples:
   - `feat(db): add project_members table to postgres adapter`
   - `fix(auth): handle missing session in user-provider`
   - `chore: flip DATABASE_PROVIDER to postgresql`

3. **Group changes logically but don't overthink it.** When committing, batch related file changes into a single commit per logical unit (e.g., one commit for adapter changes, one for auth changes). Do not spend excessive time deliberating over grouping—if it's related, group it; if unsure, commit per file area and move on.

4. **Do not reason endlessly about what to commit together.** Make a decision quickly and commit.

## When active

Apply these rules to every git operation in this repo.