import sys, markdown
src, out = sys.argv[1], sys.argv[2]
import re
text = open(src, encoding="utf-8").read()
text = re.sub(r"(?m)^   (- )", r"    \1", text)
text = re.sub(r"(?m)^(\*\*[^\n]*\*\*)\n(- )", r"\1\n\n\2", text)
body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
body = re.sub(r"<td>((?:FR|M)-?\d+)</td>", r'<td style="white-space:nowrap">\1</td>', body)
body = body.replace("<li>[ ] ", '<li class="task">☐ ').replace("<li>[x] ", '<li class="task">☑ ')
css = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1b2631; }
h1 { font-size: 20pt; color: #1a5276; border-bottom: 3px solid #1a5276; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 14pt; color: #1a5276; border-bottom: 1px solid #aeb6bf; padding-bottom: 3px; margin-top: 22px; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #2e4053; margin-bottom: 4px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.5pt; page-break-inside: avoid; }
th { background: #1a5276; color: white; text-align: left; padding: 5px 7px; }
td { border: 1px solid #d5d8dc; padding: 4px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f4f6f7; }
code { font-family: Menlo, monospace; font-size: 8.8pt; background: #f2f3f4; padding: 1px 3px; border-radius: 3px; }
pre { background: #f4f6f7; border: 1px solid #d5d8dc; border-radius: 4px; padding: 8px 10px; font-size: 8.5pt; line-height: 1.3; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
li { margin: 2px 0; }
li.task { list-style: none; margin-left: -1.1em; }
hr { border: none; border-top: 1px solid #d5d8dc; margin: 16px 0; }
"""
open(out, "w", encoding="utf-8").write(f"<!doctype html><html><head><meta charset='utf-8'><title>{sys.argv[3] if len(sys.argv)>3 else "Document"}</title><style>{css}</style></head><body>{body}</body></html>")
