"""Build paired A4 math worksheets from reviewed JSON. Does not perform OCR or solve math."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
)

PAGE_W, PAGE_H = A4
MARGIN = 45
CONTENT_W = PAGE_W - 2 * MARGIN
GREEN = colors.HexColor('#2B7A78')
INK = colors.HexColor('#242424')


def positive(value, name, maximum=10000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f'{name}: expected a positive number <= {maximum}')
    return value


def register_fonts(regular=None, bold=None):
    candidates = [regular, os.environ.get('MATH_WORKSHEET_FONT'),
                  'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc',
                  '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc']
    chosen = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if not chosen:
        raise ValueError('Chinese font missing; pass --font with a Chinese TrueType font file')
    if regular and not Path(regular).is_file():
        raise ValueError(f'font not found: {regular}')
    bold_path = Path(bold) if bold else (Path('C:/Windows/Fonts/msyhbd.ttc') if chosen.name.lower() == 'msyh.ttc' else chosen)
    if not bold_path.is_file():
        bold_path = chosen
    pdfmetrics.registerFont(TTFont('MathCN', str(chosen)))
    pdfmetrics.registerFont(TTFont('MathCNBold', str(bold_path)))
    return str(chosen)


def paragraph(text, size=12, color=INK, bold=False):
    text = escape(text).replace('\n', '<br/>')
    # Keep a whole blank together; CJK wrapping is retained for the surrounding prose.
    text = re.sub(r'（[ \u3000]+）', lambda m: '<nobr>' + m.group().replace(' ', '&#160;').replace('\u3000', '&#160;&#160;') + '</nobr>', text)
    style = ParagraphStyle('math', fontName='MathCNBold' if bold else 'MathCN',
                           fontSize=size, leading=size * 1.7, textColor=color,
                           wordWrap='CJK', spaceAfter=7, splitLongWords=True)
    return Paragraph(text, style)


class Equation(Flowable):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.parts = [(ch, 20 if ch in '□○' else pdfmetrics.stringWidth(ch, 'MathCN', 14)) for ch in text]
        self.width = sum(width for _, width in self.parts)
        self.height = 34
        if self.width > CONTENT_W - 4:
            raise ValueError('equation is too wide; split into separate equation blocks at a meaningful boundary')

    def draw(self):
        c, x, y = self.canv, 0, 12
        c.saveState()
        c.setStrokeColor(INK)
        c.setFillColor(INK)
        c.setFont('MathCN', 14)
        c.setLineWidth(.8)
        for ch, width in self.parts:
            if ch == '□':
                c.rect(x, y - 3, 17, 17, stroke=1, fill=0)
            elif ch == '○':
                c.circle(x + 8.5, y + 5.5, 8.5, stroke=1, fill=0)
            else:
                c.drawString(x, y, ch)
            x += width
        c.restoreState()


class Diagram(Flowable):
    def __init__(self, block):
        super().__init__()
        self.block = block
        self.width = block.get('width', 440)
        self.height = 100 if block['type'] == 'number_line' else block['rows'] * block.get('spacing', 18) + 15

    def draw(self):
        c, b = self.canv, self.block
        c.saveState()
        c.setFillColor(INK)
        c.setStrokeColor(INK)
        c.setLineWidth(.8)
        if b['type'] == 'dots':
            spacing = b.get('spacing', 18)
            for row in range(b['rows']):
                for col in range(b['cols']):
                    c.circle(8 + col * spacing, self.height - 8 - row * spacing, 2.5, stroke=1, fill=0)
        else:
            values = b['values']
            start, end, baseline = 10, self.width - 16, 24
            step = (end - start) / (len(values) - 1)
            c.line(start, baseline, end + 8, baseline)
            c.line(end + 4, baseline + 3, end + 8, baseline)
            c.line(end + 4, baseline - 3, end + 8, baseline)
            c.setFont('MathCN', 9)
            for index, value in enumerate(values):
                x = start + index * step
                c.line(x, baseline, x, baseline + 5)
                c.drawCentredString(x, baseline - 15, str(value))
            for arc in b.get('arcs', []):
                x0, x1 = start + arc[0] * step, start + arc[1] * step
                path = c.beginPath()
                path.moveTo(x0, baseline + 7)
                path.curveTo(x0 + (x1 - x0) * .25, baseline + 36,
                             x1 - (x1 - x0) * .25, baseline + 36, x1, baseline + 7)
                c.drawPath(path)
                direction = 1 if x1 > x0 else -1
                c.line(x1 - direction * 6, baseline + 10, x1, baseline + 7)
                c.line(x1 - direction, baseline + 14, x1, baseline + 7)
                if len(arc) == 3 and arc[2]:
                    c.drawCentredString((x0 + x1) / 2, baseline + 40, str(arc[2]))
        c.restoreState()


def validate(spec, base, draft=False, questions_only=False):
    if not isinstance(spec, dict) or not isinstance(spec.get('title'), str) or not spec['title'].strip():
        raise ValueError('title must be nonempty text')
    questions = spec.get('questions')
    if not isinstance(questions, list) or not questions:
        raise ValueError('questions must be a nonempty list')
    seen_ids, seen_locations = set(), set()
    for q in questions:
        if not isinstance(q, dict):
            raise ValueError('each question must be an object')
        for name in ['id', 'source', 'page', 'number', 'status', 'selection_reason']:
            if not isinstance(q.get(name), str) or not q[name].strip():
                raise ValueError(f'{name} must be nonempty text in each question')
        location = (q['source'], q['page'], q['number'])
        if q['id'] in seen_ids or location in seen_locations:
            raise ValueError(f'duplicate id or source/page/number: {q["id"]}')
        seen_ids.add(q['id'])
        seen_locations.add(location)
        if q['status'] not in ('ready', 'needs_review'):
            raise ValueError(f'{q["id"]}: status must be ready or needs_review')
        if q['status'] == 'needs_review':
            if not draft:
                raise ValueError(f'{q["id"]}: needs_review; resolve issue or explicitly use --draft')
            if not isinstance(q.get('issue'), str) or not q['issue'].strip():
                raise ValueError('needs_review item requires an issue description')
        if not questions_only and q['status'] == 'ready':
            if not isinstance(q.get('answer'), list) or not q['answer'] or not all(isinstance(t, str) and t.strip() for t in q['answer']):
                raise ValueError(f'{q["id"]}: answer must contain nonempty text lines')
            if not isinstance(q.get('verification'), str) or not q['verification'].strip():
                raise ValueError(f'{q["id"]}: verification is required')
        blocks = q.get('blocks')
        if not isinstance(blocks, list) or not blocks:
            raise ValueError(f'{q["id"]}: blocks must be nonempty')
        for b in blocks:
            if not isinstance(b, dict):
                raise ValueError('each block must be an object')
            kind = b.get('type')
            if kind in ('text', 'equation'):
                if not isinstance(b.get('text'), str) or not b['text'].strip():
                    raise ValueError(f'{kind}: text must be nonempty')
            elif kind == 'image':
                if not isinstance(b.get('path'), str) or not b['path']:
                    raise ValueError('image: path is required')
                p = (base / b['path']).resolve()
                if not p.is_file():
                    raise ValueError(f'image missing: {p}')
                with PILImage.open(p) as im:
                    width = positive(b.get('width', 300), 'image width', CONTENT_W - 4)
                    if width * im.height / im.width > 610:
                        raise ValueError('image too tall: crop the relevant figure or reduce width')
            elif kind == 'number_line':
                values = b.get('values')
                if not isinstance(values, list) or len(values) < 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
                    raise ValueError('number_line values must have at least two finite numbers')
                delta = values[1] - values[0]
                if delta <= 0 or any(not math.isclose(values[i + 1] - values[i], delta) for i in range(len(values) - 1)):
                    raise ValueError('number_line values must increase with equal steps')
                width = positive(b.get('width', 440), 'number_line width', CONTENT_W - 4)
                if (width - 26) / (len(values) - 1) < 14:
                    raise ValueError('number_line tick labels too dense; use a separate verified diagram')
                if not isinstance(b.get('arcs', []), list):
                    raise ValueError('number_line arcs must be a list')
                for arc in b.get('arcs', []):
                    if not isinstance(arc, list) or len(arc) not in (2, 3) or not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(values) for v in arc[:2]) or arc[0] == arc[1]:
                        raise ValueError('number_line arc uses tick indices, not tick values')
            elif kind == 'dots':
                for key in ['rows', 'cols']:
                    if type(b.get(key)) is not int or not 1 <= b[key] <= 30:
                        raise ValueError(f'dots {key}: expected integer 1..30')
                spacing = positive(b.get('spacing', 18), 'dots spacing', 40)
                if (b['cols'] - 1) * spacing + 16 > CONTENT_W - 4 or b['rows'] * spacing + 15 > 600:
                    raise ValueError('dots diagram exceeds printable area')
            else:
                raise ValueError(f'unsupported block type: {kind}')
        gap = q.get('work_space', 40)
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or not 0 <= gap <= 300:
            raise ValueError('work_space must be 0..300 points')


def label(q):
    main, sep, sub = q['number'].partition('（')
    page = f'原第{q["page"]}页' if q['page'].isdigit() else q['page']
    return f'{q["source"]} · {page} · 第{main}题' + (sep + sub if sep else '')


def block_flow(b, base):
    if b['type'] == 'text':
        return paragraph(b['text'])
    if b['type'] == 'equation':
        return Equation(b['text'])
    if b['type'] in ('dots', 'number_line'):
        return Diagram(b)
    path = (base / b['path']).resolve()
    with PILImage.open(path) as im:
        width = b.get('width', 300)
        height = width * im.height / im.width
    flow = Image(str(path), width, height)
    flow.hAlign = 'LEFT'
    return flow


def write_pdf(path, spec, base, answers=False, draft=False):
    title, page_count = spec['title'], [0]
    kind = '参考答案' if answers else '题目'
    if draft:
        kind = '待核对 · ' + kind
    title_size = 19
    while pdfmetrics.stringWidth(title, 'MathCNBold', title_size) > CONTENT_W - 120 and title_size > 12:
        title_size -= 1
    if pdfmetrics.stringWidth(title, 'MathCNBold', title_size) > CONTENT_W - 120:
        raise ValueError('title too long for header; use a shorter title')

    def header(c, doc):
        page_count[0] = doc.page
        c.saveState()
        c.setFillColor(GREEN)
        c.setFont('MathCNBold', title_size)
        c.drawString(MARGIN, PAGE_H - 49, title)
        c.setFillColor(INK)
        c.setFont('MathCN', 11)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 49, kind)
        c.setFont('MathCN', 9)
        c.drawString(MARGIN, PAGE_H - 72, '按来源、原页码和题号对应')
        if not answers:
            c.drawRightString(PAGE_W - MARGIN, PAGE_H - 72, '姓名：____________  日期：____________')
        c.setStrokeColor(colors.HexColor('#D4DDDA'))
        c.line(MARGIN, PAGE_H - 83, PAGE_W - MARGIN, PAGE_H - 83)
        c.setFont('MathCN', 8)
        c.setFillColor(colors.HexColor('#686868'))
        c.drawString(MARGIN, 27, title + ' · ' + kind)
        c.drawRightString(PAGE_W - MARGIN, 27, str(doc.page))
        c.restoreState()

    story = []
    for q in spec['questions']:
        heading = paragraph(label(q), 11.5, GREEN, True)
        flows = []
        if q['status'] == 'needs_review':
            flows.append(paragraph('待核对：' + q['issue'], 11, colors.HexColor('#9B4E12')))
        if answers:
            if q['status'] == 'ready':
                flows += [paragraph(t, 11.2) for t in q['answer']]
                flows.append(paragraph('核验：' + q['verification'], 10.5))
        else:
            flows += [block_flow(b, base) for b in q['blocks']]
            flows.append(Spacer(1, q.get('work_space', 40)))
        # Keep the source label with the first content block. Longer content can continue.
        story.append(KeepTogether([heading, flows[0]]))
        story.extend(flows[1:])
        story.append(Spacer(1, 14))
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=99, bottomMargin=52, title=title + ' - ' + kind,
                            author='题库整理', pageCompression=1)
    doc.build(story, onFirstPage=header, onLaterPages=header)
    return page_count[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path, help='reviewed JSON; image paths are relative to this file')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--font', help='Chinese TrueType font, including compatible .ttc')
    parser.add_argument('--bold-font')
    parser.add_argument('--draft', action='store_true', help='visibly label unresolved items and filenames')
    parser.add_argument('--questions-only', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding='utf-8-sig'))
        base = args.spec.resolve().parent
        validate(spec, base, args.draft, args.questions_only)
        font = register_fonts(args.font, args.bold_font)
        prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', spec['title']).strip(' .')
        if not prefix or len(prefix) > 80:
            raise ValueError('title must yield a filename of 1..80 characters')
        if args.draft:
            prefix += '_待核对'
        names = [prefix + '_题目.pdf']
        if not args.questions_only:
            names.append(prefix + '_答案.pdf')
        manifest_name = prefix + '_生成记录.json'
        for name in names + [manifest_name]:
            if (args.output_dir / name).exists() and not args.overwrite:
                raise ValueError(f'output exists: {name}; choose a new title/directory or explicitly use --overwrite')
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.building-', dir=args.output_dir) as temp:
            staging = Path(temp)
            records = []
            for index, name in enumerate(names):
                count = write_pdf(staging / name, spec, base, answers=index == 1, draft=args.draft)
                records.append({'file': name, 'pages': count})
            manifest = {'title': spec['title'], 'draft': args.draft, 'font': font,
                        'question_ids': [q['id'] for q in spec['questions']], 'files': records,
                        'validation': 'Structure and rendering completed; semantic and visual checks must be performed separately.'}
            (staging / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            for name in names + [manifest_name]:
                os.replace(staging / name, args.output_dir / name)
        for name in names:
            print((args.output_dir / name).resolve())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
