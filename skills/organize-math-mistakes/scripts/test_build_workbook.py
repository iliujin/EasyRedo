"""Exercise real PDF output and input rejection; run with the same Python as the builder."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pypdf import PdfReader

BUILDER = Path(__file__).with_name('build_workbook.py')


def sample():
    return {
        'title': '错题整理测试',
        'questions': [{
            'id': 'A-p7-q6-4', 'source': 'A教材', 'page': '7', 'number': '6（4）',
            'status': 'ready', 'selection_reason': '仅第（4）小题有圈选',
            'blocks': [{'type': 'text', 'text': '2个5相乘得（       ）。'},
                       {'type': 'equation', 'text': '□ ○ □ = □'}],
            'answer': ['25。'], 'verification': '5 × 5 = 25。', 'work_space': 40,
        }],
    }


class WorkbookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='math-skill-test-')
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_build(self, spec, *flags):
        path = self.root / 'questions.json'
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        result = subprocess.run(
            [sys.executable, '-X', 'utf8', str(BUILDER), str(path), '--output-dir', str(self.root / 'out'), *flags],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        return result

    def test_question_answer_content_and_subquestion_label(self):
        # Catches answer leakage, incorrect label placement, and a nonfunctional builder.
        result = self.run_build(sample())
        self.assertEqual(result.returncode, 0, result.stderr)
        q = ''.join(p.extract_text() for p in PdfReader(self.root / 'out' / '错题整理测试_题目.pdf').pages)
        a = ''.join(p.extract_text() for p in PdfReader(self.root / 'out' / '错题整理测试_答案.pdf').pages)
        self.assertIn('第6题（4）', q)
        self.assertIn('2个5相乘', q)
        self.assertNotIn('25。', q)
        self.assertIn('25。', a)

    def test_duplicate_ids_are_rejected(self):
        spec = sample()
        spec['questions'].append(copy.deepcopy(spec['questions'][0]))
        result = self.run_build(spec)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr.lower())

    def test_different_books_same_page_number_are_allowed(self):
        spec = sample()
        other = copy.deepcopy(spec['questions'][0])
        other.update(id='B-p7-q6-4', source='B教材')
        spec['questions'].append(other)
        result = self.run_build(spec)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pending_items_cannot_be_published_as_final(self):
        spec = sample()
        spec['questions'][0].update(status='needs_review', issue='后侧方块无法辨认')
        result = self.run_build(spec)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('needs_review', result.stderr)
        self.assertFalse((self.root / 'out' / '错题整理测试_题目.pdf').exists())

    def test_draft_names_and_visible_review_notes(self):
        spec = sample()
        spec['questions'][0].update(status='needs_review', issue='后侧方块无法辨认', answer=[])
        result = self.run_build(spec, '--draft')
        self.assertEqual(result.returncode, 0, result.stderr)
        pdf = self.root / 'out' / '错题整理测试_待核对_题目.pdf'
        self.assertTrue(pdf.exists())
        text = ''.join(p.extract_text() for p in PdfReader(pdf).pages)
        self.assertIn('待核对', text)
        self.assertIn('后侧方块无法辨认', text)

    def test_missing_image_does_not_silently_disappear(self):
        spec = sample()
        spec['questions'][0]['blocks'].append({'type': 'image', 'path': 'missing.png'})
        result = self.run_build(spec)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing.png', result.stderr)

    def test_existing_output_is_not_overwritten_by_default(self):
        first = self.run_build(sample())
        self.assertEqual(first.returncode, 0, first.stderr)
        p = self.root / 'out' / '错题整理测试_题目.pdf'
        old = p.read_bytes()
        second = self.run_build(sample())
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(p.read_bytes(), old)

    def test_long_workbook_paginates_and_keeps_last_item(self):
        spec = sample()
        spec['questions'] = []
        for n in range(20):
            q = copy.deepcopy(sample()['questions'][0])
            q.update(id=f'A-p7-q{n}', number=str(n + 1), work_space=100)
            q['blocks'][0]['text'] = f'核对标记{n + 1}：请写出算式。'
            spec['questions'].append(q)
        result = self.run_build(spec)
        self.assertEqual(result.returncode, 0, result.stderr)
        reader = PdfReader(self.root / 'out' / '错题整理测试_题目.pdf')
        self.assertGreater(len(reader.pages), 1)
        self.assertIn('核对标记20', reader.pages[-1].extract_text())

    def test_oversize_equation_is_reported_instead_of_clipped(self):
        spec = sample()
        spec['questions'][0]['blocks'] = [{'type': 'equation', 'text': '12345 + ' * 30}]
        result = self.run_build(spec)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('equation', result.stderr.lower())


if __name__ == '__main__':
    unittest.main()
