from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import polars as pl

from portefeuille_viewer.services.asset_dashboard_comments import DashboardComments


class DashboardCommentTests(unittest.TestCase):
    def setup_editor(self):
        row={"uniek_id":"known", "optie_comment":"bestaand", "optie_comment_color":"#d4edda",
             "optie_comment_textcolor":"#000000", "optie_comment_updated_at":datetime(2026,10,28)}
        self.cache=row
        def latest(ids):return pl.DataFrame([self.cache])
        def commit(value):self.cache={**self.cache,**value}
        def colour(identity,bg,fg):self.cache.update(optie_comment_color=bg,optie_comment_textcolor=fg)
        tab=SimpleNamespace(_on_comment_commit=Mock(side_effect=commit),_patch_comment_in_models=Mock(),
                            commentFlushTimer=SimpleNamespace(isActive=lambda:False,start=Mock()))
        editor=DashboardComments(tab);editor.remember([{"id":"known"}])
        return editor,tab,latest,colour

    def test_text_uses_existing_handler_and_preserves_colours(self):
        editor,tab,latest,colour=self.setup_editor()
        with patch("portefeuille_viewer.services.asset_dashboard_comments.repository.fetch_open_optie_comments",side_effect=latest):
            result=editor.save_text("known","nieuw")
        self.assertEqual(result["optie_comment"],"nieuw")
        self.assertEqual(result["optie_comment_color"],"#d4edda")
        tab._on_comment_commit.assert_called_once()

    def test_colour_uses_existing_colour_update_and_existing_flush_timer(self):
        editor,tab,latest,colour=self.setup_editor()
        with patch("portefeuille_viewer.services.asset_dashboard_comments.repository.fetch_open_optie_comments",side_effect=latest), \
             patch("portefeuille_viewer.services.asset_dashboard_comments.repository.update_open_optie_comment_color",side_effect=colour):
            result=editor.save_colour("known","#f8d7da","#000000")
        self.assertEqual(result["optie_comment"],"bestaand")
        self.assertEqual(result["optie_comment_color"],"#f8d7da")
        tab._on_comment_commit.assert_not_called()
        tab._patch_comment_in_models.assert_called_once()
        tab.commentFlushTimer.start.assert_called_once()

    def test_unknown_series_is_rejected(self):
        editor,tab,latest,colour=self.setup_editor()
        with self.assertRaises(ValueError):editor.save_text("unknown","tekst")
        tab._on_comment_commit.assert_not_called()

    def test_colour_on_empty_comment_creates_first_entry_via_existing_handler(self):
        editor,tab,latest,colour=self.setup_editor()
        self.cache=None
        def fetch(ids):return pl.DataFrame([self.cache]) if self.cache else pl.DataFrame()
        def create(value):self.cache=dict(value)
        tab._on_comment_commit.side_effect=create
        with patch("portefeuille_viewer.services.asset_dashboard_comments.repository.fetch_open_optie_comments",side_effect=fetch):
            result=editor.save_colour("known","#f8d7da","#000000")
        self.assertEqual(result["optie_comment"],"")
        self.assertEqual(result["optie_comment_color"],"#f8d7da")
        tab._on_comment_commit.assert_called_once()

    def test_failed_commit_is_not_reported_as_saved(self):
        editor,tab,latest,colour=self.setup_editor();tab._on_comment_commit.side_effect=None
        with patch("portefeuille_viewer.services.asset_dashboard_comments.repository.fetch_open_optie_comments",side_effect=latest):
            with self.assertRaises(RuntimeError):editor.save_text("known","nieuw")


if __name__=="__main__":unittest.main()
