from orientation_correction import preview_links


def test_write_preview_links_groups_by_directory(tmp_path):
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    corrected = [dir_a / "a.jpg", dir_a / "b.jpg", dir_b / "c.jpg"]

    output = tmp_path / "preview-links.sh"
    preview_links.write_preview_links(
        output, corrected=corrected, would_correct=[], low_confidence=[]
    )

    text = output.read_text()
    assert f'export DIR="{dir_a}"' in text
    assert f'export DIR="{dir_b}"' in text
    assert '"$DIR/a.jpg" "$DIR/b.jpg"' in text
    assert '"$DIR/c.jpg"' in text
    assert "Corrected" in text
    assert "Would be corrected" not in text  # empty section omitted
    assert output.stat().st_mode & 0o111  # executable


def test_write_preview_links_labels_each_section(tmp_path):
    d = tmp_path
    output = tmp_path / "preview-links.sh"
    preview_links.write_preview_links(
        output,
        corrected=[d / "a.jpg"],
        would_correct=[d / "b.jpg"],
        low_confidence=[d / "c.jpg"],
    )

    text = output.read_text()
    assert "Corrected" in text
    assert "Would be corrected" in text
    assert "Low confidence" in text


def test_write_preview_links_placeholder_when_nothing_flagged(tmp_path):
    output = tmp_path / "preview-links.sh"
    preview_links.write_preview_links(output, corrected=[], would_correct=[], low_confidence=[])

    assert "Nothing flagged this run" in output.read_text()


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
