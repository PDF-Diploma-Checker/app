"""Locate actually invoked PDF Forms, including graphics-state placement matrices."""
import logging

import fitz
from pypdf.generic import ContentStream

logger = logging.getLogger(__name__)


def embedded_pdf_regions(reader, page_index, page):
    """Return (xref, page-space bbox) for each invocation, not resource-list bounds.

    LaTeX normally positions an included PDF using cm outside the Form itself.
    Resource-only APIs therefore cannot locate it. Nested Forms have their own
    resources and clipping BBoxes; reused Forms can appear at different places.
    """
    if reader is None:
        return []
    regions = []
    page_clip = page.rect * page.derotation_matrix

    def walk(stream, resources, matrix, clip, ancestors):
        if len(ancestors) > 32 or len(regions) >= 1000:
            return
        stack = []
        path_rect = None
        pending_clip = False
        for args, op in ContentStream(stream, reader).operations:
            if len(regions) >= 1000:
                break
            if op == b'q':
                stack.append((fitz.Matrix(matrix), fitz.Rect(clip)))
            elif op == b'Q':
                if stack:
                    matrix, clip = stack.pop()
            elif op == b'cm' and len(args) == 6:
                matrix = fitz.Matrix(*map(float, args)) * matrix
            elif op == b're' and len(args) == 4:
                x, y, width, height = map(float, args)
                rect = fitz.Rect(x, y, x + width, y + height).normalize()
                rect = rect * matrix * page.transformation_matrix
                path_rect = rect if path_rect is None else path_rect | rect
            elif op in (b'W', b'W*'):
                pending_clip = True
            elif op in (b'n', b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*'):
                if pending_clip and path_rect is not None:
                    clip = clip & path_rect
                path_rect = None
                pending_clip = False
            elif op == b'Do' and args:
                objects = resources.get('/XObject', {})
                objects = objects.get_object() if hasattr(objects, 'get_object') else objects
                reference = objects.get(args[0])
                if reference is None:
                    continue
                form = reference.get_object()
                if form.get('/Subtype') != '/Form':
                    continue
                xref = getattr(reference, 'idnum', id(form))
                if xref in ancestors:
                    continue
                transform = fitz.Matrix(*map(float, form.get('/Matrix', [1, 0, 0, 1, 0, 0]))) * matrix
                bounds = form.get('/BBox')
                if bounds is None:
                    continue
                rect = (fitz.Rect(*map(float, bounds)) * transform * page.transformation_matrix) & clip
                if rect.is_empty or not rect.is_valid:
                    continue
                regions.append((xref, rect))
                child_resources = form.get('/Resources', resources)
                child_resources = child_resources.get_object() if hasattr(child_resources, 'get_object') else child_resources
                walk(form, child_resources, transform, rect, ancestors | {xref})

    try:
        source_page = reader.pages[page_index]
        resources = source_page.get('/Resources', {})
        resources = resources.get_object() if hasattr(resources, 'get_object') else resources
        contents = source_page.get_contents()
        if contents is not None:
            walk(contents, resources, fitz.Matrix(1, 1), page_clip, set())
    except Exception:
        # Keep the old path/raster detector available for malformed documents.
        logger.exception('Could not resolve embedded PDF placements on page %s', page_index)
        return []
    return regions


def visible_drawings(page):
    """Respect PDF clipping when finding paths belonging to included figures.

    Path bounds can extend far outside a plot's axes or its Form BBox. Those
    invisible portions must not become another figure beside the original.
    """
    clips = []
    result = []
    for drawing in page.get_drawings(extended=True):
        level = drawing["level"]
        while clips and clips[-1][0] >= level:
            clips.pop()
        if drawing["type"] == "clip":
            clips.append((level, fitz.Rect(drawing["scissor"])))
            continue
        if drawing["type"] == "group":
            continue
        rect = fitz.Rect(drawing["rect"])
        for _, clip in clips:
            # Preserve horizontal/vertical lines (zero-area rectangles).
            if rect.x1 < clip.x0 or rect.x0 > clip.x1 or rect.y1 < clip.y0 or rect.y0 > clip.y1:
                break
            rect = fitz.Rect(max(rect.x0, clip.x0), max(rect.y0, clip.y0),
                             min(rect.x1, clip.x1), min(rect.y1, clip.y1))
        else:
            result.append({**drawing, "rect": rect})
    return result
