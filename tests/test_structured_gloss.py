"""Exercise the actual renderer without importing Anki or opening a user database."""
import ast
import json
import os
from pathlib import Path
import re
import unittest


SOURCE = Path(os.environ.get('YOMILENS_SOURCE', Path(__file__).resolve().parents[1] / '__init__.py'))
tree = ast.parse(SOURCE.read_text())
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in {'_esc', '_html_txt', '_render_gloss_line'}]
handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == '_Handler')
functions.append(next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == '_render'))
ns = dict(re=re, json=json, PORT=8777, DB=None, DB_MODE=False,
          HANZI_WRITER=False, PREFER_KANJI_ON_CLICK=False, WEB_AUDIO_ENABLED=False,
          WEB_AUTO_SPEAK_ENABLED=False, POPUP_THEME='default', CUSTOM_CSS='', PITCH_STYLE='graph',
          _metadata_render=lambda *args, **kwargs: '', _render_term_actions=lambda *args: '',
          _get_popup_tpl=lambda: '{{ROWS}}')
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), ns)


class StructuredGlossTest(unittest.TestCase):
    def render(self, gloss):
        entry = dict(source='Kanken', source_id=7, reading='', glosses=[gloss], meta=[])
        return ns['_render'](None, [('test', [entry])], 'test')

    def test_html_whitespace_preserves_entire_document_and_resources(self):
        for newline in ['\n', '\r\n', '\r']:
            with self.subTest(newline=newline):
                payload = ('<table>' + newline + '<tr><th>異' + newline + '体' + newline + '字</th>'
                           '<td><img\tsrc="__YOMI_RESOURCE__kankenkj2%2F78D4.svg__"></td></tr>'
                           + newline + '</table><p>旧' + newline + '字</p>'
                           '<img src="__YOMI_RESOURCE__kankenkj2%2Fstd_78D4.png__">')
                result = self.render('  @@html\t' + payload + '  ')
                expected = payload.replace('__YOMI_RESOURCE__kankenkj2%2F78D4.svg__',
                                           'http://127.0.0.1:8777/api/resource?sid=7&path=kankenkj2%2F78D4.svg')
                expected = expected.replace('__YOMI_RESOURCE__kankenkj2%2Fstd_78D4.png__',
                                            'http://127.0.0.1:8777/api/resource?sid=7&path=kankenkj2%2Fstd_78D4.png')
                self.assertIn("<div class='structured-gloss'>" + expected + '</div>', result)
                self.assertNotIn('&lt;', result)
                self.assertNotIn('<br>', result)

    def test_plain_text_still_splits_and_escapes(self):
        self.assertIn('first<br>&lt;second&gt;', self.render('first\n<second>'))

    def test_other_records_still_split(self):
        result = self.render('@@sense\t1\tone\n@@note\ttwo')
        self.assertIn("class='sense-line'", result)
        self.assertIn("class='gloss-note'", result)


if __name__ == '__main__':
    unittest.main()
