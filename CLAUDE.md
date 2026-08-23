# Project Instructions — NEXUS

## Git policy — READ BEFORE ANY ACTION

Claude Code must NEVER run any git command that changes repo state or 
history. This includes but is not limited to:
- git add
- git commit
- git push
- git pull
- git merge
- git branch (creating/deleting)
- git checkout (switching/creating branches)
- git reset
- git rebase
- git tag
- Any GitHub CLI (gh) command that creates, modifies, or deletes anything 
  on the remote (gh repo, gh pr, gh issue, etc.)

Claude Code MAY freely read git state for context: git status, git diff, 
git log — these are fine, since they don't change anything.

All commits, pushes, branching, and GitHub-side changes are done manually 
by the project owner (Varun). Claude Code's job is to write, edit, and test 
code in the working directory only. If asked to "commit this" or "push this," 
politely decline and remind the user this is a manual step they handle 
themselves.

## Failure log policy

Every error, failed command, or breakdown must be logged in FAILURE_LOG.md 
per the template already defined there, before moving to the next step.
