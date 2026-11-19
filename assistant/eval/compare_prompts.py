"""Runs every test question through each prompt version and scores them on three criteria."""

from __future__ import annotations                            # lets us write modern type hints safely

import argparse                                                # reads options typed after the command
import json                                                    # reads the questions and writes the results

from assistant.config import load_config, project_path         # our own settings loader
from assistant.core.chain import answer_question               # the full question-to-answer chain
from assistant.core.embeddings import get_embedder             # the embedding model
from assistant.core.llm import LLMError                        # so one failure does not stop the run
from assistant.core.vector_store import collection_name, open_client, open_collection   # database helpers


def load_questions(eval_dir):                                  # both question sets, labelled
    """Load the answerable and unanswerable questions, marking what each one should do."""
    answerable = json.loads((eval_dir / "questions.json").read_text(encoding="utf-8"))
    unanswerable = json.loads((eval_dir / "questions_unanswerable.json").read_text(encoding="utf-8"))
    for item in answerable:                                    # the 20 real questions
        item["should_answer"] = True                           # the assistant ought to answer these
    for item in unanswerable:                                  # the 5 impostors
        item["should_answer"] = False                          # the assistant ought to refuse these
    return answerable + unanswerable                           # one list of 25


def main() -> None:                                            # the entry point: what runs when we start this file
    """Ask every question with every prompt version and report how each version behaved."""
    parser = argparse.ArgumentParser(description="Compare prompt versions on the full question set.")
    parser.add_argument("--versions", nargs="+", default=["v1", "v2"], help="prompt versions to compare")
    args = parser.parse_args()                                 # read what was typed after the command

    config = load_config()                                     # load every setting
    eval_dir = project_path("eval")                            # where the question files live
    questions = load_questions(eval_dir)                       # all 25, labelled
    model = get_embedder(config["embeddings"])                 # load the embedding model once
    collection = open_collection(open_client(config), collection_name(config, config["chunking"]["chosen"]))

    results = {}                                               # the rows, one list per prompt version
    for version in args.versions:                              # test each prompt version in turn
        print(f"\n=== prompt {version} ===")                   # announce which one we are on
        rows = []                                              # this version's results
        for item in questions:                                 # go through all 25 questions
            try:                                               # a model call can fail
                outcome = answer_question(config, model, collection, item["question"], version)
            except LLMError as error:                          # if it did
                rows.append({"id": item["id"], "should_answer": item["should_answer"], "error": str(error)})
                print(f"  {item['id']} FAILED: {error}")       # report it and carry on
                continue                                       # next question
            correct = outcome["refused"] != item["should_answer"]   # refused an impostor, or answered a real one
            rows.append({                                      # record everything worth comparing
                "id": item["id"], "question": item["question"], "should_answer": item["should_answer"],
                "refused": outcome["refused"], "refused_by": outcome["refused_by"], "correct_decision": correct,
                "citations": outcome["citations"], "warnings": outcome["warnings"],
                "seconds": outcome["seconds"], "cached": outcome["cached"], "answer": outcome["answer"],
            })
            mark = "ok " if correct else "XX "                 # a visible flag for wrong decisions
            print(f"  {mark}{item['id']} refused={str(outcome['refused']):<5} cites={outcome['citations']['valid']} {outcome['seconds']}s")
        results[version] = rows                                # keep this version's rows

    print("\n" + "=" * 92)                                     # a separator before the table
    print(f"{'prompt':<8}{'correct refusals':>18}{'wrong refusals':>17}{'answers cited':>16}{'invented cites':>17}{'avg s':>9}")
    summary = {}                                               # the scores, per version
    for version, rows in results.items():                      # summarise each version
        done = [r for r in rows if "error" not in r]           # the questions that completed
        should_refuse = [r for r in done if not r["should_answer"]]     # the 5 impostors
        should_answer = [r for r in done if r["should_answer"]]         # the 20 real questions
        correct_refusals = sum(1 for r in should_refuse if r["refused"])        # criterion 1
        wrong_refusals = sum(1 for r in should_answer if r["refused"])          # the cost of criterion 1
        answered = [r for r in should_answer if not r["refused"]]       # the ones it actually answered
        cited = sum(1 for r in answered if r["citations"]["valid"])     # criterion 2
        invented = sum(1 for r in done if r["citations"]["invalid"])    # the serious failure
        avg = sum(r["seconds"] for r in done) / len(done) if done else 0.0      # average time
        summary[version] = {                                   # the numbers, saved for the README
            "correct_refusals": f"{correct_refusals}/{len(should_refuse)}",
            "wrong_refusals": f"{wrong_refusals}/{len(should_answer)}",
            "answers_with_valid_citation": f"{cited}/{len(answered)}",
            "answers_with_invented_citation": invented,
            "average_seconds": round(avg, 2),
            "failures": len(rows) - len(done),
        }
        cells = [version, f"{correct_refusals}/{len(should_refuse)}", f"{wrong_refusals}/{len(should_answer)}",
                 f"{cited}/{len(answered)}", str(invented), f"{avg:.2f}"]        # the row, as text
        print(f"{cells[0]:<8}{cells[1]:>18}{cells[2]:>17}{cells[3]:>16}{cells[4]:>17}{cells[5]:>9}")
    print("=" * 92)                                            # close the table

    out = eval_dir / "prompt_comparison.json"                  # where the full results go
    out.write_text(json.dumps({"summary": summary, "details": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out.name}")                               # say where the evidence was saved
    print("Criterion 3 (usefulness of the French answer) is yours to judge - read the answers in that file.")


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program