from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence


def render_process_script(
    template_path: Path,
    output_path: Path,
    pseudonyms: Sequence[str],
    codex_profile: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> None:
    template = template_path.read_text(encoding="utf-8")
    profile_flag = f"-p {codex_profile} " if codex_profile else ""
    effort_flag = f'-c model_reasoning_effort={reasoning_effort} ' if reasoning_effort else ""
    phase2_commands = "\n".join(
        f'run_student "{pseudonym}" codex {profile_flag}{effort_flag}--ask-for-approval never -s workspace-write exec --skip-git-repo-check "Run submission assessment for {pseudonym}"'
        for pseudonym in pseudonyms
    )

    if "# PHASE2_COMMANDS" not in template:
        raise ValueError(f"process script template is missing # PHASE2_COMMANDS placeholder: {template_path}")
    if "__PLANNED_STUDENT_COUNT__" not in template:
        raise ValueError(
            f"process script template is missing __PLANNED_STUDENT_COUNT__ placeholder: {template_path}"
        )

    rendered = template.replace("__PLANNED_STUDENT_COUNT__", str(len(pseudonyms)))
    rendered = rendered.replace("# PHASE2_COMMANDS", phase2_commands)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    os.chmod(output_path, 0o755)
