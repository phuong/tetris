from django.contrib import admin
from tetriminos.address.models import Country, State


class CountryAdmin(admin.ModelAdmin):
    pass

class StateAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'country_code'
    )

admin.site.register(Country, CountryAdmin)
admin.site.register(State, StateAdmin)


