"""Regression coverage for GitHub issue #6 without importing Anki."""
import ast
from pathlib import Path
import re
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "__init__.py"
tree = ast.parse(SOURCE.read_text())
names = {
    "_esc",
    "_attr",
    "_html_txt",
    "_normalize_internal_lookup_href",
    "_normalize_internal_lookup_links",
    "_render_gloss_line",
    "_structured_kind",
    "_structured_children",
    "_structured_class",
    "_render_structured_html",
}
functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name in names
]
assignments = [
    node for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "_STRUCTURED_TAGS" for target in node.targets)
]
namespace = {"re": re}
exec(compile(ast.Module(body=assignments + functions, type_ignores=[]), str(SOURCE), "exec"), namespace)


class InternalLookupLinkTest(unittest.TestCase):
    def test_structured_link_uses_q_and_preserves_other_parameters(self):
        node = {
            "tag": "a",
            "href": "?query=蟇股&wildcards=off",
            "content": "蟇股",
        }
        result = namespace["_render_structured_html"](node)
        self.assertIn('href="?q=蟇股&amp;wildcards=off"', result)
        self.assertNotIn("?query=", result)

    def test_imported_html_is_fixed_at_render_time(self):
        html = '<a href="?query=蟇蛙&amp;wildcards=off"><span>蟇蛙</span></a>'
        result = namespace["_render_gloss_line"]("@@html\t" + html)
        self.assertIn('href="?q=蟇蛙&amp;wildcards=off"', result)
        self.assertNotIn("?query=", result)

    def test_external_and_existing_q_links_are_unchanged(self):
        normalize = namespace["_normalize_internal_lookup_href"]
        self.assertEqual(normalize("?q=既存&wildcards=off"), "?q=既存&wildcards=off")
        self.assertEqual(normalize("https://example.com/?query=test"), "https://example.com/?query=test")


if __name__ == "__main__":
    unittest.main()
