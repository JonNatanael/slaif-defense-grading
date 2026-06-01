from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


def render_process_script(template_path: Path, output_path: Path, prompt_paths: Sequence[Path]) -> None:
    template = template_path.read_text(encoding="utf-8")
    phase2_commands = "\n".join(
        'codex --ask-for-approval never --full-auto exec --skip-git-repo-check '
        f'"$(cat {prompt_path.as_posix()})"'
        for prompt_path in prompt_paths
    )

    if "# PHASE2_COMMANDS" not in template:
        raise ValueError(f"process script template is missing # PHASE2_COMMANDS placeholder: {template_path}")

    rendered = template.replace("# PHASE2_COMMANDS", phase2_commands)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    os.chmod(output_path, 0o755)
