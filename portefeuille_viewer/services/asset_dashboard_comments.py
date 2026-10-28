"""Adapter to the existing Single Asset Analyse comment cache and flush lifecycle."""
from portefeuille_viewer.data import repository


class DashboardComments:
    def __init__(self, legacy_tab):
        self.legacy_tab = legacy_tab
        self.known_ids = set()

    def remember(self, metadata):
        self.known_ids.update(item["id"] for item in metadata)

    def latest(self, identity):
        if identity not in self.known_ids:
            raise ValueError("Deze optieserie is niet beschikbaar voor commentaar")
        frame = repository.fetch_open_optie_comments([identity])
        return frame.row(0, named=True) if frame is not None and not frame.is_empty() else {}

    def save_text(self, identity, comment):
        latest = self.latest(identity)
        self.legacy_tab._on_comment_commit({
            "uniek_id": identity, "optie_comment": comment,
            "optie_comment_color": latest.get("optie_comment_color") or "",
            "optie_comment_textcolor": latest.get("optie_comment_textcolor") or "",
        })
        result = self.latest(identity)
        if (result.get("optie_comment") or "") != comment:
            raise RuntimeError("Commentaar kon niet in de bestaande opslagcache worden bewaard")
        return result

    def save_colour(self, identity, background, foreground):
        latest = self.latest(identity)
        if not latest:
            self.legacy_tab._on_comment_commit({"uniek_id": identity, "optie_comment": "",
                "optie_comment_color": background, "optie_comment_textcolor": foreground})
        else:
            repository.update_open_optie_comment_color(identity, background, foreground)
            latest = self.latest(identity)
            self.legacy_tab._patch_comment_in_models(identity, latest.get("optie_comment") or "",
                latest.get("optie_comment_color") or "", latest.get("optie_comment_textcolor") or "",
                latest.get("optie_comment_updated_at"))
            if not self.legacy_tab.commentFlushTimer.isActive():
                self.legacy_tab.commentFlushTimer.start()
        result = self.latest(identity)
        if (result.get("optie_comment_color") or "") != background:
            raise RuntimeError("Commentaarkleur kon niet worden bewaard")
        return result
