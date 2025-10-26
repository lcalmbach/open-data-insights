from django.db import models

class NaturalKeyManager(models.Manager):
    """
    Generic manager that lets you define which fields make up
    a model's natural key. Example:

        class StoryTemplateManager(NaturalKeyManager):
            lookup_fields = ('slug',)
    """
    lookup_fields = ()

    def get_by_natural_key(self, *args):
        return self.get(**dict(zip(self.lookup_fields, args)))
