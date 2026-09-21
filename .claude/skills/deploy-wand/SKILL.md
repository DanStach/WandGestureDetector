---
name: deploy-wand
description: Commit any uncommitted changes, push to GitHub, then SSH into the Raspberry Pi and git pull. Use when the user says "deploy", "deploy-wand", or wants local changes on the Pi.
---

# deploy-wand

Ship local changes to the Raspberry Pi via GitHub. Pi: `raspi@192.168.4.217`, repo at `~/WandGestureDetector`.

## Steps

1. **Review local changes.** Run `git status --short` and `git diff`. If the tree is clean, skip to step 3 (still push if the branch is ahead of `origin`).

2. **Commit.** Stage the changed files by name (avoid `git add -A` so stray or secret files aren't swept in). Write a short imperative commit message describing the change, ending with the attribution line from the session's system-reminder. Never use `--no-verify` or amend existing commits.

3. **Push.** `git push origin <current-branch>`. If you're on a branch other than `main`, tell the user before continuing, since the Pi pulls whatever branch it has checked out.

4. **Check the Pi is clean.** Run:
   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 raspi@192.168.4.217 'cd ~/WandGestureDetector && git status --short'
   ```
   If it shows local modifications, stop and report them to the user. Do not stash, reset, or discard anything on the Pi without asking.

5. **Pull on the Pi.**
   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=20 raspi@192.168.4.217 'cd ~/WandGestureDetector && git pull --ff-only 2>&1 | tail -10 && git log --oneline -1'
   ```
   If the fast-forward fails, report it and stop.

6. **Report.** State the commit hash now on the Pi and which files changed. Note that a running service is not restarted by this skill; if the user wants that, the command is `sudo systemctl restart ir-gesture.service` on the Pi.

## Failure handling

- SSH failure (timeout, auth): report it and stop; don't retry with password prompts.
- Push rejected (remote ahead): report it and ask; don't force-push.
