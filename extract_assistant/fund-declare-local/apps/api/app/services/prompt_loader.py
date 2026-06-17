from pathlib import Path

from app.services import local_store


class PromptLoader:
    def __init__(self, prompt_dir: str | None = None) -> None:
        self.prompt_dir = (
            Path(prompt_dir) if prompt_dir else local_store.PROJECT_ROOT / "prompts"
        )

    def load(self, prompt_name: str) -> str:
        prompt_path = self.prompt_dir / prompt_name
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt 文件不存在：{prompt_path}")

        if not prompt_path.is_file():
            raise FileNotFoundError(f"Prompt 路径不是文件：{prompt_path}")

        return prompt_path.read_text(encoding="utf-8")
