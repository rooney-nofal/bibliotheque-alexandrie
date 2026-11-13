"""Downloads the documentation pages listed in the site's navigation and records a manifest."""

from __future__ import annotations                       # lets us write modern type hints safely

import argparse                                          # reads options typed after the command, like --limit
import hashlib                                           # makes a fingerprint of each page's text
import json                                              # writes the manifest in JSON format
import re                                                # finds and replaces text patterns
import time                                              # lets us pause between downloads
from datetime import datetime, timezone                  # records when each page was fetched

import requests                                          # downloads files over HTTPS
import yaml                                              # parses the navigation block we extract

from assistant.config import load_config, project_path   # our own settings loader

# A code include written by the documentation authors, for example: {* ../../docs_src/body/tutorial001.py hl[2] *}
INCLUDE_PATTERN = re.compile(r"\{\*\s*(\S+)([^*\n]*)\*\}")
# An optional line range inside that include, for example: ln[15:17]
LINE_RANGE_PATTERN = re.compile(r"ln\[(\d+):(\d+)\]")
# A heading anchor the authors add, for example: # First Steps { #first-steps }
ANCHOR_PATTERN = re.compile(r"\s*\{\s*#[\w\-]+\s*\}")
# A settings block some pages open with, between two lines of three dashes
FRONT_MATTER_PATTERN = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
# A style or script block, deleted together with everything inside it
STYLE_BLOCK_PATTERN = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
# A coloured note box, for example: /// tip   or   /// note | Technical Details
ADMONITION_OPEN = re.compile(r"^/{3,}\s*(\w+)\s*\|?\s*(.*)$")
# Leftover formatting tags that carry no meaning once the page is plain text
HTML_TAG_PATTERN = re.compile(
    r"</?(?:div|span|font|a|img|br|abbr|p|u|b|i|em|strong|small|sup|sub|details|summary|table|tr|td|th|thead|tbody|blockquote)\b[^>]*>"
)
# Which code fence language to use, based on the file extension of an included example
CODE_LANGUAGES = {"py": "python", "sh": "console", "json": "json", "yaml": "yaml", "yml": "yaml", "md": "markdown", "html": "html", "txt": ""}


def _collect_md_paths(node, found: list[str]) -> None:    # walks the navigation tree and collects page paths
    """Walk the nested navigation structure and gather every .md path into 'found'."""
    if isinstance(node, str):                             # if this piece is a piece of text
        if node.endswith(".md"):                          # and that text names a documentation page
            found.append(node)                            # keep it
    elif isinstance(node, list):                          # if this piece is a list of entries
        for item in node:                                 # look at each entry in turn
            _collect_md_paths(item, found)                # and search inside it the same way
    elif isinstance(node, dict):                          # if this piece is a named group
        for value in node.values():                       # look at what each name contains
            _collect_md_paths(value, found)               # and search inside it the same way


def _path_to_url(md_path: str, base_url: str) -> str:     # turns "tutorial/body.md" into its address on the site
    """Convert a documentation file path into the public URL of that page."""
    slug = md_path[:-3]                                   # drop the last three characters, ".md"
    if slug == "index":                                   # the site's front page is a special case
        slug = ""                                         # it lives at the base address with nothing after it
    elif slug.endswith("/index"):                         # a section's front page, like "learn/index"
        slug = slug[: -len("/index")]                     # becomes just the section name, "learn"
    return base_url + (slug + "/" if slug else "")        # join base address and slug, ending with a slash


def _path_to_filename(md_path: str) -> str:               # turns "tutorial/body.md" into a flat file name
    """Build a safe flat filename so every page can live in one folder."""
    return md_path[:-3].replace("/", "__") + ".md"        # replace each slash with a double underscore


def discover_pages(corpus: dict) -> list[dict]:           # finds every page the site lists in its navigation
    """Read the site's navigation file and return the pages we want, with their URLs."""
    response = requests.get(corpus["nav_url"], timeout=30)             # download the navigation file
    response.raise_for_status()                                        # stop with a clear error if it failed
    lines = response.text.splitlines()                                 # split the file into a list of lines
    start = next(i for i, line in enumerate(lines) if line.rstrip() == "nav:")   # find the line opening the navigation
    end = len(lines)                                                   # assume it runs to the end, for now
    for i in range(start + 1, len(lines)):                             # then look at each line after it
        line = lines[i]                                                # take that line
        if line.strip() and not line[0].isspace() and not line.lstrip().startswith("-"):   # a new top-level setting
            end = i                                                    # so the navigation stops just before it
            break                                                      # and we stop looking
    nav = yaml.safe_load("\n".join(lines[start:end]))["nav"]           # parse only that block, safely
    md_paths: list[str] = []                                           # prepare an empty list for the page paths
    _collect_md_paths(nav, md_paths)                                   # fill it by walking the navigation
    excluded = tuple(section + "/" for section in corpus["exclude_sections"])    # sections to skip, as path prefixes
    skipped = set(corpus["exclude_pages"])                             # individual pages to skip
    pages, seen = [], set()                                            # the result list, and what we already added
    for md_path in md_paths:                                           # go through every page the navigation listed
        if md_path.startswith(excluded) or md_path in skipped or md_path in seen:   # skip excluded and duplicates
            continue                                                   # move on to the next one
        seen.add(md_path)                                              # remember that we have handled this page
        pages.append({                                                 # record what the fetching step needs
            "source_path": md_path,                                    # the page's path inside the documentation
            "url": _path_to_url(md_path, corpus["base_url"]),          # its public address, which we will cite
            "file": _path_to_filename(md_path),                        # the flat name we will save it under
        })
    return pages                                                       # hand the list back to the caller


def _resolve_includes(text: str, corpus: dict, session: requests.Session, cache: dict) -> str:
    """Replace every {* file *} placeholder with the real code, fetched once and reused."""
    def replace(match: re.Match) -> str:                               # called for each placeholder found
        relative = re.sub(r"^(\.\./)+", "", match.group(1))            # drop the leading ../ steps from the path
        url = corpus["repo_raw_base"] + relative                       # build the address of the code file
        if url not in cache:                                           # if we have not downloaded it before
            reply = session.get(url, timeout=30)                       # download it now
            cache[url] = reply.text if reply.status_code == 200 else ""   # remember it, or remember the failure
        code = cache[url]                                              # take the code out of the cache
        if not code:                                                   # if the file could not be downloaded
            return ""                                                  # leave nothing in its place
        span = LINE_RANGE_PATTERN.search(match.group(2))               # does the placeholder ask for some lines only?
        if span:                                                       # if it does
            code = "\n".join(code.splitlines()[int(span.group(1)) - 1 : int(span.group(2))])   # keep that range
        language = CODE_LANGUAGES.get(relative.rsplit(".", 1)[-1], "")  # choose the fence language from the extension
        return f"```{language}\n{code.rstrip()}\n```"                  # return the code as a fenced block
    return INCLUDE_PATTERN.sub(replace, text)                          # apply that to every placeholder in the page


def _clean_markdown(text: str) -> str:                                 # removes everything that is not readable content
    """Strip front matter, note boxes, anchors and leftover tags, leaving plain Markdown."""
    text = FRONT_MATTER_PATTERN.sub("", text)                          # remove the settings block some pages open with
    text = STYLE_BLOCK_PATTERN.sub("", text)                           # remove style and script blocks entirely
    text = ANCHOR_PATTERN.sub("", text)                                # remove the { #anchor } suffix from headings
    kept = []                                                          # the lines we decide to keep
    for line in text.splitlines():                                     # look at the page one line at a time
        stripped = line.strip()                                        # the same line without surrounding spaces
        if re.fullmatch(r"/{3,}", stripped):                           # a line of slashes closes a note box
            continue                                                   # so drop it
        opening = ADMONITION_OPEN.match(stripped)                      # does this line open a note box?
        if opening:                                                    # if it does
            kind = opening.group(1).capitalize()                       # the kind of box, such as Tip or Warning
            label = opening.group(2).strip()                           # an optional title after the | sign
            kept.append(f"**{kind}: {label}**" if label else f"**{kind}**")   # keep it as a bold label
            continue                                                   # and move to the next line
        kept.append(line)                                              # any other line is kept as it is
    text = "\n".join(kept)                                             # put the kept lines back together
    text = HTML_TAG_PATTERN.sub("", text)                              # delete leftover formatting tags
    text = re.sub(r"\n{3,}", "\n\n", text)                             # squeeze runs of blank lines down to one
    return text.strip()                                                # trim the edges and return


def fetch_page(page: dict, corpus: dict, session: requests.Session, cache: dict) -> tuple[str, str]:
    """Download one documentation page and return its title and clean Markdown text."""
    response = session.get(corpus["source_base"] + page["source_path"], timeout=30)   # download the page source
    response.raise_for_status()                                        # stop with a clear error if it failed
    text = _clean_markdown(_resolve_includes(response.text, corpus, session, cache))  # inline code, then clean up
    first = text.splitlines()[0] if text else ""                       # the first line of the cleaned page
    title = first.lstrip("# ").strip() if first.startswith("#") else page["source_path"]   # its heading, or a fallback
    return title, text                                                 # give both back to the caller


def main() -> None:                                                    # the entry point: what runs when we start this file
    """Fetch every selected page, save it to disk, and write the manifest."""
    parser = argparse.ArgumentParser(description="Download the documentation corpus listed in the site's navigation.")
    parser.add_argument("--limit", type=int, default=None, help="fetch only the first N pages, for a quick test")
    args = parser.parse_args()                                         # read what was typed after the command

    corpus = load_config()["corpus"]                                   # load settings and keep only the corpus section
    raw_dir = project_path(corpus["raw_dir"])                          # the full path to data/raw on this machine
    raw_dir.mkdir(parents=True, exist_ok=True)                         # create it if missing, without complaining

    pages = discover_pages(corpus)                                     # find every page we want to download
    print(f"Discovered {len(pages)} pages in the navigation.")         # tell the user what we found
    if args.limit:                                                     # if this is a test run
        pages = pages[: args.limit]                                    # keep only the first few pages
        print(f"TEST RUN: fetching only the first {len(pages)}.")      # and say so clearly

    session = requests.Session()                                       # one reusable connection for every download
    session.headers.update({"User-Agent": corpus["user_agent"]})       # identify our script honestly on every request
    code_cache: dict[str, str] = {}                                    # code examples already downloaded, kept for reuse
    manifest, failures, skipped = [], [], []                           # what succeeded, what failed, what was too short

    for position, page in enumerate(pages, start=1):                   # go through the pages, counting from 1
        try:                                                           # try to download this one
            title, text = fetch_page(page, corpus, session, code_cache)   # fetch, inline its code, and clean it
        except Exception as error:                                     # if anything went wrong
            failures.append((page["source_path"], str(error)))         # remember the failure
            print(f"  [{position}/{len(pages)}] FAILED {page['source_path']} -> {error}")   # report it
            continue                                                   # and carry on with the next page
        if len(text) < corpus["min_page_characters"]:                  # if the page is only a navigation stub
            skipped.append(page["source_path"])                        # remember that we skipped it
            print(f"  [{position}/{len(pages)}] skipped (only {len(text)} chars) {page['source_path']}")
            continue                                                   # and do not save it
        (raw_dir / page["file"]).write_text(text, encoding="utf-8")    # save the clean text to disk
        manifest.append({                                              # record everything we know about this page
            "url": page["url"],                                        # the address we fetched, and will cite
            "source_path": page["source_path"],                        # its path inside the documentation
            "file": page["file"],                                      # the file we saved it as
            "title": title,                                            # its heading
            "characters": len(text),                                   # how much text it holds
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),   # a fingerprint of the exact content
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),   # when we fetched it, in UTC
        })
        print(f"  [{position}/{len(pages)}] {title}  ({len(text)} chars)")   # show progress
        time.sleep(corpus["request_delay_seconds"])                    # pause before the next page, to stay polite

    if args.limit is None:                                             # on a full run only, never on a test run
        wanted = {entry["file"] for entry in manifest}                 # the files this run produced
        for stale in sorted(raw_dir.glob("*.md")):                     # look at every file already in the folder
            if stale.name not in wanted:                               # if this run did not produce it
                stale.unlink()                                         # delete it, so removed pages do not linger
                print(f"  removed stale file {stale.name}")            # and say so

    manifest_path = project_path(corpus["manifest"])                   # where the manifest file goes
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")   # write it
    total = sum(entry["characters"] for entry in manifest)             # the size of the whole corpus
    print(f"\nSaved {len(manifest)} pages ({total} characters) to {raw_dir}")        # final summary
    print(f"Wrote {manifest_path.name}. Code examples downloaded: {len(code_cache)}.")   # and what it cost
    if skipped:                                                        # if some pages were too short
        print(f"Skipped {len(skipped)} page(s) under {corpus['min_page_characters']} characters: {', '.join(skipped)}")
    if failures:                                                       # if some pages failed outright
        print(f"{len(failures)} page(s) failed: {', '.join(path for path, _ in failures)}")
    if args.limit is None and len(manifest) < corpus["min_pages"]:     # on a full run, check the brief's minimum
        raise SystemExit(f"ERROR: only {len(manifest)} pages collected, below the required {corpus['min_pages']}.")


if __name__ == "__main__":                                             # only run main() when started directly
    main()                                                             # start the program