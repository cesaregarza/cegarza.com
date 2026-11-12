"""Keyboard behaviour of the contents drawer, checked in a real browser.

Which elements take focus is decided by the stylesheet and the drawer script together, so a
rendered response cannot show it. These tests load the page in headless Chromium and press keys.
"""

import os
from datetime import date
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import Client, TestCase, override_settings
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright
from wagtail.models import Site

from blog.models import BlogIndexPage, BlogPage, ContentPage

HOST = "design.test"
POST_PATH = "/keyboard-note/"
PLAIN_POST_PATH = "/plain-note/"
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}
TAB_WALK_LIMIT = 200

FOCUS_STATE = """() => {
    const element = document.activeElement;
    const box = element.getBoundingClientRect();
    return {
        index: Array.from(document.querySelectorAll("*")).indexOf(element),
        tag: element.tagName.toLowerCase(),
        text: element.textContent.trim().replace(/\\s+/g, " ").slice(0, 60),
        classes: element.className,
        inDrawer: Boolean(element.closest("#postOutline")),
        inArticle: Boolean(element.closest("article.post")),
        left: Math.round(box.left),
        right: Math.round(box.right),
    };
}"""


@override_settings(ALLOWED_HOSTS=[HOST], SECURE_SSL_REDIRECT=False)
class ContentsDrawerKeyboardTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        index = BlogIndexPage(title="Field notes", slug="notes", default_author_name="A. Writer")
        Site.objects.get(is_default_site=True).root_page.add_child(instance=index)
        index.save_revision().publish()

        pages = (
            BlogPage(
                title="A note with three sections",
                slug=POST_PATH.strip("/"),
                date=date(2026, 7, 30),
                body=[
                    ("heading", "First observation"),
                    ("markdown", "Opening copy with a [reference](https://example.com/one)."),
                    ("heading", "Second observation"),
                    ("markdown", "Middle copy with a [reference](https://example.com/two)."),
                    ("heading", "Third observation"),
                    ("markdown", "Closing copy."),
                ],
            ),
            BlogPage(
                title="A note without sections",
                slug=PLAIN_POST_PATH.strip("/"),
                date=date(2026, 7, 29),
                body=[("markdown", "Short copy with a [reference](https://example.com/three).")],
            ),
            ContentPage(title="About", slug="about", body=[("markdown", "About this site.")]),
        )
        for page in pages:
            index.add_child(instance=page)
            page.save_revision().publish()
        Site.objects.create(hostname=HOST, port=443, site_name="Field notes", root_page=index)

        # Pages are rendered here because nothing may touch the database once the browser runs.
        client = Client()
        cls.documents = {}
        for path in (POST_PATH, PLAIN_POST_PATH):
            response = client.get(path, secure=True, HTTP_HOST=HOST)
            assert response.status_code == 200, (path, response.status_code)
            cls.documents[path] = response.content

    def setUp(self):
        # Playwright keeps an event loop running on this thread, and Django refuses database work
        # under one. It therefore starts after the test's own database setup and stops in a
        # cleanup, which runs before the test's transaction is rolled back.
        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        try:
            browser = playwright.chromium.launch()
        except PlaywrightError as error:
            # A missing browser may skip on a developer machine. In a hosted run a skip would
            # read as a pass, so there it fails.
            if os.environ.get("CI"):
                raise
            reason = str(error).strip().splitlines()[0]
            self.skipTest(f"no browser (uv run playwright install chromium): {reason}")
        self.addCleanup(browser.close)
        self.page = browser.new_page(viewport=PHONE)
        self.page.route("**/*", self.serve)
        self.drawer = self.page.locator("#postOutline")
        self.toggle = self.page.locator("#postTocDrawerToggle")

    def serve(self, route):
        """Answer the browser from the rendered pages and the static files; nothing leaves the test."""
        url = urlsplit(route.request.url)
        if url.hostname != HOST:
            route.abort()
        elif url.path in self.documents:
            route.fulfill(body=self.documents[url.path], content_type="text/html; charset=utf-8")
        elif url.path.startswith(settings.STATIC_URL) and (
            asset := finders.find(url.path.removeprefix(settings.STATIC_URL))
        ):
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404)

    def open_post(self, path=POST_PATH, viewport=PHONE):
        self.page.set_viewport_size(viewport)
        self.page.goto(f"https://{HOST}{path}")

    def focused(self):
        return self.page.evaluate(FOCUS_STATE)

    def tab_stops(self):
        """Every element Tab reaches, in order, over one full lap of the page."""
        stops = []
        for _ in range(TAB_WALK_LIMIT):
            self.page.keyboard.press("Tab")
            stop = self.focused()
            if stop["tag"] == "body":
                continue
            if stops and stop["index"] == stops[0]["index"]:
                return stops
            stops.append(stop)
        self.fail(f"Tab did not come back round within {TAB_WALK_LIMIT} presses")

    def open_drawer_by_keyboard(self):
        self.toggle.focus()
        self.page.keyboard.press("Enter")
        expect(self.toggle).to_have_attribute("aria-expanded", "true")

    def test_a_closed_drawer_takes_no_keyboard_focus(self):
        self.open_post()
        expect(self.toggle).to_have_attribute("aria-expanded", "false")

        self.toggle.focus()
        self.page.keyboard.press("Tab")
        after_toggle = self.focused()
        self.assertFalse(after_toggle["inDrawer"], after_toggle)

        stops = self.tab_stops()
        self.assertIn("contents", [stop["text"] for stop in stops])
        self.assertEqual([stop for stop in stops if stop["inDrawer"]], [])
        expect(self.drawer).to_be_hidden()

    def test_a_post_without_contents_keeps_its_unopenable_rail_out_of_the_tab_order(self):
        self.open_post(PLAIN_POST_PATH)
        expect(self.toggle).to_have_count(0)

        stops = self.tab_stops()
        self.assertTrue(any(stop["inArticle"] for stop in stops), stops)
        self.assertEqual([stop for stop in stops if stop["inDrawer"]], [])

    def test_opening_the_drawer_by_keyboard_leads_into_its_menu(self):
        self.open_post()
        self.open_drawer_by_keyboard()
        expect(self.drawer).to_be_focused()

        menu_links = self.drawer.locator(".site-nav__link")
        self.page.keyboard.press("Tab")
        expect(menu_links.first).to_be_focused()
        expect(menu_links.first).to_have_text("writing")
        expect(menu_links.first).to_be_in_viewport(ratio=1)

        for _ in range(menu_links.count()):
            self.page.keyboard.press("Tab")
        first_contents_link = self.drawer.locator(".post-toc__link").first
        expect(first_contents_link).to_be_focused()
        expect(first_contents_link).to_be_in_viewport(ratio=1)

    def test_closing_the_drawer_from_inside_returns_focus_to_its_control(self):
        self.open_post()
        self.open_drawer_by_keyboard()
        self.page.keyboard.press("Tab")
        self.assertTrue(self.focused()["inDrawer"], self.focused())

        self.page.keyboard.press("Escape")
        expect(self.toggle).to_have_attribute("aria-expanded", "false")
        expect(self.toggle).to_be_focused()
        expect(self.drawer).to_be_hidden()

        self.page.keyboard.press("Tab")
        after_toggle = self.focused()
        self.assertFalse(after_toggle["inDrawer"], after_toggle)

    def test_following_a_contents_link_closes_the_drawer_and_frees_focus(self):
        self.open_post()
        self.open_drawer_by_keyboard()
        link = self.drawer.locator(".post-toc__link").nth(1)
        target = link.get_attribute("href")
        link.focus()
        self.page.keyboard.press("Enter")

        expect(self.toggle).to_have_attribute("aria-expanded", "false")
        self.assertEqual(urlsplit(self.page.url).fragment, target.removeprefix("#"))
        self.assertFalse(self.focused()["inDrawer"], self.focused())

        self.page.keyboard.press("Tab")
        after_heading = self.focused()
        self.assertTrue(after_heading["inArticle"], after_heading)
        expect(self.drawer).to_be_hidden()

    def test_the_desktop_rail_stays_visible_whatever_the_phone_drawer_was_doing(self):
        for drawer_was_open in (False, True):
            with self.subTest(drawer_was_open=drawer_was_open):
                self.open_post()
                if drawer_was_open:
                    self.open_drawer_by_keyboard()
                else:
                    expect(self.drawer).to_be_hidden()

                self.page.set_viewport_size(DESKTOP)
                expect(self.drawer).to_be_visible()
                expect(self.toggle).to_be_hidden()

                contents_stops = [
                    stop for stop in self.tab_stops() if "post-toc__link" in stop["classes"]
                ]
                self.assertEqual(
                    [stop["text"] for stop in contents_stops],
                    ["First observation", "Second observation", "Third observation"],
                )
                for stop in contents_stops:
                    self.assertTrue(0 <= stop["left"] < stop["right"] <= DESKTOP["width"], stop)
