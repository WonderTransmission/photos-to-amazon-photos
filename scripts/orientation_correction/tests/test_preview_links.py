from pathlib import Path

from orientation_correction import preview_links


def test_write_preview_links_groups_by_directory(tmp_path):
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    corrected = [dir_a / "a.jpg", dir_a / "b.jpg", dir_b / "c.jpg"]

    written = preview_links.write_preview_links(
        tmp_path,
        corrected=corrected,
        would_correct=[],
        low_confidence=[],
        divider_dir=tmp_path / "dividers",
    )

    assert len(written) == 1
    output = written[0]
    assert output.name == "preview-links-corrected.sh"
    text = output.read_text()
    assert f'export DIR="{dir_a}"' in text
    assert f'export DIR="{dir_b}"' in text
    assert '"$DIR/a.jpg" "$DIR/b.jpg"' in text
    assert '"$DIR/c.jpg"' in text
    assert output.stat().st_mode & 0o111  # executable


def test_write_preview_links_writes_a_separate_file_per_category(tmp_path):
    d = tmp_path
    written = preview_links.write_preview_links(
        tmp_path,
        corrected=[d / "a.jpg"],
        would_correct=[d / "b.jpg"],
        low_confidence=[d / "c.jpg"],
        divider_dir=tmp_path / "dividers",
    )

    assert {p.name for p in written} == {
        "preview-links-corrected.sh",
        "preview-links-would-correct.sh",
        "preview-links-low-confidence.sh",
    }

    by_name = {p.name: p.read_text() for p in written}
    corrected_text = by_name["preview-links-corrected.sh"]
    would_correct_text = by_name["preview-links-would-correct.sh"]
    low_confidence_text = by_name["preview-links-low-confidence.sh"]

    # each file must only reference its own category's file -- no bleed-through between them
    assert '"$DIR/a.jpg"' in corrected_text
    assert '"$DIR/b.jpg"' not in corrected_text
    assert '"$DIR/c.jpg"' not in corrected_text

    assert '"$DIR/b.jpg"' in would_correct_text
    assert '"$DIR/a.jpg"' not in would_correct_text

    assert '"$DIR/c.jpg"' in low_confidence_text
    assert '"$DIR/a.jpg"' not in low_confidence_text


def test_write_preview_links_writes_nothing_when_nothing_flagged(tmp_path):
    written = preview_links.write_preview_links(
        tmp_path,
        corrected=[],
        would_correct=[],
        low_confidence=[],
        divider_dir=tmp_path / "dividers",
    )

    assert written == []
    assert list(tmp_path.glob("preview-links-*.sh")) == []
    assert not (tmp_path / "dividers").exists()  # nothing to divide, nothing written


def test_write_preview_links_omits_files_for_empty_categories(tmp_path):
    written = preview_links.write_preview_links(
        tmp_path,
        corrected=[tmp_path / "a.jpg"],
        would_correct=[],
        low_confidence=[],
        divider_dir=tmp_path / "dividers",
    )

    assert len(written) == 1
    assert written[0].name == "preview-links-corrected.sh"


def test_write_preview_links_opens_a_divider_image_first_in_each_group(tmp_path):
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    divider_dir = tmp_path / "dividers"

    written = preview_links.write_preview_links(
        tmp_path,
        corrected=[dir_a / "a.jpg"],
        would_correct=[dir_b / "b.jpg"],
        low_confidence=[],
        divider_dir=divider_dir,
    )

    dividers = sorted(divider_dir.glob("*.png"))
    assert len(dividers) == 2  # one per (category, directory) group

    for output in written:
        for line in output.read_text().splitlines():
            if line.startswith("open -a preview"):
                # the divider must be the FIRST path passed to `open`, so it's the first thing
                # Preview.app shows for that group
                first_arg = line.split('"')[1]
                assert first_arg.endswith(".png")
                assert Path(first_arg).exists()


def test_write_preview_links_divider_indices_are_unique_across_categories(tmp_path):
    d = tmp_path
    divider_dir = tmp_path / "dividers"
    preview_links.write_preview_links(
        tmp_path,
        corrected=[d / "a.jpg"],
        would_correct=[d / "b.jpg"],
        low_confidence=[d / "c.jpg"],
        divider_dir=divider_dir,
    )

    dividers = sorted(divider_dir.glob("*.png"))
    assert len(dividers) == 3
    assert len({p.name for p in dividers}) == 3


def test_write_review_checklist_lists_corrected_and_would_correct(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    output = tmp_path / "review.txt"

    wrote = preview_links.write_review_checklist(
        output, corrected=[a], would_correct=[b], revert_command="revert-cmd review.txt"
    )

    assert wrote is True
    text = output.read_text()
    assert str(a) in text
    assert str(b) in text
    assert "revert-cmd review.txt" in text


def test_write_review_checklist_excludes_low_confidence(tmp_path):
    """Low-confidence files were never actually rotated -- there's nothing to revert, so they
    don't belong on a false-positive review checklist."""
    a = tmp_path / "a.jpg"
    output = tmp_path / "review.txt"

    preview_links.write_review_checklist(
        output, corrected=[a], would_correct=[], revert_command="cmd"
    )

    assert str(a) in output.read_text()


def test_write_review_checklist_returns_false_and_writes_nothing_when_empty(tmp_path):
    output = tmp_path / "review.txt"

    wrote = preview_links.write_review_checklist(
        output, corrected=[], would_correct=[], revert_command="cmd"
    )

    assert wrote is False
    assert not output.exists()


def test_write_review_checklist_dedupes_overlap_between_corrected_and_would_correct(tmp_path):
    # Shouldn't happen in practice (a file is either corrected or would-correct, not both, in a
    # single run) but the checklist should be robust to it regardless.
    a = tmp_path / "a.jpg"
    output = tmp_path / "review.txt"

    preview_links.write_review_checklist(
        output, corrected=[a], would_correct=[a], revert_command="cmd"
    )

    assert output.read_text().count(str(a)) == 1
