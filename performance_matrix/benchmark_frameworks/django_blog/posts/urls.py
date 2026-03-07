from django.urls import path

from .views import PostDetailView, PostListView

urlpatterns = [
    path("posts", PostListView.as_view()),
    path("posts/<int:id>", PostDetailView.as_view()),
]
