from analysis.modules.llm.image_analysis.figures import FIGURE_FAMILIES, is_caption, mentions_figure


class ReferenceMatcher:
    def find_references(self, paragraphs, image_id, family="rys"):
        return [para for para in paragraphs if mentions_figure(para, image_id, family)]

    def references_to(self, paragraphs, img, images):
        """Paragraphs that discuss the figure. "Rysunek 3.1" is also what the text may call "schemat 3.1" or "wykres 3.1",
        unless a figure of that series has the same number."""
        taken = {other["family"] for other in images if other["number"] == img["number"]}
        for family in [img["family"]] + [f for f in FIGURE_FAMILIES if f not in taken]:
            refs = [r for r in self.find_references(paragraphs, img["number"], family)
                    if not is_caption(r, img["number"], family)]
            if refs:
                return refs
        return []
