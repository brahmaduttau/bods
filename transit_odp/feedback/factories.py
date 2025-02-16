import factory

from transit_odp.feedback.models import Feedback


class FeedbackFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Feedback

    page_url = factory.Faker("uri_path")
    satisfaction_rating = factory.Faker("random_int", min=1, max=5)
    comment = factory.Faker("paragraph")
