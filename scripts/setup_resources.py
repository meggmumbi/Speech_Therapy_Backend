"""One-time download of the linguistic resources the pipeline needs.

Run once per machine, before starting the server:

    python scripts/setup_resources.py

The old ``pronunciation_pipeline`` called ``nltk.download`` at *import* time,
so every server start reached out to the network and a transient failure there
took the whole application down with it. Resource acquisition belongs in a
setup step that can fail loudly and be retried, not in the request path.
"""

from __future__ import annotations

import sys

REQUIRED = [
    ("corpora/cmudict", "cmudict"),
    ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
]


def main() -> int:
    import nltk

    failed: list[str] = []
    for path, package in REQUIRED:
        try:
            nltk.data.find(path)
            print(f"  present  {package}")
        except LookupError:
            print(f"  fetching {package} ...")
            if not nltk.download(package, quiet=True):
                failed.append(package)
                print(f"  FAILED   {package}")

    if failed:
        print(f"\nCould not install: {', '.join(failed)}")
        return 1

    # Verify the pipeline can actually reach them, rather than trusting the
    # download step's own report.
    from app.services.pronunciation import pronunciations

    variants = pronunciations("draught")
    if not variants:
        print("\nCMUdict installed but lookup returned nothing.")
        return 1
    print(f"\nAll resources ready. draught -> {' '.join(variants[0])}")
    return 0


if __name__ == "__main__":
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
