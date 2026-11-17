"""Builds the prompt sent to the model: the rules, the retrieved passages, and the question."""

from __future__ import annotations                            # lets us write modern type hints safely

from assistant.config import project_path                      # turns a config path into a real one

REFUSAL = "Je ne sais pas."                                    # the exact words the model must use when unsure


def load_template(config: dict, version: str | None = None) -> str:
    """Read one prompt version from the prompts/ folder, so prompts live in Git, not in the code."""
    settings = config["prompt"]                                # the prompt section of the settings
    name = version or settings["version"]                      # the version asked for, or the one in config
    path = project_path(settings["dir"]) / f"{name}.md"        # for example prompts/v1.md
    if not path.exists():                                      # if that version does not exist
        raise FileNotFoundError(f"prompt template not found: {path}")   # say which file is missing
    return path.read_text(encoding="utf-8")                    # hand the template back


def format_passages(hits: list[dict]) -> str:
    """Lay the retrieved passages out as a numbered list the model can cite by number."""
    blocks = []                                                # one block of text per passage
    for position, hit in enumerate(hits, start=1):             # number them from 1, so the model can write [1]
        section = hit["section"]                               # where the passage sits inside its page
        label = section if section.startswith(hit["title"]) else f"{hit['title']} > {section}"
        blocks.append(f"[{position}] {label}\nSource : {hit['url']}\n{hit['text']}")
    return "\n\n".join(blocks)                                 # join them with a blank line between


def build_prompt(config: dict, question: str, hits: list[dict], version: str | None = None) -> str:
    """Fill the chosen template with the passages and the question."""
    template = load_template(config, version)                  # the rules, with two gaps to fill
    return template.replace("{passages}", format_passages(hits)).replace("{question}", question)