# Installing agentlink

Two audiences, same commands. Humans can follow the first section; agents should follow
"Instructions for an agent" exactly.

- Repository: <https://github.com/gougougouz/agent-context-bridge>
- Requirements: Python 3.9+ on PATH. Nothing else — no git, no pip packages required
  (`zstandard` is installed only for reading DSH's compressed sessions, and its absence
  does not break Codex or Claude).
- No administrator rights, no prompts, no interactive questions.

## Install (humans)

Windows, PowerShell:

```powershell
irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
```

Restart the tools (or open a new session), then in any project:

```bash
agentlink init
agentlink brief
```

## Instructions for an agent

You were asked something like "install this skill: <repository URL>" or "把这个 skill 装上".
Do the following, in order, without asking the user to run anything manually.

1. **Check Python.** `python --version` (Windows may need `py -3 --version`). If it is older
   than 3.9 or missing, stop and tell the user to install Python 3.9+; do not try to install
   a Python runtime yourself.

2. **Install.** Pick the command for the current OS and run it in a shell.

   Windows (PowerShell 5.1 or PowerShell 7):

   ```powershell
   irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex
   ```

   macOS / Linux:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
   ```

   If a different location is required (for example a project policy that forbids writing to
   the home directory, or a drive with more space), pass it explicitly:

   ```powershell
   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1))) -Dir D:\app\agentlink
   ```

   ```bash
   curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | AGENTLINK_HOME=/opt/agentlink bash
   ```

   Useful switches when something is restricted: `-NoPath` (do not edit the user PATH),
   `-NoDeps` (do not run pip), `-Force` (overwrite a non-empty directory).

3. **Verify.** The installer prints a version line such as `agentlink 0.2.0`. Confirm it
   independently:

   ```bash
   agentlink --version
   agentlink doctor
   ```

   `doctor` prints the Python it uses, whether `zstandard` is importable, the transcript
   directory of each tool, and whether `SKILL.md` landed in each skill folder. Missing
   transcript directories are normal (that tool is simply not installed).

4. **Report.** Tell the user, in their language: the version, the three skill paths, the
   command they will use (`agentlink brief`), and that they should restart the tools or open
   a new session. Do not paste the whole installer output.

5. **Do not** clone the repository, create a virtualenv, edit the registry, or modify files
   outside the install directory and the three skill directories. The installer is
   idempotent: running it again upgrades in place and keeps the user's projects untouched.

### Expected result

| Artifact | Path |
| --- | --- |
| code | `%LOCALAPPDATA%\agentlink` (Windows) · `~/.local/share/agentlink` (macOS/Linux) |
| DSH skill | `~/.dsh/skills/agent-context-bridge/` |
| Codex skill | `~/.codex/skills/agent-context-bridge/` |
| Claude skill | `~/.claude/skills/agent-context-bridge/` |
| launcher | `<install dir>/bin/agentlink` (`agentlink.cmd` on Windows) |

Exit code 0 with a version line means success. A non-zero exit prints one line starting with
`x`; fix that condition and re-run — nothing is left half-installed.

### If the install cannot run

- **No network.** The installer downloads a zip from `codeload.github.com`. If that is
  blocked, ask the user for a local copy of the repository and run
  `python -m agentlink install` from its root with `PYTHONPATH=<repo>/src`.
- **Restricted PATH.** Use `-NoPath`; the skill directories still receive working launchers,
  and each contains a `LOCAL.md` with the absolute path to run.
- **Read-only home.** Use `-Dir` / `AGENTLINK_HOME` to point at a writable location.
- **Skill folders do not exist yet.** That is fine; the installer creates them. If the
  client is installed later, re-run the installer.

## Upgrade

Run the same command again. The installer replaces the code, reinstalls the skills, and
re-verifies the version. Project state (`.agentlink/`) lives in each project and is never
touched.

## Uninstall

Remove what the installer created:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\agentlink"
Remove-Item -Recurse -Force "$env:USERPROFILE\.dsh\skills\agent-context-bridge"
Remove-Item -Recurse -Force "$env:USERPROFILE\.codex\skills\agent-context-bridge"
Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\agent-context-bridge"
```

```bash
rm -rf ~/.local/share/agentlink
rm -rf ~/.dsh/skills/agent-context-bridge ~/.codex/skills/agent-context-bridge ~/.claude/skills/agent-context-bridge
```

Then delete the PATH entry pointing at `<install dir>/bin` if you added one, and remove any
`.agentlink/` directories you no longer want in projects. No registry keys, services, or
global packages are involved.

## Security and privacy

- The installer is a single readable script; it downloads the repository zip and copies files.
- `zstandard` is the only package it may install, via `pip install --user`-style call.
- After installation the tool makes no network requests. Transcripts are read locally and
  never uploaded. See "Design notes" in the README.