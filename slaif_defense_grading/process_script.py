from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence


class ProcessStatus:
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ProcessStudent:
    """One planned student for the rendered process.sh.

    ``status`` is the association status from associations.csv: resolved
    students get a Codex command; unresolved students receive a deterministic
    local neutral report and never trigger an agent invocation.
    """

    pseudonym: str
    status: str


def render_process_script(
    template_path: Path,
    output_path: Path,
    students: Sequence[ProcessStudent],
    codex_profile: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> None:
    template = template_path.read_text(encoding="utf-8")
    profile_flag = f"-p {codex_profile} " if codex_profile else ""
    effort_flag = f"-c model_reasoning_effort={reasoning_effort} " if reasoning_effort else ""

    phase2_commands: List[str] = []
    for student in students:
        if student.status == ProcessStatus.RESOLVED:
            agent_command = (
                f'codex {profile_flag}{effort_flag}--ask-for-approval never -s workspace-write '
                f'exec --skip-git-repo-check "Run submission assessment for {student.pseudonym}"'
            )
            phase2_commands.append(f'run_planned_student "{student.pseudonym}" {ProcessStatus.RESOLVED} {agent_command}')
        else:
            phase2_commands.append(f'run_planned_student "{student.pseudonym}" {ProcessStatus.UNRESOLVED}')
    phase2_text = "\n".join(phase2_commands)

    if "# PHASE2_COMMANDS" not in template:
        raise ValueError(f"process script template is missing # PHASE2_COMMANDS placeholder: {template_path}")
    if "__PLANNED_STUDENT_COUNT__" not in template:
        raise ValueError(
            f"process script template is missing __PLANNED_STUDENT_COUNT__ placeholder: {template_path}"
        )

    rendered = template.replace("__PLANNED_STUDENT_COUNT__", str(len(students)))
    rendered = rendered.replace("# PHASE2_COMMANDS", phase2_text)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    os.chmod(output_path, 0o755)
