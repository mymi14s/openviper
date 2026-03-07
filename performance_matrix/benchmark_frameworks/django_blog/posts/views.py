import json

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import BlogPost


def _serialize(post: BlogPost) -> dict:
    return {
        "id": post.pk,
        "title": post.title,
        "content": post.content,
        "created_at": post.created_at.isoformat(),
    }


@method_decorator(csrf_exempt, name="dispatch")
class PostListView(View):
    def post(self, request):
        data = json.loads(request.body)
        post = BlogPost.objects.create(title=data["title"], content=data["content"])
        return JsonResponse(_serialize(post), status=201)


class PostDetailView(View):
    def get(self, request, id: int):
        try:
            post = BlogPost.objects.get(pk=id)
        except BlogPost.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)
        return JsonResponse(_serialize(post))
