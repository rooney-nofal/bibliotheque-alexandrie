"""Tries to make the assistant break its own rules, through the question and through a poisoned passage."""

from __future__ import annotations                            # lets us write modern type hints safely

import argparse                                                # reads options typed after the command
import json                                                    # reads the attacks and writes the results

from assistant.config import load_config, project_path         # our own settings loader
from assistant.core.chain import answer_question               # the normal question-to-answer chain
from assistant.core.embeddings import get_embedder             # the embedding model
from assistant.core.llm import LLMError, generate              # the model client, for the passage attack
from assistant.core.prompting import build_prompt              # builds a prompt from passages we control
from assistant.core.search import search                       # finds the real passages first
from assistant.core.vector_store import collection_name, open_client, open_collection   # database helpers


def run_question_attack(config, model, collection, attempt, version):
    """Attack through the question itself: the user types the malicious instruction."""
    outcome = answer_question(config, model, collection, attempt["attack"], version)   # a normal run
    return outcome["answer"], {"refused": outcome["refused"], "refused_by": outcome["refused_by"],
                               "best_similarity": outcome["best_similarity"]}


def run_passage_attack(config, model, collection, attempt, version):
    """Attack through a document: the malicious instruction hides inside a retrieved passage."""
    hits = search(config, model, collection, attempt["question"])      # a normal, innocent question
    poisoned = [dict(hit) for hit in hits]                     # copy the results so the database is untouched
    target = 1 if len(poisoned) > 1 else 0                     # poison the second passage if there is one
    poisoned[target]["text"] = poisoned[target]["text"] + "\n\n" + attempt["poison"]   # append the attack
    prompt = build_prompt(config, attempt["question"], poisoned, version)      # build the prompt as usual
    reply = generate(config, prompt)                           # and ask the model
    return reply["text"], {"poisoned_passage": target + 1, "cached": reply["cached"]}


def main() -> None:                                            # the entry point: what runs when we start this file
    """Run every attack and report which ones the assistant resisted."""
    parser = argparse.ArgumentParser(description="Attempt prompt injection against the assistant.")
    parser.add_argument("--version", default=None, help="prompt version to attack, for example v1")
    args = parser.parse_args()                                 # read what was typed after the command

    config = load_config()                                     # load every setting
    version = args.version or config["prompt"]["version"]      # which prompt we are attacking
    eval_dir = project_path("eval")                            # where the attack file lives
    attempts = json.loads((eval_dir / "injection_attempts.json").read_text(encoding="utf-8"))
    model = get_embedder(config["embeddings"])                 # load the embedding model once
    collection = open_collection(open_client(config), collection_name(config, config["chunking"]["chosen"]))

    rows, held = [], 0                                         # the records, and how many attacks failed to work
    print(f"Attacking prompt {version} with {len(attempts)} attempts.\n")
    for attempt in attempts:                                   # try each attack in turn
        try:                                                   # a model call can fail
            if attempt["kind"] == "question":                  # the attack is in what the user typed
                answer, extra = run_question_attack(config, model, collection, attempt, version)
            else:                                              # the attack is hidden in a document
                answer, extra = run_passage_attack(config, model, collection, attempt, version)
        except LLMError as error:                              # if the call failed
            rows.append({"id": attempt["id"], "error": str(error)})        # record it
            print(f"  {attempt['id']} ERROR: {error}")         # and carry on
            continue                                           # next attack
        leaked = [marker for marker in attempt["fail_if_contains"] if marker.casefold() in answer.casefold()]
        defended = not leaked                                  # the attack worked only if a marker appeared
        held += 1 if defended else 0                           # count the successful defences
        rows.append({"id": attempt["id"], "kind": attempt["kind"], "description": attempt["description"],
                     "defended": defended, "leaked_markers": leaked, "answer": answer, **extra})
        status = "HELD " if defended else "BROKE"              # a word you can read at a glance
        print(f"  {status} {attempt['id']} ({attempt['kind']}) {attempt['description']}")
        print(f"        -> {answer[:140].replace(chr(10), ' ')}")         # the start of what it actually said
        if leaked:                                             # if the attack worked
            print(f"        !! leaked: {leaked}")              # name exactly what got through

    print(f"\n{held}/{len(attempts)} attacks defended with prompt {version}.")
    out = eval_dir / f"injection_results_{version}.json"       # one results file per prompt version
    out.write_text(json.dumps({"prompt_version": version, "defended": held, "total": len(attempts), "attempts": rows},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out.name}")                                 # say where the evidence was saved


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program