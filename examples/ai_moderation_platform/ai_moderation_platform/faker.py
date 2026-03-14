import random

from faker import Faker
from posts.models import Post

fake = Faker()


async def generate_posts(n):
    posts = []

    for _ in range(n):
        await Post.objects.create(
            author=random.choice([1, 2]),
            title=fake.sentence(nb_words=6),
            content=fake.text(max_nb_chars=500),
        )

    return posts
