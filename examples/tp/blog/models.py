"""Blog models — Post and Comment."""

from openviper.db import fields
from openviper.db.models import Model


class Post(Model):
    """A blog post.

    MODEL_EVENTS wired in settings:
        * ``after_insert``  → ``blog.events.create_likes``
        * ``after_delete``  → ``blog.events.cleanup_comments``
    """

    class Meta:
        table_name = "blog_post"

    title = fields.CharField(max_length=255)
    body = fields.TextField(null=True)
    author_id = fields.IntegerField(null=True)
    published = fields.BooleanField(default=False)
    created_at = fields.DateTimeField(auto_now_add=True, null=True)
    updated_at = fields.DateTimeField(auto_now=True, null=True)


class Comment(Model):
    """A comment on a blog post.

    MODEL_EVENTS wired in settings:
        * ``after_insert``  → ``blog.events.notify_post_author``
    """

    class Meta:
        table_name = "blog_comment"

    post_id = fields.IntegerField()
    author_id = fields.IntegerField(null=True)
    body = fields.TextField()
    created_at = fields.DateTimeField(auto_now_add=True, null=True)
