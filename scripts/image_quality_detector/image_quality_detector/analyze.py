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

# Per-image checks: CleanVision scores each file independently, so a single flagged file is the
# unit of action.
CATEGORIES = ("blurry", "dark", "light")

# Set-based checks: CleanVision flags every member of a matching group of files, not one
# offending file -- there's no single file to act on until something decides which member(s) of
# the group to keep. See analyze_images' `duplicate_sets` return value; cli.py does that
# reduction (keep the first by sorted path, quarantine the rest).
DUPLICATE_CATEGORIES = ("exact_duplicates", "near_duplicates")

ALL_CHECKS = CATEGORIES + DUPLICATE_CATEGORIES
DEFAULT_CHECKS = CATEGORIES


@dataclass(frozen=True)
class QualityResult:
    path: Path
    matched: frozenset[str]  # subset of CATEGORIES -- never includes DUPLICATE_CATEGORIES

    @property
    def has_issue(self) -> bool:
        return bool(self.matched)

    @property
    def category_key(self) -> str:
        """e.g. 'blurry', or 'dark+light' for an image flagged under multiple categories --
        used both as the quarantine subdirectory name and the preview-links grouping key.
        Reflects only the per-image checks in `matched`; duplicate-set membership is handled
        separately by the caller (see analyze_images)."""
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


DuplicateSets = dict[str, list[list[Path]]]


def analyze_images(
    paths: list[Path],
    checks: tuple[str, ...] = DEFAULT_CHECKS,
    *,
    n_jobs: int = 1,
) -> tuple[list[QualityResult], DuplicateSets, list[tuple[Path, Exception]]]:
    """Runs CleanVision issue detection over `paths` for the given `checks` (any of ALL_CHECKS).
    Returns (results, duplicate_sets, errors):

    - results: one QualityResult per successfully-decoded path, `matched` covering only the
      per-image checks in `checks` (CATEGORIES) -- never DUPLICATE_CATEGORIES.
    - duplicate_sets: {category: [[path, path, ...], ...]} for each requested category in
      DUPLICATE_CATEGORIES that found at least one group -- every path in a group matched that
      check against every other path in the same group. It's up to the caller to decide what
      "flagged" means for a group (e.g. keep one member, treat the rest as flagged).
    - errors: files that failed to even decode, skipped before reaching CleanVision.
    """
    issue_types = {c: {} for c in checks}
    categories = [c for c in CATEGORIES if c in checks]
    duplicate_categories = [c for c in DUPLICATE_CATEGORIES if c in checks]

    valid: list[Path] = []
    errors: list[tuple[Path, Exception]] = []
    for path in paths:
        exc = _verify_loadable(path)
        if exc is None:
            valid.append(path)
        else:
            errors.append((path, exc))

    if not valid:
        return [], {}, errors

    log.info("Analyzing %d image(s) for quality issues (%s)...", len(valid), ", ".join(checks))
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

    path_by_str = {str(p): p for p in valid}
    duplicate_sets: DuplicateSets = {}
    for dup_category in duplicate_categories:
        groups = imagelab.info.get(dup_category, {}).get("sets", [])
        if groups:
            duplicate_sets[dup_category] = [[path_by_str[s] for s in group] for group in groups]

    return results, duplicate_sets, errors
