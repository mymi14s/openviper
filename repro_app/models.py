from openviper.db.models import Model
from openviper.db import fields

class MyModel(Model):
    class Meta:
        table_name = "my_model"
    title = fields.CharField(max_length=100)
