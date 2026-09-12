"""One-time download of the linguistic resources the pipeline needs.

Run once per machine, before starting the server:

    python scripts/setup_resources.py

The old ``pronunciation_pipeline`` called ``nltk.download`` at *import* time,
so every server start reached out to the network and a transient failure there
took the whole application down with it. Resource acquisition belongs in a
setup step that can fail loudly and be retried, not in the request path.
"""

from __future__ import annotations

import os
import sys

REQUIRED = [
    ("corpora/cmudict", "cmudict"),
    ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
]


def download_model() -> int:
    """Fetch the acoustic model into the local HuggingFace cache.

    Run once per machine, with network access. Afterwards the server loads it
    offline, which is both faster and the right behaviour for a study machine:
    the model that scores an attempt should be the one that was validated.
    """
    os.environ["PRONUNCIATION_ALLOW_DOWNLOAD"] = "1"
    from app.services.pronunciation.runtime import build_config, get_model

    config = build_config()
    print(f"  fetching {config.model_id} (~1.2 GB on first run) ...")
    info = get_model().describe()
    print(f"  ready: {info.n_labels} labels, "
          f"{len(info.inventory)} mapped to ARPAbet")
    return 0


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
    import os
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if "--download-model" in sys.argv:
        raise SystemExit(download_model())
    raise SystemExit(main())
