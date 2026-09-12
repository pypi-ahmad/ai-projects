Identify every visual region on this page in reading order: titles, headings, paragraphs, tables, key/value pairs, figures, and invoice line items. For each region give it a stable id, a type, its text (or a caption for a figure), and a normalized bounding box (0-1, x0,y0,x1,y1) on THIS page. If a region is a table, also return its rows as a 2D array of strings; do not invent cells that aren't visible. If you are not confident of a bounding box for a region, set its bbox to null rather than guessing.

This is page {page_number} ({width_px}x{height_px} px).
