"""Runs the same questions through the hosted model and the local model, and records the comparison."""

from __future__ import annotations                            # lets us write modern type hints safely

import argparse                                                # reads options typed after the command
import copy                                                    # makes an independent copy of the settings
import json                                                    # reads the questions and writes the results

from assistant.config import load_config, project_path         # our own settings loader
from assistant.core.embeddings import get_embedder             # the embedding model, for searching
from assistant.core.llm import LLMError, generate              # the model client and its error type
from assistant.core.prompting import build_prompt              # builds the prompt from question and passages
from assistant.core.search import search                       # finds the passages
from assistant.core.vector_store import collection_name, open_client, open_collection   # the database helpers


def variant_config(config: dict, provider: str) -> dict:       # the same settings, pointed at one provider
    """Copy the settings and switch which model answers, without touching the original."""
    variant = copy.deepcopy(config)                            # an independent copy, so we change nothing shared
    variant["llm"]["provider"] = provider                      # hosted or local
    if provider == "local":                                    # the local model has its own name
        variant["llm"]["model"] = config["llm"]["local_model"] # so the cache and the report record it correctly
    return variant                                             # hand the adjusted settings back


def main() -> None:                                            # the entry point: what runs when we start this file
    """Ask both models the same questions and report speed, length and cost side by side."""
    parser = argparse.ArgumentParser(description="Compare the hosted model and the local model on the same questions.")
    parser.add_argument("--questions", type=int, default=5, help="how many test questions to use")
    args = parser.parse_args()                                 # read what was typed after the command

    config = load_config()                                     # load every setting
    if not config["llm"].get("local_model"):                   # the comparison needs both models named
        raise SystemExit("config.yaml: llm.local_model is empty. Set it before running the comparison.")
    if not config["chunking"].get("chosen"):                   # and it needs to know which index to search
        raise SystemExit("config.yaml: chunking.chosen is empty. Phase 3 should have set it.")
    size = config["chunking"]["chosen"]                        # the chunk size Phase 3 chose
    questions = json.loads((project_path("eval") / "questions.json").read_text(encoding="utf-8"))[: args.questions]

    model = get_embedder(config["embeddings"])                 # load the embedding model once
    collection = open_collection(open_client(config), collection_name(config, size))   # the passages to search

    records = []                                               # one record per question
    for item in questions:                                     # go through the test questions
        hits = search(config, model, collection, item["question"])      # find the best passages
        prompt = build_prompt(config, item["question"], hits)  # build the full prompt from them
        row = {"id": item["id"], "question": item["question"], "prompt_characters": len(prompt), "results": {}}
        for provider in ("openrouter", "local"):               # ask both models the identical prompt
            print(f"  {item['id']} -> {provider} ...", flush=True)      # show progress, as local is slow
            try:                                               # a model can fail for many reasons
                reply = generate(variant_config(config, provider), prompt)   # ask it
            except LLMError as error:                          # if it failed
                row["results"][provider] = {"error": str(error)}            # record why
                print(f"     FAILED: {error}")                 # and say so
                continue                                       # carry on with the other model
            row["results"][provider] = {                       # record everything worth comparing
                "model": reply["model"],                       # which model answered
                "seconds": round(reply["seconds"], 2),         # how long it took
                "cached": reply["cached"],                     # whether the cache answered instead
                "usage": reply["usage"],                       # how many tokens it used
                "answer": reply["text"],                       # what it actually wrote
            }
            print(f"     {reply['seconds']:.1f}s  {len(reply['text'])} chars")   # a short progress line
        records.append(row)                                    # keep this question's results

    print("\n" + "=" * 78)                                     # a separator before the summary
    print(f"{'provider':<12}{'avg seconds':>13}{'avg answer chars':>19}{'answers':>10}{'failures':>11}")
    summary = {}                                               # the averages, per provider
    for provider in ("openrouter", "local"):                   # summarise each one
        done = [r["results"][provider] for r in records if "error" not in r["results"][provider]]
        failed = len(records) - len(done)                      # how many questions it could not answer
        if done:                                               # if it answered at least one
            avg_s = sum(d["seconds"] for d in done) / len(done)             # average time
            avg_c = sum(len(d["answer"]) for d in done) / len(done)         # average answer length
        else:                                                  # if it answered none
            avg_s = avg_c = 0.0                                # report zeroes rather than crash
        summary[provider] = {"average_seconds": round(avg_s, 2), "average_answer_characters": round(avg_c), "answers": len(done), "failures": failed}
        print(f"{provider:<12}{avg_s:>13.2f}{avg_c:>19.0f}{len(done):>10}{failed:>11}")
    print("=" * 78)                                            # close the table

    out = project_path("eval") / "model_comparison.json"       # where the full results go
    out.write_text(json.dumps({"chunk_size": size, "prompt_version": config["prompt"]["version"], "summary": summary, "details": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out.name} - read the answers there to judge the French quality yourself.")


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program