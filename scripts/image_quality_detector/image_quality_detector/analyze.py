"""CleanVision-based quality classification: totally overexposed ("light"), totally underexposed
("dark"), and extremely blurry ("blurry"). Uses CleanVision's own is_*_issue flags and default
thresholds rather than our own score cutoffs -- on a sample run those defaults already came back
conservative (2 blurry flags out of 187 real photos, 0 dark/light), matching what "totally" /
"extremely" call for rather than catching borderline cases.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from cleanvision import Imagelab
from PIL import Image

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

log = logging.getLogger(__name__)

CATEGORIES = ("blurry", "dark", "light")
DEFAULT_ISSUE_TYPES = {"blurry": {}, "dark": {}, "light": {}}


@dataclass(frozen=True)
class QualityResult:
    path: Path
    matched: frozenset[str]  # subset of CATEGORIES

    @property
    def has_issue(self) -> bool:
        return bool(self.matched)

    @property
    def category_key(self) -> str:
        """e.g. 'blurry', or 'dark+light' for an image flagged under multiple categories --
        used both as the quarantine subdirectory name and the preview-links grouping key."""
        return "+".join(sorted(self.matched))


def _verify_loadable(path: Path) -> Exception | None:
    """CleanVision doesn't report per-file decode failures back to the caller, so we check
    ourselves first and only hand it files we already know PIL can open -- keeping the same
    "one corrupt file doesn't abort the run, just gets logged" guarantee the rest of this
    pipeline relies on."""
    try:
        with Image.open(path) as img:
            img.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure is reported, not fatal
        return exc
    return None


def analyze_images(
    paths: list[Path],
    issue_types: dict | None = None,
    *,
    n_jobs: int = 1,
) -> tuple[list[QualityResult], list[tuple[Path, Exception]]]:
    """Runs CleanVision issue detection over `paths`. Returns (results, errors) where errors are
    files that failed to even decode (skipped before reaching CleanVision)."""
    issue_types = issue_types if issue_types is not None else DEFAULT_ISSUE_TYPES
    categories = [c for c in CATEGORIES if c in issue_types]

    valid: list[Path] = []
    errors: list[tuple[Path, Exception]] = []
    for path in paths:
        exc = _verify_loadable(path)
        if exc is None:
            valid.append(path)
        else:
            errors.append((path, exc))

    if not valid:
        return [], errors

    log.info("Analyzing %d image(s) for quality issues (%s)...", len(valid), ", ".join(categories))
    imagelab = Imagelab(filepaths=[str(p) for p in valid], verbose=False)
    imagelab.find_issues(issue_types=issue_types, n_jobs=n_jobs, verbose=False)
    df = imagelab.issues

    results = [
        QualityResult(
            path=path,
            matched=frozenset(c for c in categories if bool(df.loc[str(path), f"is_{c}_issue"])),
        )
        for path in valid
    ]
    return results, errors
