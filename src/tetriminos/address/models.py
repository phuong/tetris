from django.db import models


class Country(models.Model):
    code = models.CharField('Country code', max_length=2, primary_key=True)
    name = models.CharField('Country name', max_length=50)

    def __str__(self):
        return self.name or None


class State(models.Model):
    name = models.CharField('State/Province name', max_length=150)
    code = models.CharField('State Code', max_length=5, blank=True)
    country_code = models.CharField('Country code', max_length=2)
    timezone = models.CharField('Timezone', max_length=128)

    def __str__(self):
        return self.name or None

    class Meta:
        ordering = ('country_code', 'name',)


class AddressedModel(models.Model):
    address = models.CharField('Address', max_length=255, blank=True, null=True)
    postal_code = models.CharField('Postal code', max_length=6, blank=True, null=True)
    city = models.CharField('City', max_length=150, blank=True, null=True)
    state = models.ForeignKey(State, null=True)
    country = models.ForeignKey(Country, to_field='code', default='CA')

    class Meta:
        abstract = True
