"""Admin registration for the posts app."""

from __future__ import annotations

from moderation.models import ModerationLog

from openviper.admin import ActionResult, ChildTable, ModelAdmin, action, register

from .models import Comment, Post, PostLike, PostReport


class PostReportInline(ChildTable):
    model = PostReport
    fields = ["reported_by", "reason"]


class ModerationLogInline(ChildTable):
    model = ModerationLog
    fk_name = "object_id"
    extra_filters = {"content_type": "post"}
    fields = ["classification", "confidence", "reason", "reviewed"]


@register(Post)
class PostAdmin(ModelAdmin):
    list_display = ["id", "title", "author", "is_hidden", "likes_count", "created_at"]
    list_filter = ["is_hidden", "created_at"]
    search_fields = ["title", "content"]
    actions = ["mark_as_hidden", "mark_as_visible", "run_moderation"]
    child_tables = [PostReportInline, ModerationLogInline]

    @action(description="Mark selected posts as hidden")
    async def mark_as_hidden(self, queryset, request):
        count = await queryset.update(is_hidden=True)
        return ActionResult(
            success=True,
            count=count,
            message=f"Successfully hidden {count} posts.",
        )

    @action(description="Mark selected posts as visible")
    async def mark_as_visible(self, queryset, request):
        count = await queryset.update(is_hidden=False)
        return ActionResult(
            success=True,
            count=count,
            message=f"Successfully revealed {count} posts.",
        )

    @action(description="Run AI moderation on selected posts")
    async def run_moderation(self, queryset, request):
        from posts.tasks import moderate

        posts = await queryset.all()
        for post in posts:
            moderate.send(post.id)
        return ActionResult(
            success=True,
            count=len(posts),
            message=f"Queued AI moderation for {len(posts)} posts.",
        )


@register(Comment)
class CommentAdmin(ModelAdmin):
    list_display = ["id", "post", "author", "is_hidden", "created_at"]
    list_filter = ["is_hidden", "created_at"]
    search_fields = ["content"]


@register(PostLike)
class PostLikeAdmin(ModelAdmin):
    list_display = ["id", "post", "user", "created_at"]
    list_filter = ["created_at"]


@register(PostReport)
class PostReportAdmin(ModelAdmin):
    list_display = ["id", "post", "reported_by", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["reason"]
