import fitz  # PyMuPDF
from typing import List
import re
import logging

from analysis.extraction.raw_extraction.bare_struct import (
    DocumentData,
    PageData,
    ImageInfo,
)

logger = logging.getLogger(__name__)

def get_raster_figure_numbers(document_data: DocumentData) -> List[str]:
    if not document_data or not getattr(document_data, "pages", None):
        return []

    number_pattern = re.compile(
        r"(?i)\b(?:rys(?:unek)?|fig(?:ure)?|wykres|fot(?:o)?|photo|image)\.?\s*(\d+(?:\.\d+)*)"
    )

    raster_numbers: List[str] = []
    seen = set()

    for page in document_data.pages:
        for img in getattr(page, "images", []):
            if str(getattr(img, "image_type", "")).lower().strip() != "raster":
                continue

            description = str(getattr(img, "description", "") or "")
            if not description:
                continue

            match = number_pattern.search(description)
            if not match:
                continue

            fig_number = match.group(1)
            if fig_number not in seen:
                seen.add(fig_number)
                raster_numbers.append(fig_number)

    return raster_numbers


def find_image_description(image_bbox, text_blocks, priority_side=None):
    x0, y0, x1, y1 = image_bbox
    img_keywords = (
        "rysunek", "rys.", "fot.", "ilustracja", "wykres", "rycina",
        "schemat", "diagram", "grafika", "figure", "fig.", "photo",
        "img", "image", "schema", "chart", "plot"
    )

    candidates = {"above": [], "below": []}

    for block in text_blocks:
        bx0, by0, bx1, by1 = block.bbox

        is_close_above = abs(by1 - y0) < 40
        is_close_below = abs(by0 - y1) < 40

        if is_close_above or is_close_below:
            full_text = " ".join(
                span.text for line in block.lines for span in line.spans
            ).strip()
            if not full_text:
                continue

            side = "above" if is_close_above else "below"
            sizes = [sp.size for line in block.lines for sp in line.spans if sp.text.strip()]
            block_size = max(set(sizes), key=sizes.count) if sizes else None
            candidates[side].append((by0, by1, full_text, block_size))

    candidates["above"].sort(key=lambda item: item[0])
    candidates["below"].sort(key=lambda item: item[0])

    primary = priority_side if priority_side else "below"
    secondary = "above" if primary == "below" else "below"

    def build_full_caption(block_list):
        if not block_list:
            return ""
        start_idx = -1
        for idx, (_, _, text, _) in enumerate(block_list):
            if text.lower().startswith(img_keywords):
                start_idx = idx
                break

        if start_idx == -1:
            return ""

        caption_parts = [block_list[start_idx][2]]
        last_by1 = block_list[start_idx][1]
        caption_size = block_list[start_idx][3]

        for idx in range(start_idx + 1, len(block_list)):
            curr_by0, curr_by1, text, curr_size = block_list[idx]
            if (curr_by0 - last_by1) < 18:
                if text.lower().startswith(img_keywords):
                    break 
                if (
                    caption_size is not None
                    and curr_size is not None
                    and abs(curr_size - caption_size) > 0.5
                ):
                    break
                caption_parts.append(text)
                last_by1 = curr_by1
            else:
                break

        return " ".join(" ".join(caption_parts).split())

    caption_primary = build_full_caption(candidates[primary])
    if caption_primary:
        return caption_primary, primary

    caption_secondary = build_full_caption(candidates[secondary])
    if caption_secondary:
        return caption_secondary, secondary

    return "", priority_side

def merge_fragment_images(
    page: fitz.Page, cur_page: PageData, min_overlap: float = 0.2, pad: float = 5.0
) -> None:
    """
    Merges small raster fragments (e.g. nodes of a diagram stored as separate bitmaps)
    into the bigger image they overlap. The container's bbox becomes the union of both
    boxes and the container is re-rendered, so nothing sticking out of the original
    clip is cut off. Fragment files are removed; the caption of a fragment is inherited
    if the container has none.
    """
    import os

    def area(b):
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    def inter(a, b):
        w = min(a[2], b[2]) - max(a[0], b[0])
        h = min(a[3], b[3]) - max(a[1], b[1])
        return max(0.0, w) * max(0.0, h)

    changed = True
    while changed and len(cur_page.images) > 1:
        changed = False
        images = cur_page.images
        for i, small in enumerate(images):
            a_small = area(small.bbox)
            if a_small <= 0 or small.image_type != "raster":
                continue
            for j, big in enumerate(images):
                if i == j or area(big.bbox) <= a_small * 1.05:
                    continue
                if inter(small.bbox, big.bbox) / a_small < min_overlap:
                    continue

                union = fitz.Rect(big.bbox) | fitz.Rect(small.bbox)
                clip = (union + (-pad, -pad, pad, pad)) & page.rect if big.image_type == "vector" else union
                try:
                    if big.image_type == "vector":
                        pix = page.get_pixmap(clip=clip)
                        pix.save(big.path)
                        big.width, big.height = pix.width, pix.height
                    big.bbox = (union.x0, union.y0, union.x1, union.y1)
                except Exception as e:
                    logger.error(f"Failed to re-render merged image {big.path}: {e}")
                    continue

                if not big.description and small.description:
                    big.description = small.description
                try:
                    if small.path and os.path.isfile(small.path):
                        os.remove(small.path)
                except OSError as e:
                    logger.warning(f"Could not remove {small.path}: {e}")
                del cur_page.images[i]
                changed = True
                break
            if changed:
                break


def extract_vector_graphics(
    page: fitz.Page,
    drawings: list,
    page_index: int,
    table_bboxes: list,
    cur_page: PageData,
    priority_side=None,
) -> str:
    """
    Extracts vector graphics from a PDF page, merges adjacent shapes, and saves them as images.

    Args:
        page (fitz.Page): The PDF page.
        drawings (list): A list of raw vector drawings from the page.
        page_index (int): The index of the current page, used for generating image filenames.
        table_bboxes (list): A list of table bounding boxes to avoid extracting table borders.
        cur_page (PageData): The data object for the current page where image metadata is appended.
        priority_side (str, optional): The preferred side (above/below) to look for descriptions.


    Returns:
        return priority_side(str)
    """
    if not drawings:
        return priority_side

    content_width = (
        cur_page.width
        - cur_page.margins.get("left", 0)
        - cur_page.margins.get("right", 0)
    )
    if content_width <= 50:
        content_width = page.rect.width * 0.8

    vector_bboxes = []
    for d in drawings:
        color = d.get("color")
        fill = d.get("fill")

        if color is None and fill is None:
            continue
        if (color is None or (len(color) in (1, 3) and min(color) >= 0.98)) and (
            fill is None or (len(fill) in (1, 3) and min(fill) >= 0.98)
        ):
            continue

        rect = fitz.Rect(d["rect"])
        if max(rect.width, rect.height) <= 2:
            continue

        is_orthogonal = True
        is_rect_only = True
        for item in d.get("items", []):
            if item[0] == "l":
                is_rect_only = False
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) > 2 and abs(p1.y - p2.y) > 2:
                    is_orthogonal = False
                    break
            elif item[0] in ("c", "q"):
                is_rect_only = False
                is_orthogonal = False
                break
            elif item[0] != "re":
                is_rect_only = False

        is_inside_table = False
        for t_bbox in table_bboxes:
            expanded_t_bbox = t_bbox + (-10, -10, 10, 10)
            intersect = rect & expanded_t_bbox
            if intersect.is_valid and not intersect.is_empty:
                if (intersect.width * intersect.height) / (
                    rect.width * rect.height + 0.001
                ) > 0.8:
                    is_inside_table = True
                    break

        if is_inside_table and is_orthogonal:
            continue

        has_dark_stroke = False
        if color is not None:
            if len(color) in (1, 3) and sum(color) / len(color) <= 0.85:
                has_dark_stroke = True
            elif len(color) == 4 and max(color) >= 0.15:
                has_dark_stroke = True

        has_dark_fill = False
        if fill is not None:
            if len(fill) in (1, 3) and sum(fill) / len(fill) <= 0.85:
                has_dark_fill = True
            elif len(fill) == 4 and max(fill) >= 0.15:
                has_dark_fill = True

        is_pale_shape = not has_dark_stroke and not has_dark_fill

        if is_pale_shape and is_rect_only:
            continue

        is_text_formatting = False
        lines_inside = 0
        expanded_rect = rect + (-5, -5, 5, 5)
        for text_block in cur_page.text_blocks:
            for line in text_block.lines:
                t_rect = fitz.Rect(line.bbox)
                if expanded_rect.intersects(t_rect):
                    lines_inside += 1

                    if (
                        rect.height <= 3
                        and rect.x0 >= t_rect.x0 - 5
                        and rect.x1 <= t_rect.x1 + 5
                    ):
                        is_text_formatting = True

        if lines_inside > 0:
            if is_pale_shape:
                is_text_formatting = True
            elif rect.height <= 5 and rect.width < 150:
                is_text_formatting = True
        elif is_pale_shape and is_rect_only:
            is_text_formatting = True

        if not is_text_formatting:
            vector_bboxes.append(rect)

    merged_bboxes = vector_bboxes.copy()
    changed = True

    while changed:
        changed = False
        new_merged = []

        while len(merged_bboxes) > 0:
            current = merged_bboxes.pop(0)
            expanded_current = current + (-80, -80, 80, 80)

            i = 0
            while i < len(merged_bboxes):
                if expanded_current.intersects(merged_bboxes[i]):
                    current = current | merged_bboxes[i]
                    expanded_current = current + (-80, -80, 80, 80)
                    merged_bboxes.pop(i)
                    changed = True
                else:
                    i += 1
            new_merged.append(current)
        merged_bboxes = new_merged


    min_physical_width = 40
    min_physical_width = 20

    for i in range(len(merged_bboxes)):
        bbox = merged_bboxes[i]

        if bbox.width > min_physical_width and bbox.height > min_physical_width:
            changed_text = True
            while changed_text:
                changed_text = False
                search_area = bbox + (-35, -5, 35, 20)
                new_bbox = bbox

                for t_block in cur_page.text_blocks:
                    for line in t_block.lines:
                        t_rect = fitz.Rect(line.bbox)
                        if search_area.intersects(t_rect) and not bbox.contains(t_rect):
                            if t_rect.width > content_width * 0.40:
                                continue

                            line_text = " ".join([s.text for s in line.spans]).strip()

                            if line_text.lower().startswith(
                                (
                                    "rys",
                                    "tab",
                                    "fot",
                                    "wykres",
                                    "schemat",
                                    "figure",
                                    "fig",
                                )
                            ):
                                continue

                            if line_text.endswith(".") and t_rect.y1 <= bbox.y0 + 20:
                                continue

                            new_bbox = new_bbox | t_rect
                            changed_text = True
                bbox = new_bbox

            merged_bboxes[i] = bbox + (-5, -5, 5, 5)

    for i, bbox in enumerate(merged_bboxes):
        if bbox.width > min_physical_width and bbox.height > min_physical_width:
            aspect_ratio = bbox.width / bbox.height

            if aspect_ratio < 25.0 and aspect_ratio > 0.05:
                is_invalid = False
                for t_bbox in table_bboxes:
                    intersect = bbox & t_bbox
                    if intersect.is_valid and not intersect.is_empty:
                        intersect_area = intersect.width * intersect.height
                        bbox_area = bbox.width * bbox.height
                        t_bbox_area = t_bbox.width * t_bbox.height

                        if t_bbox_area > 0 and (intersect_area / t_bbox_area) > 0.50:
                            is_invalid = True
                            break
                        if bbox_area > 0 and (intersect_area / bbox_area) > 0.80:
                            is_invalid = True
                            break

                if is_invalid:
                    continue

                bbox = bbox.intersect(page.rect)
                if not bbox.is_valid or bbox.is_empty:
                    continue

                description, found_side = find_image_description(
                    (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                    cur_page.text_blocks,
                    priority_side,
                )

                if description and priority_side is None:
                    priority_side = found_side

                try:
                    pix = page.get_pixmap(clip=bbox)
                    img_path = f"images/p{page_index}_vec_{i}.png"
                    pix.save(img_path)
                    logger.info(f"Successfully saved vector image: {img_path}")
                except Exception as e:
                    logger.error(f"Failed to save vector image for page {page_index}, rect {i}: {e}")
                    continue

                cur_page.images.append(
                    ImageInfo(
                        path=img_path,
                        bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                        width=pix.width,
                        height=pix.height,
                        image_type="vector",
                        description=description,
                    )
                )

    return priority_side


def extract_raster_images(
    blocks: list,
    drawings: list,
    page_width: float,
    page_height: float,
    page_index: int,
    cur_page: PageData,
    priority_side=None,
) -> str:
    """
    Extracts raster images from PDF blocks, filters them (removes backgrounds, small icons), and saves them to images.

    Args:
        blocks (list): A list of blocks extracted from page.get_text("dict")["blocks"].
        drawings (list): A list of vector drawings on the page, used for collision detection.
        page_width (float): The width of the page.
        page_height (float): The height of the page.
        page_index (int): The index of the current page, used for generating image filenames.
        cur_page (PageData): The data object for the current page where extracted image metadata is appended.
        priority_side (str, optional): The preferred side (above/below) to look for descriptions.

    Returns:
        str: The updated priority_side for images.
    """
    for block in blocks:
        if block["type"] == 1:
            x0, y0, x1, y1 = block["bbox"]
            phys_width = x1 - x0
            phys_height = y1 - y0
            img_rect = fitz.Rect(block["bbox"])

            min_physical_width = 20
            min_physical_width = 20

            if phys_width < min_physical_width or phys_height < min_physical_width:
                continue

            if phys_width < 40 and phys_height < 40:
                is_inline_with_text = False
                for t_block in cur_page.text_blocks:
                    t_rect = fitz.Rect(t_block.bbox) + (-2, -2, 2, 2)
                    if img_rect.intersects(t_rect):
                        is_inline_with_text = True
                        break

                is_in_drawing = False
                for d in drawings:
                    d_rect = fitz.Rect(d["rect"])
                    if (
                        d_rect.width < page_width * 0.9
                        and d_rect.height < page_height * 0.9
                    ):
                        if img_rect.intersects(d_rect):
                            is_in_drawing = True
                            break

                if is_inline_with_text and not is_in_drawing:
                    continue

                if not is_in_drawing and block["width"] < 150 and block["height"] < 150:
                    continue

            if phys_height > 0:
                aspect_ratio = phys_width / phys_height
                if aspect_ratio > 15.0 or aspect_ratio < 0.15:
                    continue

                if phys_height < 35 and aspect_ratio > 2.5:
                    continue

            try:
                pix = fitz.Pixmap(block["image"])
                if pix.is_unicolor:
                    continue
            except Exception as e:
                logger.warning(f"Failed to create Pixmap for block {block.get('number')} on page {page_index}: {e}")
                pass

            is_background = False
            if img_rect.height < 60:
                for t_block in cur_page.text_blocks:
                    for line in t_block.lines:
                        t_rect = fitz.Rect(line.bbox)
                        intersect = img_rect & t_rect
                        if intersect.is_valid and not intersect.is_empty:
                            overlap_area = intersect.width * intersect.height
                            img_area = img_rect.width * img_rect.height
                            if overlap_area / img_area > 0.6:
                                is_background = True
                                break
                    if is_background:
                        break

            if is_background:
                continue

            description, found_side = find_image_description(
                block["bbox"], cur_page.text_blocks, priority_side
            )
            if description and priority_side is None:
                priority_side = found_side

            ext = block.get("ext", "png")
            img_path = f"images/p{page_index}_b{block['number']}.{ext}"

            try:
                with open(img_path, "wb") as img_file:
                    img_file.write(block["image"])
                logger.info(f"Successfully saved raster image: {img_path}")
            except Exception as e:
                logger.error(f"Failed to save raster image {img_path}: {e}")
                continue

            cur_page.images.append(
                ImageInfo(
                    path=img_path,
                    bbox=block["bbox"],
                    width=block["width"],
                    height=block["height"],
                    image_type="raster",
                    description=description,
                )
            )

    return priority_side