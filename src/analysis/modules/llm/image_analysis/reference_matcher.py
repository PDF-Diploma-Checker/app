from analysis.modules.llm.image_analysis.figures import reference_pattern


class ReferenceMatcher:
    def find_references(self, paragraphs, image_id, family="rys"):
        pattern = reference_pattern(image_id, family)
        return [para for para in paragraphs if pattern.search(para)]
