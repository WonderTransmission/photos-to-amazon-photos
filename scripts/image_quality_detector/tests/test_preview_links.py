from pathlib import Path

from image_quality_detector import preview_links


def test_write_preview_links_groups_by_directory(tmp_path):
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    blurry = [dir_a / "a.jpg", dir_a / "b.jpg", dir_b / "c.jpg"]

    written = preview_links.write_preview_links(
        tmp_path,
        mode="would-quarantine",
        by_category={"blurry": blurry},
        divider_dir=tmp_path / "dividers",
    )

    assert len(written) == 1
    output = written[0]
    assert output.name == "preview-links-blurry-would-quarantine.sh"
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
        mode="quarantined",
        by_category={
            "blurry": [d / "a.jpg"],
            "dark": [d / "b.jpg"],
            "dark+light": [d / "c.jpg"],
        },
        divider_dir=tmp_path / "dividers",
    )

    assert {p.name for p in written} == {
        "preview-links-blurry-quarantined.sh",
        "preview-links-dark-quarantined.sh",
        "preview-links-dark+light-quarantined.sh",
    }

    by_name = {p.name: p.read_text() for p in written}
    blurry_text = by_name["preview-links-blurry-quarantined.sh"]
    dark_text = by_name["preview-links-dark-quarantined.sh"]
    combined_text = by_name["preview-links-dark+light-quarantined.sh"]

    # each file must only reference its own category's file -- no bleed-through between them
    assert '"$DIR/a.jpg"' in blurry_text
    assert '"$DIR/b.jpg"' not in blurry_text
    assert '"$DIR/c.jpg"' not in blurry_text

    assert '"$DIR/b.jpg"' in dark_text
    assert '"$DIR/a.jpg"' not in dark_text

    assert '"$DIR/c.jpg"' in combined_text
    assert '"$DIR/a.jpg"' not in combined_text


def test_write_preview_links_writes_nothing_when_nothing_flagged(tmp_path):
    written = preview_links.write_preview_links(
        tmp_path,
        mode="would-quarantine",
        by_category={},
        divider_dir=tmp_path / "dividers",
    )

    assert written == []
    assert list(tmp_path.glob("preview-links-*.sh")) == []
    assert not (tmp_path / "dividers").exists()  # nothing to divide, nothing written


def test_write_preview_links_omits_files_for_empty_categories(tmp_path):
    written = preview_links.write_preview_links(
        tmp_path,
        mode="would-quarantine",
        by_category={"blurry": [tmp_path / "a.jpg"], "dark": []},
        divider_dir=tmp_path / "dividers",
    )

    assert len(written) == 1
    assert written[0].name == "preview-links-blurry-would-quarantine.sh"


def test_write_preview_links_opens_a_divider_image_first_in_each_group(tmp_path):
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    divider_dir = tmp_path / "dividers"

    written = preview_links.write_preview_links(
        tmp_path,
        mode="would-quarantine",
        by_category={"blurry": [dir_a / "a.jpg"], "dark": [dir_b / "b.jpg"]},
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
        mode="would-quarantine",
        by_category={"blurry": [d / "a.jpg"], "dark": [d / "b.jpg"], "light": [d / "c.jpg"]},
        divider_dir=divider_dir,
    )

    dividers = sorted(divider_dir.glob("*.png"))
    assert len(dividers) == 3
    assert len({p.name for p in dividers}) == 3


def test_write_review_checklist_lists_flagged_files(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    output = tmp_path / "review.txt"

    wrote = preview_links.write_review_checklist(
        output, flagged=[a, b], revert_command="revert-cmd review.txt"
    )

    assert wrote is True
    text = output.read_text()
    assert str(a) in text
    assert str(b) in text
    assert "revert-cmd review.txt" in text


def test_write_review_checklist_returns_false_and_writes_nothing_when_empty(tmp_path):
    output = tmp_path / "review.txt"

    wrote = preview_links.write_review_checklist(output, flagged=[], revert_command="cmd")

    assert wrote is False
    assert not output.exists()


def test_write_review_checklist_dedupes(tmp_path):
    a = tmp_path / "a.jpg"
    output = tmp_path / "review.txt"

    preview_links.write_review_checklist(output, flagged=[a, a], revert_command="cmd")

    assert output.read_text().count(str(a)) == 1


def test_write_duplicate_set_previews_opens_kept_and_removed_together(tmp_path):
    kept = tmp_path / "a.jpg"
    removed = tmp_path / "b.jpg"

    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="would-quarantine",
        duplicate_groups={"exact_duplicates": [{"kept": kept, "removed": [removed]}]},
        divider_dir=tmp_path / "dividers",
    )

    assert len(written) == 1
    output = written[0]
    assert output.name == "preview-links-exact_duplicates-would-quarantine.sh"
    text = output.read_text()

    # both the kept file and the flagged one appear in the same `open` call
    open_lines = [line for line in text.splitlines() if line.startswith("open -a preview")]
    assert len(open_lines) == 1
    assert str(kept) in open_lines[0]
    assert str(removed) in open_lines[0]
    assert output.stat().st_mode & 0o111  # executable


def test_write_duplicate_set_previews_pauses_between_sets_but_not_after_the_last(tmp_path):
    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="would-quarantine",
        duplicate_groups={
            "exact_duplicates": [
                {"kept": tmp_path / "a.jpg", "removed": [tmp_path / "b.jpg"]},
                {"kept": tmp_path / "c.jpg", "removed": [tmp_path / "d.jpg"]},
            ]
        },
        divider_dir=tmp_path / "dividers",
    )

    lines = written[0].read_text().splitlines()
    open_lines_idx = [i for i, line in enumerate(lines) if line.startswith("open -a preview")]
    read_lines_idx = [i for i, line in enumerate(lines) if line.startswith("read -p")]

    assert len(open_lines_idx) == 2
    # exactly one pause, sitting between the two `open` calls -- none after the final set
    assert len(read_lines_idx) == 1
    assert open_lines_idx[0] < read_lines_idx[0] < open_lines_idx[1]


def test_write_duplicate_set_previews_pause_prompt_shows_progress_count(tmp_path):
    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="would-quarantine",
        duplicate_groups={
            "exact_duplicates": [
                {"kept": tmp_path / f"k{n}.jpg", "removed": [tmp_path / f"r{n}.jpg"]}
                for n in range(8)
            ]
        },
        divider_dir=tmp_path / "dividers",
    )

    read_lines = [
        line for line in written[0].read_text().splitlines() if line.startswith("read -p")
    ]

    assert len(read_lines) == 7  # one between each pair of the 8 sets, none after the last
    assert "(2 of 8)" in read_lines[0]
    assert "(8 of 8)" in read_lines[-1]


def test_write_duplicate_set_previews_writes_a_separate_file_per_category(tmp_path):
    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="quarantined",
        duplicate_groups={
            "exact_duplicates": [{"kept": tmp_path / "a.jpg", "removed": [tmp_path / "b.jpg"]}],
            "near_duplicates": [{"kept": tmp_path / "c.jpg", "removed": [tmp_path / "d.jpg"]}],
        },
        divider_dir=tmp_path / "dividers",
    )

    assert {p.name for p in written} == {
        "preview-links-exact_duplicates-quarantined.sh",
        "preview-links-near_duplicates-quarantined.sh",
    }


def test_write_duplicate_set_previews_skips_groups_with_nothing_removed(tmp_path):
    # Shouldn't happen in practice (cli.py only creates a group entry when there's at least one
    # non-kept member) but the writer should be robust to it regardless.
    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="would-quarantine",
        duplicate_groups={"exact_duplicates": [{"kept": tmp_path / "a.jpg", "removed": []}]},
        divider_dir=tmp_path / "dividers",
    )

    assert written == []


def test_write_duplicate_set_previews_writes_nothing_when_no_groups(tmp_path):
    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="would-quarantine",
        duplicate_groups={},
        divider_dir=tmp_path / "dividers",
    )

    assert written == []
    assert list(tmp_path.glob("preview-links-*.sh")) == []


def test_write_duplicate_set_previews_opens_a_divider_first_in_each_set(tmp_path):
    written = preview_links.write_duplicate_set_previews(
        tmp_path,
        mode="would-quarantine",
        duplicate_groups={
            "exact_duplicates": [
                {"kept": tmp_path / "a.jpg", "removed": [tmp_path / "b.jpg"]},
                {"kept": tmp_path / "c.jpg", "removed": [tmp_path / "d.jpg"]},
            ]
        },
        divider_dir=tmp_path / "dividers",
    )

    dividers = sorted((tmp_path / "dividers").glob("*.png"))
    assert len(dividers) == 2  # one per set

    for line in written[0].read_text().splitlines():
        if line.startswith("open -a preview"):
            first_arg = line.split('"')[1]
            assert first_arg.endswith(".png")
            assert Path(first_arg).exists()
