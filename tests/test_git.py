"""Tests for git.py — force-push guard and URL parsing."""

from unittest.mock import MagicMock, patch

import pytest

from forger.git import detect_repo, push


class TestPushPrefixGuard:
    def test_rejects_branch_without_prefix(self):
        with pytest.raises(ValueError, match="Refusing to force-push"):
            push("main", "/tmp/fake", branch_prefix="forger")

    def test_rejects_branch_with_wrong_prefix(self):
        with pytest.raises(ValueError, match="Refusing to force-push"):
            push("other/issue-1", "/tmp/fake", branch_prefix="forger")

    def test_rejects_partial_prefix_match(self):
        with pytest.raises(ValueError, match="Refusing to force-push"):
            push("forger-extra/issue-1", "/tmp/fake", branch_prefix="forger")

    def test_accepts_correct_prefix(self):
        with patch("forger.git.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            push("forger/issue-1", "/tmp/fake", branch_prefix="forger")
            mock_run.assert_called_once()

    def test_accepts_custom_prefix(self):
        with patch("forger.git.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            push("mybranch/fix-123", "/tmp/fake", branch_prefix="mybranch")
            mock_run.assert_called_once()


class TestDetectRepo:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://github.com/org/repo.git", "org/repo"),
            ("https://github.com/org/repo", "org/repo"),
            ("git@github.com:org/repo.git", "org/repo"),
            ("git@github.com:org/repo", "org/repo"),
            ("https://github.com/user/my-project.git", "user/my-project"),
            ("https://gitlab.com/org/repo.git", None),
            ("not-a-url", None),
        ],
    )
    def test_url_parsing(self, url, expected):
        with patch("forger.git.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=url + "\n")
            assert detect_repo(None) == expected

    def test_no_remote(self):
        with patch("forger.git.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal")
            assert detect_repo(None) is None
