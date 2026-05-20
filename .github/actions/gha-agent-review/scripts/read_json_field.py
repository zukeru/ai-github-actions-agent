#!/usr/bin/env python3
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: read_json_field.py <file> <field>", file=sys.stderr)
        return 2

    with open(sys.argv[1], "r", encoding="utf-8") as input_file:
        data = json.load(input_file)

    value = data
    for part in sys.argv[2].split("."):
        value = value[part]

    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

