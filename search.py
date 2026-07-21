#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path


def search_txt_files(folder_path, words, match_all=False, exempts=None, case_sensitive=False, recursive=False):
    folder = Path(folder_path)

    if not folder.is_dir():
        raise NotADirectoryError(f"'{folder_path}' is not a valid directory.")

    pattern = "**/*.txt" if recursive else "*.txt"
    txt_files = sorted(folder.glob(pattern))

    if not txt_files:
        print(f"No .txt files found in '{folder_path}'.", file=sys.stderr)
        return []

    search_words = [word if case_sensitive else word.lower() for word in words]
    results = []

    for txt_file in txt_files:
        try:
            with open(txt_file, "r", encoding="utf-8", errors="replace") as f:
                # search text file line by line for any of the search words
                for line_number, line in enumerate(f, start=1):
                    haystack = line if case_sensitive else line.lower()

                    if match_all:
                        if all(search_word in haystack for search_word in search_words):
                            if exempts:
                                if any(exempt in haystack for exempt in exempts):
                                    continue  # Skip this line if it contains any exempt word

                            results.append({
                                "file": str(txt_file),
                                "line_number": line_number,
                                "line": line.rstrip("\n"),
                            })
                    else:
                        if any(search_word in haystack for search_word in search_words):
                            
                            if exempts:
                                if any(exempt in haystack for exempt in exempts):
                                    continue  # Skip this line if it contains any exempt word

                            results.append({
                                "file": str(txt_file),
                                "line_number": line_number,
                                "line": line.rstrip("\n"),
                            })
        except OSError as e:
            print(f"Could not read '{txt_file}': {e}", file=sys.stderr)

    return results

def main():
    parser = argparse.ArgumentParser(
        description="Search .txt files in a folder for lines containing a given word."
    )
    parser.add_argument("folder", help="Path to the folder containing .txt files")
    parser.add_argument("words", nargs="+", help="Word (or substring) to search for")

    # add optional argument to make multiple words needed to match one line before returning
    parser.add_argument(
        "-m", "--match-all",
        action="store_true",
        help="Require all search words to be present in a line for it to match (default: any word matches)",
    )

    parser.add_argument(
        "-e", "--exempt",
        nargs="+",             # Accepts one or more exempt words
        default=[],
        help="Exempt results containing these words (or substrings)"
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Perform a case-sensitive search (default: case-insensitive)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Also search .txt files in subfolders",
    )

    args = parser.parse_args()

    if args.exempt:
        print(f"Exempting lines containing '{args.exempt}' from results.")

        results = search_txt_files(
            args.folder, args.words, args.match_all, args.exempt, args.case_sensitive, args.recursive
        )
    else:
        results = search_txt_files(
            args.folder, args.words, args.match_all, args.case_sensitive, args.recursive
        )

    if not results:
        print(f"No matches found for '{args.words}'.")
        return

    print(f"Found {len(results)} matching line(s) for '{args.words}':\n")
    for r in results:
        print(f"{r['file']} (line {r['line_number']}): {r['line']}")


if __name__ == "__main__":
    main()