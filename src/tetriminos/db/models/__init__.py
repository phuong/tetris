from .manager import SignalManager, CachedManager

from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

"""
This abstract class include 2 field created_at and updated_at into
children class and update updated_at field once instance has been saved
"""
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('Created at'), default=timezone.now)
    updated_at = models.DateTimeField(_('Updated at'), default=timezone.now)

    class Meta:
        abstract = True

    def save(self, **kwargs):
        self.updated_at = timezone.now()
        return super(TimeStampedModel, self).save(**kwargs)
