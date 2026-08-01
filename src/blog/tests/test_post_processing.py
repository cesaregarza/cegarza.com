import unittest

from django.test import SimpleTestCase

from blog.post_processing import (
    HeadingSlugger,
    PostProcessor,
    build_toc_hierarchy,
    collect_glossary_terms,
    format_minutes,
    html_has_math,
    inject_collapsible_readtimes,
    render_blog_body,
)


class TestMathDetection(SimpleTestCase):
    def test_html_has_math_delimiters(self):
        self.assertTrue(html_has_math(r"text \(x\) more"))
        self.assertTrue(html_has_math("block $$x$$ here"))
        self.assertTrue(html_has_math(r"display \[x\] here"))
        self.assertTrue(html_has_math("[latex]x[/latex]"))
        self.assertFalse(html_has_math("plain prose with no math"))
        self.assertFalse(html_has_math(""))

    def test_render_blog_body_reports_inline_math(self):
        body = [("markdown", r"Here is \(x^2\) inline.")]
        self.assertTrue(render_blog_body(body)["math_present"])

    def test_render_blog_body_reports_display_math(self):
        body = [("markdown", "A display block $$E = mc^2$$ here.")]
        self.assertTrue(render_blog_body(body)["math_present"])

    def test_render_blog_body_plain_prose_has_no_math(self):
        body = [("markdown", "Just some ordinary prose with no delimiters.")]
        self.assertFalse(render_blog_body(body)["math_present"])

    def test_render_blog_body_empty_has_no_math(self):
        self.assertFalse(render_blog_body([])["math_present"])


class TestHeadingSlugger(unittest.TestCase):
    def test_basic_slug(self):
        slugger = HeadingSlugger()
        self.assertEqual(slugger.ensure("Hello World"), "h-hello-world")

    def test_strips_special_chars(self):
        slugger = HeadingSlugger()
        self.assertEqual(slugger.ensure("What's the deal?"), "h-whats-the-deal")

    def test_deduplication(self):
        slugger = HeadingSlugger()
        self.assertEqual(slugger.ensure("Intro"), "h-intro")
        self.assertEqual(slugger.ensure("Intro"), "h-intro-2")
        self.assertEqual(slugger.ensure("Intro"), "h-intro-3")

    def test_existing_id_preserved(self):
        slugger = HeadingSlugger()
        self.assertEqual(slugger.ensure("Anything", "custom-id"), "custom-id")

    def test_existing_id_conflict(self):
        slugger = HeadingSlugger()
        slugger.ensure("First", "my-id")
        self.assertEqual(slugger.ensure("Second", "my-id"), "my-id-2")

    def test_empty_text(self):
        slugger = HeadingSlugger()
        self.assertEqual(slugger.ensure(""), "h-section")

    def test_none_text(self):
        slugger = HeadingSlugger()
        self.assertEqual(slugger.ensure(None), "h-section")


class TestFormatMinutes(unittest.TestCase):
    def test_zero_words(self):
        self.assertEqual(format_minutes(0), "1 min")

    def test_short_text(self):
        self.assertEqual(format_minutes(110), "1 min")

    def test_one_minute(self):
        self.assertEqual(format_minutes(220), "1 min")

    def test_five_minutes(self):
        self.assertEqual(format_minutes(1100), "5 min")

    def test_custom_wpm(self):
        self.assertEqual(format_minutes(500, words_per_minute=100), "5 min")


class TestBuildTocHierarchy(unittest.TestCase):
    def test_flat_h1s(self):
        items = [
            {"id": "a", "text": "A", "level": "h1"},
            {"id": "b", "text": "B", "level": "h1"},
        ]
        result = build_toc_hierarchy(items)
        self.assertEqual(result[0]["parent_id"], "")
        self.assertEqual(result[1]["parent_id"], "")

    def test_h2_under_h1(self):
        items = [
            {"id": "a", "text": "A", "level": "h1"},
            {"id": "b", "text": "B", "level": "h2"},
        ]
        result = build_toc_hierarchy(items)
        self.assertEqual(result[1]["parent_id"], "a")

    def test_h3_under_h2_and_h1(self):
        items = [
            {"id": "a", "text": "A", "level": "h1"},
            {"id": "b", "text": "B", "level": "h2"},
            {"id": "c", "text": "C", "level": "h3"},
        ]
        result = build_toc_hierarchy(items)
        self.assertEqual(result[2]["parent_id"], "b")
        self.assertEqual(result[2]["grandparent_id"], "a")

    def test_h2_without_h1(self):
        items = [{"id": "b", "text": "B", "level": "h2"}]
        result = build_toc_hierarchy(items)
        self.assertEqual(result[0]["parent_id"], "")

    def test_empty_items(self):
        self.assertEqual(build_toc_hierarchy([]), [])


class TestInjectCollapsibleReadtimes(unittest.TestCase):
    def test_replaces_placeholder(self):
        html = '<span data-collapsible-readtime>--</span>'
        result = inject_collapsible_readtimes(html, [440])
        self.assertIn("2 min", result)

    def test_multiple_placeholders(self):
        html = (
            '<span data-collapsible-readtime>--</span>'
            '<span data-collapsible-readtime>--</span>'
        )
        result = inject_collapsible_readtimes(html, [220, 660])
        self.assertIn("1 min", result)
        self.assertIn("3 min", result)

    def test_empty_counts(self):
        html = '<span data-collapsible-readtime>--</span>'
        result = inject_collapsible_readtimes(html, [])
        self.assertEqual(result, html)

    def test_no_placeholders(self):
        html = "<p>No collapsibles here</p>"
        result = inject_collapsible_readtimes(html, [220])
        self.assertEqual(result, html)


class TestPostProcessorWordCount(unittest.TestCase):
    def _count(self, text):
        proc = PostProcessor({}, False)
        return proc._count_words(text)

    def test_plain_words(self):
        self.assertEqual(self._count("hello world foo"), 3)

    def test_empty(self):
        self.assertEqual(self._count(""), 0)

    def test_none(self):
        self.assertEqual(self._count(None), 0)

    def test_contractions(self):
        self.assertEqual(self._count("don't can't won't"), 3)

    def test_math_inline(self):
        count = self._count("Here is $x^2$ inline")
        self.assertGreater(count, 0)

    def test_math_display(self):
        count = self._count("Before $$\\frac{a}{b}$$ after")
        self.assertGreater(count, 0)

    def test_latex_tags(self):
        count = self._count("Some [latex]\\int_0^1 f(x) dx[/latex] text")
        self.assertGreater(count, 0)


class TestPostProcessorHeadings(unittest.TestCase):
    def test_extracts_toc_items(self):
        proc = PostProcessor({}, False)
        proc.feed("<h1>Title</h1><h2>Sub</h2><h3>Deep</h3>")
        proc.close()
        self.assertEqual(len(proc.toc_items), 3)
        self.assertEqual(proc.toc_items[0]["text"], "Title")
        self.assertEqual(proc.toc_items[0]["level"], "h1")
        self.assertEqual(proc.toc_items[1]["text"], "Sub")
        self.assertEqual(proc.toc_items[2]["text"], "Deep")

    def test_assigns_ids(self):
        proc = PostProcessor({}, False)
        proc.feed("<h1>My Title</h1>")
        proc.close()
        output = "".join(proc.output)
        self.assertIn('id="h-my-title"', output)

    def test_preserves_existing_id(self):
        proc = PostProcessor({}, False)
        proc.feed('<h1 id="custom">Title</h1>')
        proc.close()
        output = "".join(proc.output)
        self.assertIn('id="custom"', output)

    def test_h4_not_in_toc(self):
        proc = PostProcessor({}, False)
        proc.feed("<h4>Not tracked</h4>")
        proc.close()
        self.assertEqual(len(proc.toc_items), 0)


class TestPostProcessorImages(unittest.TestCase):
    def test_adds_lazy_loading(self):
        proc = PostProcessor({}, False)
        proc.feed('<img src="test.jpg">')
        proc.close()
        output = "".join(proc.output)
        self.assertIn('loading="lazy"', output)
        self.assertIn('decoding="async"', output)

    def test_preserves_existing_loading(self):
        proc = PostProcessor({}, False)
        proc.feed('<img src="test.jpg" loading="eager">')
        proc.close()
        output = "".join(proc.output)
        self.assertIn('loading="eager"', output)
        self.assertNotIn('loading="lazy"', output)


class TestPostProcessorGlossary(unittest.TestCase):
    def test_manual_link(self):
        terms = {"api": {"term": "API", "definition": "Application Programming Interface"}}
        proc = PostProcessor(terms, False)
        proc.feed("<p>Learn about [[api]]</p>")
        proc.close()
        output = "".join(proc.output)
        self.assertIn("glossary-term", output)
        self.assertIn("API", output)

    def test_manual_link_with_display_text(self):
        terms = {"api": {"term": "API", "definition": "Application Programming Interface"}}
        proc = PostProcessor(terms, False)
        proc.feed("<p>The [[api|interface]]</p>")
        proc.close()
        output = "".join(proc.output)
        self.assertIn("interface", output)
        self.assertIn("glossary-term", output)

    def test_auto_link(self):
        terms = {"api": {"term": "API", "definition": "Application Programming Interface"}}
        proc = PostProcessor(terms, True)
        proc.feed("<p>The API is great</p>")
        proc.close()
        output = "".join(proc.output)
        self.assertIn("glossary-term", output)

    def test_no_link_in_code(self):
        terms = {"api": {"term": "API", "definition": "Application Programming Interface"}}
        proc = PostProcessor(terms, True)
        proc.feed("<code>API</code>")
        proc.close()
        output = "".join(proc.output)
        self.assertNotIn("glossary-term", output)

    def test_no_link_in_pre(self):
        terms = {"api": {"term": "API", "definition": "Application Programming Interface"}}
        proc = PostProcessor(terms, True)
        proc.feed("<pre>API</pre>")
        proc.close()
        output = "".join(proc.output)
        self.assertNotIn("glossary-term", output)


class TestPostProcessorDetailsCounting(unittest.TestCase):
    def test_closed_details_counted_deep_only(self):
        proc = PostProcessor({}, False)
        proc.feed(
            '<p>main words here</p>'
            '<details class="collapsible-block">'
            '<summary>Title</summary>'
            '<p>hidden content inside details</p>'
            '</details>'
        )
        proc.close()
        self.assertGreater(proc.total_main_words, 0)
        self.assertGreater(proc.total_deep_words, proc.total_main_words)

    def test_open_details_counted_both(self):
        proc = PostProcessor({}, False)
        proc.feed(
            '<details class="collapsible-block" open>'
            '<summary>Title</summary>'
            '<p>visible content inside details</p>'
            '</details>'
        )
        proc.close()
        self.assertEqual(proc.total_main_words, proc.total_deep_words)

    def test_collapsible_word_counts_tracked(self):
        proc = PostProcessor({}, False)
        proc.feed(
            '<details class="collapsible-block">'
            '<summary>S</summary>'
            '<p>one two three four five</p>'
            '</details>'
        )
        proc.close()
        self.assertEqual(len(proc.collapsible_word_counts), 1)
        self.assertEqual(proc.collapsible_word_counts[0], 5)


class TestCollectGlossaryTerms(unittest.TestCase):
    def _make_block(self, block_type, value):
        class FakeBlock:
            pass
        b = FakeBlock()
        b.block_type = block_type
        b.value = value
        return b

    def test_basic_terms(self):
        block = self._make_block("glossary", {
            "auto_link": False,
            "terms": [
                {"term": "API", "definition": "Interface", "aliases": ""},
            ],
        })
        terms, auto_link = collect_glossary_terms([block])
        self.assertIn("api", terms)
        self.assertFalse(auto_link)

    def test_auto_link_flag(self):
        block = self._make_block("glossary", {
            "auto_link": True,
            "terms": [
                {"term": "API", "definition": "Interface", "aliases": ""},
            ],
        })
        _, auto_link = collect_glossary_terms([block])
        self.assertTrue(auto_link)

    def test_aliases(self):
        block = self._make_block("glossary", {
            "auto_link": False,
            "terms": [
                {"term": "API", "definition": "Interface", "aliases": "REST,endpoint"},
            ],
        })
        terms, _ = collect_glossary_terms([block])
        self.assertIn("rest", terms)
        self.assertIn("endpoint", terms)
        self.assertEqual(terms["rest"]["term"], "API")

    def test_nested_in_collapsible(self):
        glossary = self._make_block("glossary", {
            "auto_link": False,
            "terms": [
                {"term": "API", "definition": "Interface", "aliases": ""},
            ],
        })
        collapsible = self._make_block("collapsible", {"content": [glossary]})
        terms, _ = collect_glossary_terms([collapsible])
        self.assertIn("api", terms)

    def test_empty_blocks(self):
        terms, auto_link = collect_glossary_terms([])
        self.assertEqual(terms, {})
        self.assertFalse(auto_link)
