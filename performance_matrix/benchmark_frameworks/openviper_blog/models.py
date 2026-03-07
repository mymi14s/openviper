"""BlogPost model for the OpenViper benchmark app."""

from openviper.db.fields import CharField, DateTimeField, TextField
from openviper.db.models import Model


class BlogPost(Model):
    _app_name = "openviper_blog"

    title = CharField(max_length=500)
    content = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "posts"
