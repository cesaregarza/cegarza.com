import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.dispatch import receiver
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from modelcluster.models import ClusterableModel
from wagtail import blocks
from wagtail.admin.panels import FieldPanel, HelpPanel, InlinePanel
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Orderable, Page, Site
from wagtail.signals import page_published
from wagtail.snippets.models import register_snippet
from wagtailmarkdown.blocks import MarkdownBlock

from .post_processing import format_minutes, render_blog_body
from .site_urls import page_path_for_site

BLOG_BODY_RENDER_VERSION = "console-v1"
APPLET_CATALOG = (
    {
        "title": "Loser’s bracket, winner’s bias",
        "path": "applets/loser-winner.html",
    },
    {
        "title": "PageRank, forward and reverse",
        "path": "applets/pagerank-forward-reverse.html",
    },
    {
        "title": "Volume cancellation",
        "path": "applets/pagerank-volume-cancel.html",
    },
)


class CodeBlock(blocks.StructBlock):
    language = blocks.CharBlock(
        required=False,
        help_text="Language hint for syntax highlighting (e.g. python, js).",
    )
    code = blocks.TextBlock()

    class Meta:
        icon = "code"
        label = "Code"


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock(required=True)
    caption = blocks.CharBlock(
        required=False,
        help_text="Optional caption shown under the image.",
    )

    def bulk_to_python(self, values):
        normalized = []
        for value in values:
            if value is None or isinstance(value, dict):
                normalized.append(value)
            else:
                normalized.append({"image": value, "caption": ""})
        return super().bulk_to_python(normalized)

    def to_python(self, value):
        if value is None:
            return super().to_python({"image": None, "caption": ""})
        if isinstance(value, dict):
            return super().to_python(value)
        # Backwards-compatibility: previous ImageChooserBlock value.
        return super().to_python({"image": value, "caption": ""})

    class Meta:
        icon = "image"
        label = "Image"


class GlossaryTermBlock(blocks.StructBlock):
    term = blocks.CharBlock(required=True)
    definition = blocks.TextBlock(required=True)
    aliases = blocks.CharBlock(
        required=False,
        help_text="Optional aliases (comma-separated).",
    )

    class Meta:
        icon = "help"
        label = "Glossary Term"


class GlossaryBlock(blocks.StructBlock):
    terms = blocks.ListBlock(GlossaryTermBlock(), help_text="Glossary terms for this post.")
    auto_link = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Auto-link matching terms in the post body.",
    )
    show_list = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Show a glossary list at this position.",
    )

    class Meta:
        icon = "list-ul"
        label = "Glossary"


class KeyTakeawayBlock(blocks.StructBlock):
    title = blocks.CharBlock(required=False, help_text="Optional label (e.g. Key takeaway).")
    color = blocks.ChoiceBlock(
        required=False,
        default="blue",
        choices=[
            ("blue", "Blue"),
            ("purple", "Purple"),
            ("pink", "Pink"),
            ("gold", "Gold"),
        ],
        help_text="Accent color for the callout.",
    )
    body = MarkdownBlock(required=True)

    class Meta:
        icon = "success"
        label = "Key Takeaway"


class AppletEmbedBlock(blocks.StructBlock):
    title = blocks.CharBlock(
        required=True,
        help_text="Accessible title for the iframe content.",
    )
    src = blocks.CharBlock(
        required=True,
        help_text="Path to an applet under /static/applets/ (for example /static/applets/loser-winner.html).",
    )
    lazy_load = blocks.BooleanBlock(
        required=False,
        default=True,
        help_text="Lazy-load the iframe (recommended). Disable only when immediate load is required.",
    )
    use_full_height = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Ignore max height and auto-resize iframe to full applet content height.",
    )
    max_height = blocks.IntegerBlock(
        required=False,
        min_value=120,
        help_text=(
            "Optional maximum iframe height (px). "
            "If applet content exceeds this, it scrolls inside the frame."
        ),
    )
    style_overrides = blocks.TextBlock(
        required=False,
        help_text="Optional inline style overrides for the iframe element (CSS declarations).",
    )

    def clean(self, value):
        cleaned = super().clean(value)
        src = (cleaned.get("src") or "").strip()
        if not src.startswith("/static/applets/"):
            raise ValidationError({"src": "Applet source must start with /static/applets/."})
        if src.startswith("//"):
            raise ValidationError({"src": "Protocol-relative URLs are not allowed."})
        return cleaned

    class Meta:
        icon = "media"
        label = "Applet Embed"


# Base blocks that can be used both at top-level and inside collapsible sections
BASE_BLOCKS = [
    ("markdown", MarkdownBlock()),
    ("paragraph", blocks.RichTextBlock()),
    ("heading", blocks.CharBlock(form_classname="title")),
    ("image", ImageBlock()),
    ("code", CodeBlock()),
    ("raw_html", blocks.RawHTMLBlock()),
    ("quote", blocks.TextBlock()),
    ("glossary", GlossaryBlock()),
    ("takeaway", KeyTakeawayBlock()),
    ("applet_embed", AppletEmbedBlock()),
]


class CollapsibleBlock(blocks.StructBlock):
    """A collapsible/spoiler block that can contain any other block types."""

    category = blocks.ChoiceBlock(
        required=False,
        default="",
        choices=[
            ("", "Default"),
            ("explainer", "Explainer"),
            ("technical", "Technical"),
            ("extra", "Extra"),
            ("subquest", "Side Quest"),
        ],
        help_text="Optional category to color-code the collapsible.",
    )
    title = blocks.CharBlock(
        required=True,
        help_text="The summary text shown when collapsed (e.g., 'Click to reveal')",
    )
    open_by_default = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="If checked, the content will be visible by default",
    )
    content = blocks.StreamBlock(
        BASE_BLOCKS,
        help_text="The content to show when expanded",
    )

    class Meta:
        icon = "collapse-down"
        label = "Collapsible Section"
        template = "blog/blocks/collapsible_block.html"


@register_snippet
class BlogAuthor(models.Model):
    """An author imported from Ghost or maintained in Wagtail."""

    ghost_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    bio = models.TextField(blank=True)
    website = models.URLField(blank=True)

    panels = [
        FieldPanel("name"),
        FieldPanel("slug"),
        FieldPanel("bio"),
        FieldPanel("website"),
    ]

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


@register_snippet
class BlogTag(models.Model):
    """A tag imported from Ghost or maintained in Wagtail."""

    ghost_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    panels = [
        FieldPanel("name"),
        FieldPanel("slug"),
        FieldPanel("description"),
    ]

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


@register_snippet
class BlogSeries(ClusterableModel):
    """An editorial sequence whose posts have an explicit reading order."""

    class Status(models.TextChoices):
        ONGOING = "ongoing", "Ongoing"
        COMPLETE = "complete", "Complete"

    title = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        help_text="Stable public URL segment used under /series/.",
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ONGOING,
    )
    next_up = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional public note about the next unpublished part.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    panels = [
        FieldPanel("title"),
        FieldPanel("slug"),
        FieldPanel("description"),
        FieldPanel("status"),
        FieldPanel("next_up"),
        InlinePanel("memberships", label="Parts"),
    ]

    class Meta:
        ordering = ["title", "pk"]
        verbose_name = "Blog series"
        verbose_name_plural = "Blog series"

    def __str__(self):
        return self.title


class GhostContentFields(models.Model):
    """Stable Ghost identity and timestamps used for repeatable imports."""

    ghost_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    ghost_uuid = models.UUIDField(unique=True, null=True, blank=True)
    ghost_created_at = models.DateTimeField(null=True, blank=True)
    ghost_updated_at = models.DateTimeField(null=True, blank=True)
    ghost_published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class GhostImageImport(models.Model):
    """Maps a Ghost media path to one Wagtail image for importer idempotence."""

    ghost_path = models.CharField(max_length=1024, unique=True)
    image = models.ForeignKey(
        "wagtailimages.Image",
        on_delete=models.CASCADE,
        related_name="+",
    )
    source_sha256 = models.CharField(max_length=64)

    class Meta:
        ordering = ["ghost_path"]

    def __str__(self):
        return self.ghost_path


class BlogIndexPage(Page):
    """Blog listing page."""

    intro = models.TextField(blank=True)
    default_author_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Default author name for site metadata and unattributed posts.",
    )

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
        FieldPanel("default_author_name"),
    ]

    subpage_types = ["blog.BlogPage", "blog.ContentPage"]
    parent_page_types = ["home.HomePage"]

    def get_context(self, request):
        context = super().get_context(request)
        posts = BlogPage.objects.child_of(self).live().public().order_by("-first_published_at")
        paginator = Paginator(posts, 9)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        site = Site.find_for_request(request)

        from .series import public_series_for_index

        all_series_groups = public_series_for_index(self, site=site)
        series_post_ids = {
            part.page.pk for group in all_series_groups for part in group.parts
        }
        current_posts = list(page_obj.object_list)
        lead_post_id = current_posts[0].pk if current_posts else None
        context["posts"] = page_obj
        context["page_obj"] = page_obj
        context["paginator"] = paginator
        context["is_paginated"] = paginator.num_pages > 1
        context["series_groups"] = all_series_groups if page_obj.number == 1 else []
        context["series_count"] = len(all_series_groups)
        context["standalone_posts"] = [
            post
            for post in current_posts
            if post.pk != lead_post_id and post.pk not in series_post_ids
        ]
        context["applets"] = APPLET_CATALOG
        context["applet_count"] = len(APPLET_CATALOG)
        context["blog_tags_enabled"] = getattr(settings, "BLOG_TAGS_ENABLED", False)
        return context

    class Meta:
        verbose_name = "Blog Index"


class BlogPage(GhostContentFields, Page):
    """Individual blog post page."""

    date = models.DateField("Post date", null=True, blank=True)
    is_featured = models.BooleanField(
        default=False,
        help_text="Feature this post in editorial selections.",
    )
    featured_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Optional hero/share image for the post.",
    )
    social_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Optional social preview image override (OpenGraph/Twitter cards).",
    )
    abstract = models.TextField(
        blank=True,
        help_text="Optional abstract/summary used for OpenGraph and meta descriptions.",
    )
    authors = ParentalManyToManyField(
        "blog.BlogAuthor",
        blank=True,
        related_name="blog_pages",
    )
    tags = ParentalManyToManyField(
        "blog.BlogTag",
        blank=True,
        related_name="blog_pages",
    )
    body = StreamField(
        BASE_BLOCKS + [("collapsible", CollapsibleBlock())],
        blank=True,
        use_json_field=True,
    )
    body_render_cache_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    body_rendered_html = models.TextField(
        blank=True,
        default="",
        editable=False,
    )
    body_rendered_toc_items = models.JSONField(
        blank=True,
        default=list,
        editable=False,
    )
    body_rendered_toc_crumb = models.CharField(
        max_length=255,
        blank=True,
        default="",
        editable=False,
    )
    body_rendered_readtime_main = models.CharField(
        max_length=32,
        blank=True,
        default="",
        editable=False,
    )
    body_rendered_readtime_deep = models.CharField(
        max_length=32,
        blank=True,
        default="",
        editable=False,
    )

    content_panels = Page.content_panels + [
        FieldPanel("date"),
        FieldPanel("is_featured"),
        FieldPanel("featured_image"),
        FieldPanel("authors"),
        FieldPanel("tags"),
        FieldPanel("body"),
    ]

    promote_panels = Page.promote_panels + [
        FieldPanel("social_image"),
        FieldPanel("abstract"),
        HelpPanel(
            template="blog/admin/share_preview_panel.html",
            heading="Share preview",
        ),
    ]

    parent_page_types = ["blog.BlogIndexPage"]
    subpage_types = []

    def _compute_body_render_cache_key(self):
        raw_data = getattr(self.body, "raw_data", self.body)
        try:
            payload = json.dumps(
                raw_data if raw_data is not None else [],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        except TypeError:
            payload = json.dumps(str(raw_data), ensure_ascii=True)
        versioned_payload = f"{BLOG_BODY_RENDER_VERSION}:{payload}"
        return hashlib.sha256(versioned_payload.encode("utf-8")).hexdigest()

    def _render_context_from_cache(self):
        fallback_readtime = format_minutes(0)
        return {
            "body_html": self.body_rendered_html,
            "toc_items": self.body_rendered_toc_items or [],
            "toc_crumb": self.body_rendered_toc_crumb or "",
            "readtime_main": self.body_rendered_readtime_main or fallback_readtime,
            "readtime_deep": self.body_rendered_readtime_deep or fallback_readtime,
        }

    def _persist_render_cache(self, body_cache_key, rendered):
        if not self.pk:
            return
        update_fields = {
            "body_render_cache_key": body_cache_key,
            "body_rendered_html": rendered.get("body_html", ""),
            "body_rendered_toc_items": rendered.get("toc_items", []) or [],
            "body_rendered_toc_crumb": rendered.get("toc_crumb", ""),
            "body_rendered_readtime_main": rendered.get("readtime_main", ""),
            "body_rendered_readtime_deep": rendered.get("readtime_deep", ""),
        }
        BlogPage.objects.filter(pk=self.pk).update(**update_fields)
        for key, value in update_fields.items():
            setattr(self, key, value)

    def get_render_context(self, request=None):
        body_cache_key = self._compute_body_render_cache_key()
        raw_data = getattr(self.body, "raw_data", self.body)
        body_has_content = bool(raw_data)
        has_usable_cache = bool(self.body_rendered_html) or not body_has_content
        if self.body_render_cache_key == body_cache_key and has_usable_cache:
            return self._render_context_from_cache()

        rendered = render_blog_body(self.body)
        is_admin_path = bool(request and (getattr(request, "path", "") or "").startswith("/admin/"))
        if self.live and self.pk and not is_admin_path:
            self._persist_render_cache(body_cache_key, rendered)
        return rendered

    def get_context(self, request):
        context = super().get_context(request)
        context.update(self.get_render_context(request=request))
        context["blog_tags_enabled"] = getattr(settings, "BLOG_TAGS_ENABLED", False)
        site = Site.find_for_request(request)
        if site:
            context["blog_index_url"] = page_path_for_site(self.get_parent(), site)

        from .series import public_series_context_for_page

        series_context = public_series_context_for_page(
            self,
            self.get_parent().specific,
            site=site,
        )
        context.update(series_context)
        if not series_context["post_series"]:
            siblings = list(
                BlogPage.objects.child_of(self.get_parent())
                .live()
                .public()
                .order_by("first_published_at", "pk")
            )
            current_index = next(
                (index for index, post in enumerate(siblings) if post.pk == self.pk),
                None,
            )
            if current_index is not None:
                if current_index > 0:
                    context["previous_post"] = siblings[current_index - 1]
                if current_index + 1 < len(siblings):
                    context["next_post"] = siblings[current_index + 1]
        return context

    @property
    def primary_author(self):
        return self.authors.first()

    class Meta:
        verbose_name = "Blog Post"


class BlogSeriesMembership(Orderable):
    """One ordered post placement inside a blog series."""

    series = ParentalKey(
        "blog.BlogSeries",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    page = models.ForeignKey(
        "blog.BlogPage",
        on_delete=models.CASCADE,
        related_name="series_memberships",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Use this series for the post band and in-series navigation.",
    )

    panels = [
        FieldPanel("page"),
        FieldPanel("is_primary"),
    ]

    def clean(self):
        super().clean()
        if not self.is_primary or not self.page_id:
            return
        if (
            BlogSeriesMembership.objects.filter(
                page_id=self.page_id,
                is_primary=True,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {"is_primary": "This post already has a primary series."}
            )

    class Meta:
        ordering = ["sort_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["series", "page"],
                name="blog_unique_series_page",
            ),
            models.UniqueConstraint(
                fields=["page"],
                condition=models.Q(is_primary=True),
                name="blog_one_primary_series_per_page",
            ),
        ]

    def __str__(self):
        return f"{self.series}: {self.page}"


class ContentPage(GhostContentFields, Page):
    """Generic, safely rendered content such as the imported About page."""

    body = StreamField(
        BASE_BLOCKS,
        blank=True,
        use_json_field=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel("body"),
    ]

    parent_page_types = ["blog.BlogIndexPage"]
    subpage_types = []

    class Meta:
        verbose_name = "Content Page"


@receiver(page_published)
def precompute_blog_body_render_cache(sender, **kwargs):
    instance = kwargs.get("instance")
    if instance is None:
        return
    specific = getattr(instance, "specific", instance)
    if not isinstance(specific, BlogPage):
        return
    rendered = render_blog_body(specific.body)
    body_cache_key = specific._compute_body_render_cache_key()
    specific._persist_render_cache(body_cache_key, rendered)
