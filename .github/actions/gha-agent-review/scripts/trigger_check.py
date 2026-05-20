#!/usr/bin/env python3
import argparse
import json
import os
import sys

from review_common import body_has_trigger, parse_trigger_phrases


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output_file:
            output_file.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def load_event(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as event_file:
        return json.load(event_file)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger-phrases", required=True)
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--comment-body")
    parser.add_argument("--is-pr", action="store_true")
    args = parser.parse_args()

    phrases = parse_trigger_phrases(args.trigger_phrases)

    if args.comment_body is not None:
        comment_body = args.comment_body
        is_pr = args.is_pr
    else:
        if not args.event_path:
            print("GITHUB_EVENT_PATH is not set and no --comment-body was provided", file=sys.stderr)
            return 2
        event = load_event(args.event_path)
        comment_body = (event.get("comment") or {}).get("body") or ""
        is_pr = bool((event.get("issue") or {}).get("pull_request"))

    should_run = is_pr and body_has_trigger(comment_body, phrases)
    write_output("should-run", "true" if should_run else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

