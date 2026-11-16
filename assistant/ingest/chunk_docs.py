"""Cuts each downloaded page into passages that remember their document and their section."""

from __future__ import annotations                        # lets us write modern type hints safely

import argparse                                           # reads options typed after the command, like --size
import json                                               # reads the manifest and writes the passage files
import re                                                 # finds and replaces text patterns

from assistant.config import load_config, project_path    # our own settings loader

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")        # a Markdown heading: one to six # signs, then its title
FENCE_PATTERN = re.compile(r"^\s*```")                    # the ``` line that opens or closes a code block


def _iter_units(text: str):                               # splits a page into the smallest pieces we never cut
    """Walk the page and yield its pieces: headings, paragraphs, and whole code blocks."""
    lines = text.splitlines()                             # work line by line
    index = 0                                             # where we are in the page
    while index < len(lines):                             # until we reach the end
        line = lines[index]                               # the line we are looking at
        if FENCE_PATTERN.match(line):                     # a code block starts here
            start = index                                 # remember where it began
            index += 1                                    # step past the opening ```
            while index < len(lines) and not FENCE_PATTERN.match(lines[index]):   # walk to the closing ```
                index += 1                                # keep going
            index = min(index + 1, len(lines))            # include the closing line, without running off the end
            yield "code", "\n".join(lines[start:index])   # hand back the whole code block in one piece
            continue                                      # and carry on
        if HEADING_PATTERN.match(line):                   # a heading line
            yield "heading", line                         # hand it back on its own
            index += 1                                    # move to the next line
            continue                                      # and carry on
        if not line.strip():                              # a blank line separates paragraphs
            index += 1                                    # skip it
            continue                                      # and carry on
        start = index                                     # a paragraph starts here
        while index < len(lines) and lines[index].strip() and not FENCE_PATTERN.match(lines[index]) and not HEADING_PATTERN.match(lines[index]):
            index += 1                                    # keep reading until a blank line, a heading or a code block
        yield "text", "\n".join(lines[start:index])       # hand back the paragraph


def _overlap_tail(units: list[str], overlap: int) -> list[str]:   # the pieces repeated into the next passage
    """Take the last few pieces of a passage, up to the overlap budget, to start the next one."""
    tail, total = [], 0                                   # the pieces we will repeat, and their size so far
    for unit in reversed(units):                          # look at the passage backwards, newest first
        if total + len(unit) > overlap:                   # if adding this piece would exceed the budget
            break                                         # stop here
        tail.insert(0, unit)                              # otherwise keep it, in its original order
        total += len(unit)                                # and count its length
    return tail                                           # hand back what will open the next passage


def chunk_document(text: str, max_chars: int, overlap: int) -> list[dict]:   # cuts one page into passages
    """Cut one page into passages of about max_chars, never splitting a code block."""
    chunks, stack, current, current_len = [], [], [], 0   # finished passages, heading trail, passage being built, its size

    def section_label() -> str:                           # builds the section name from the heading trail
        return " > ".join(title for _, title in stack)    # for example: Query Parameters > Defaults

    def flush() -> None:                                  # closes the passage being built and stores it
        nonlocal current, current_len                     # we change the two variables defined just above
        body = "\n\n".join(current).strip()               # join its pieces with a blank line between them
        if body:                                          # only store it if it actually holds text
            chunks.append({"section": section_label(), "text": body, "characters": len(body)})
        current, current_len = [], 0                      # then start an empty passage

    for kind, content in _iter_units(text):               # go through the page piece by piece
        if kind == "heading":                             # a heading starts a new section
            flush()                                       # so close whatever passage was open
            match = HEADING_PATTERN.match(content)        # read the heading
            level, title = len(match.group(1)), match.group(2).strip()   # how deep it is, and its title
            while stack and stack[-1][0] >= level:        # drop any heading at the same depth or deeper
                stack.pop()                               # because this new one replaces it
            stack.append((level, title))                  # then record the new heading
            continue                                      # and move to the next piece
        if current and current_len + len(content) > max_chars:   # this piece would make the passage too long
            tail = _overlap_tail(current, overlap)        # remember the last pieces, to repeat them
            flush()                                       # close the passage as it stands
            current = list(tail)                          # open the next one with the repeated pieces
            current_len = sum(len(unit) for unit in current)     # and count their length
        current.append(content)                           # add this piece to the passage
        current_len += len(content)                       # and count it
    flush()                                               # close the last passage of the page
    return chunks                                         # hand them all back


def main() -> None:                                       # the entry point: what runs when we start this file
    """Cut every downloaded page into passages, once for each chunk size we want to compare."""
    parser = argparse.ArgumentParser(description="Cut the downloaded pages into passages, once per chunk size.")
    parser.add_argument("--size", type=int, default=None, help="chunk only this size instead of every size in config")
    args = parser.parse_args()                            # read what was typed after the command

    config = load_config()                                # load every setting
    corpus, chunking = config["corpus"], config["chunking"]      # keep the two sections we need
    raw_dir = project_path(corpus["raw_dir"])             # where the downloaded pages are
    processed_dir = project_path(corpus["processed_dir"])  # where the passages will go
    processed_dir.mkdir(parents=True, exist_ok=True)      # create that folder if it is missing

    manifest = json.loads(project_path(corpus["manifest"]).read_text(encoding="utf-8"))   # the list of pages
    sizes = [args.size] if args.size else chunking["sizes_to_test"]    # one size, or every size to compare
    overlap = chunking["overlap"]                         # how much text neighbouring passages share

    for size in sizes:                                    # do the whole corpus once per size
        records, oversize = [], 0                         # the passages, and how many exceeded the target
        for entry in manifest:                            # go through every page
            text = (raw_dir / entry["file"]).read_text(encoding="utf-8")   # read it from disk
            for position, chunk in enumerate(chunk_document(text, size, overlap)):   # cut it into passages
                if chunk["characters"] > size:            # a single code block can be longer than the target
                    oversize += 1                         # count it, rather than cutting the code in half
                records.append({                          # record everything the search step will need
                    "chunk_id": f"{entry['file'][:-3]}#{position:03d}",   # a unique name, page plus position
                    "url": entry["url"],                  # the page's public address, for citing
                    "title": entry["title"],              # the page's title
                    "file": entry["file"],                # the file it came from
                    "section": chunk["section"],          # the section it belongs to, as the brief requires
                    "text": chunk["text"],                # the passage itself
                    "characters": chunk["characters"],    # its length
                })
        out_path = processed_dir / f"chunks_{size}.jsonl"  # one file per size
        with out_path.open("w", encoding="utf-8") as handle:        # open it for writing
            for record in records:                        # and write one passage per line
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        lengths = sorted(record["characters"] for record in records)   # all the passage lengths, in order
        median = lengths[len(lengths) // 2]               # the middle one
        print(f"size {size:>5}: {len(records):5} passages, median {median} chars, {oversize} oversize (single code blocks) -> {out_path.name}")


if __name__ == "__main__":                                # only run main() when started directly
    main()                                                # start the program