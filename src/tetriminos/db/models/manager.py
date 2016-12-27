import six
import threading
import weakref
from hashlib import md5 as _md5

from django.conf import settings
from django.db import router
from django.db.models import Manager, Model
from django.db.models.signals import (
    post_save, post_delete, post_init, class_prepared
)
from django.utils.encoding import smart_text
from django.core.cache import cache
from django.utils.encoding import force_bytes

md5 = lambda x: _md5(force_bytes(x, errors='replace'))


class SignalManager(object):
    def _class_prepared(self, sender, **kwargs):
        post_save.connect(self.post_save, sender=sender, weak=False)
        post_delete.connect(self.post_delete, sender=sender, weak=False)

    def contribute_to_class(self, model, name):
        super(SignalManager, self).contribute_to_class(model, name)
        class_prepared.connect(self._class_prepared, sender=model)

    def post_save(self, instance, *args, **kwargs):
        """
        Triggered when a model bound to this manager is saved.
        """

    def post_delete(self, instance, *args, **kwargs):
        """
        Triggered when a model bound to this manager is deleted.
        """


class ImmutableDict(dict):
    def _setitem__(self, key, value):
        raise TypeError

    def _delitem__(self, key):
        raise TypeError


UNSAVED = ImmutableDict()

FIELD_DELIMITER = '-'


def _prep_value(model, key, value):
    if isinstance(value, Model):
        value = value.pk
    else:
        value = six.text_type(value)
    return value


def _prep_key(model, key):
    if key == 'pk':
        return model._meta.pk.name
    return key


def make_key(model, prefix, kwargs):
    kwargs_bits = []
    for k, v in sorted(six.iteritems(kwargs)):
        k = _prep_key(model, k)
        v = smart_text(_prep_value(model, k, v))
        kwargs_bits.append('%s=%s' % (k, v))
    kwargs_bits = ':'.join(kwargs_bits)
    # prefix:ModelName:md5(cachekey)
    return '%s:%s:%s' % (
        prefix,
        model.__name__,
        md5(kwargs_bits).hexdigest()
    )


class CachedManager(Manager):
    lookup_handlers = {
        'iexact': lambda x: x.upper(),
    }
    use_for_related_fields = True

    def __init__(self, *args, **kwargs):
        self.cache_fields = kwargs.pop('cache_fields', [])
        self.cache_timeout = kwargs.pop('cache_timeout', 60 * 60)
        self.cache_version = kwargs.pop('cache_version', None)
        self._local_cache = threading.local()
        super(CachedManager, self).__init__(*args, **kwargs)

    def _get_cache(self):
        if not hasattr(self._local_cache, 'value'):
            self._local_cache.value = weakref.WeakKeyDictionary()
        return self._local_cache.value

    def _set_cache(self, value):
        self._local_cache.value = value

    def _prepare_cache_fields(self):
        fields = []
        for item in self.cache_fields:
            if isinstance(item, str):
                fields.append(item)
            if isinstance(item, list):
                item.sort()
                fields.append(FIELD_DELIMITER.join(item))
        return fields

    def _generate_cache_version(self):
        version = md5('&'.join(sorted(f.attname for f in self.model._meta.fields)))
        return version.hexdigest()[:3]

    _cache = property(_get_cache, _set_cache)

    def _getstate__(self):
        d = self._dict__.copy()
        d.pop('_BaseManager__cache', None)
        d.pop('_BaseManager__local_cache', None)
        return d

    def _setstate__(self, state):
        self._dict__.update(state)
        self._local_cache = weakref.WeakKeyDictionary()

    def _class_prepared(self, sender, **kwargs):
        if not self.cache_fields:
            return
        self.cache_fields = self._prepare_cache_fields()

        if not self.cache_version:
            self.cache_version = self._generate_cache_version()

        post_init.connect(self._post_init, sender=sender, weak=False)
        post_save.connect(self._post_save, sender=sender, weak=False)
        post_delete.connect(self._post_delete, sender=sender, weak=False)

    def _cache_state(self, instance):
        """
        Updates the tracked state of an instance.
        """
        if instance.pk:
            self._cache[instance] = {
                f: self._value_for_field(instance, f) for f in self.cache_fields
                }
        else:
            self._cache[instance] = UNSAVED

    def _post_init(self, instance, **kwargs):
        """
        Stores the initial state of an instance.
        """
        self._cache_state(instance)

    def _post_save(self, instance, **kwargs):
        pk_name = instance._meta.pk.name
        pk_names = ('pk', pk_name)
        pk_val = instance.pk
        for key in self.cache_fields:
            if key in pk_names:
                continue
            # store pointers
            value = self._value_for_field(instance, key)
            cache.set(
                key=self._get_lookup_cache_key(**{key: value}),
                value=pk_val,
                timeout=self.cache_timeout,
                version=self.cache_version,
            )

        # Ensure we don't serialize the database into the cache
        db = instance._state.db
        instance._state.db = None
        # store actual object
        try:
            cache.set(
                key=self._get_lookup_cache_key(**{pk_name: pk_val}),
                value=instance,
                timeout=self.cache_timeout,
                version=self.cache_version,
            )
        except Exception as e:
            # logger.log
            pass
        instance._state.db = db

        # Kill off any keys which are no longer valid
        if instance in self._cache:
            for key in self.cache_fields:
                if key not in self._cache[instance]:
                    continue
                value = self._cache[instance][key]
                current_value = self._value_for_field(instance, key)
                if value != current_value:
                    cache.delete(
                        key=self._get_lookup_cache_key(**{key: value}),
                        version=self.cache_version,
                    )
        self._cache_state(instance)

    def _post_delete(self, instance, **kwargs):
        """
        Drops instance from all cache storages.
        """
        pk_name = instance._meta.pk.name
        for key in self.cache_fields:
            if key in ('pk', pk_name):
                continue
            # remove pointers
            value = self._value_for_field(instance, key)
            cache.delete(
                key=self._get_lookup_cache_key(**{key: value}),
                version=self.cache_version,
            )
        # remove actual object
        cache.delete(
            key=self._get_lookup_cache_key(**{pk_name: instance.pk}),
            version=self.cache_version,
        )

    def _get_lookup_cache_key(self, **kwargs):
        return make_key(self.model, 'modelcache', kwargs)

    def _value_for_field(self, instance, key):
        if key == 'pk':
            return instance.pk

        # Single key
        if FIELD_DELIMITER not in key:
            field = instance._meta.get_field(key)
            return getattr(instance, field.attname)

        # Multiple key
        keys = key.split(FIELD_DELIMITER)
        values = []
        for key in keys:
            field = instance._meta.get_field(key)
            values.append(str(getattr(instance, field.attname)))
        return FIELD_DELIMITER.join(values)

    def contribute_to_class(self, model, name):
        super(CachedManager, self).contribute_to_class(model, name)
        class_prepared.connect(self._class_prepared, sender=model)

    def _get_kwargs_key_val(self, **kwargs):
        # Single condition
        if len(kwargs) == 1:
            key, value = next(six.iteritems(kwargs))
            if key.endswith('__exact'):
                key = key.split('__exact', 1)[0]
            return key, value
        keys = []
        values = []
        # Multiple condition
        for key in sorted(kwargs.iterkeys()):
            if key.endswith('__exact'):
                key = key.split('__exact', 1)[0]
            keys.append(key)
            value = kwargs[key]
            # Store everything by key references
            if isinstance(value, Model):
                value = value.pk
            if not isinstance(value, str):
                value = str(value)
            values.append(value)
        return FIELD_DELIMITER.join(keys), FIELD_DELIMITER.join(values)

    def get_from_cache(self, **kwargs):
        """
        Wrap Manager.get method
        :return: Model object
        """
        if not self.cache_fields:
            return super(CachedManager, self).get(**kwargs)

        key, value = self._get_kwargs_key_val(**kwargs)
        pk_name = self.model._meta.pk.name
        if key == 'pk':
            key = pk_name

        if key not in self.cache_fields:
            return super(CachedManager, self).get(**kwargs)

        cache_key = self._get_lookup_cache_key(**{key: value})
        retval = cache.get(cache_key, version=self.cache_version)
        if retval is None:
            result = super(CachedManager, self).get(**kwargs)
            self._post_save(instance=result)
            return result

        # Hit pointer instead of actual instance, return get by pk_name
        if key != pk_name:
            return self.get_from_cache(**{pk_name: retval})

        # Unexpected type
        if type(retval) != self.model:
            message = 'Unexpected value type returned from cache'
            if settings.DEBUG:
                raise ValueError(message)
            # logger.log()
            return super(CachedManager, self).get(**kwargs)

        # Unexpected value
        if value.isdigit():
            value = int(value)
        if key == pk_name and value != retval.pk:
            message = 'Unexpected value returned from cache'
            if settings.DEBUG:
                raise ValueError(message)
            # Logger.log
            return super(CachedManager, self).get(**kwargs)

        # Super.get behaviors
        retval._state.db = router.db_for_read(self.model, **kwargs)
        return retval

    def get(self, from_cache=False, **kwargs):
        """
        Overwrite super.get method.
        :param from_cache: set true to lookup from cache first
        :return:
        """
        if from_cache:
            return self.get_from_cache(**kwargs)
        return super(CachedManager, self).get(**kwargs)

    def uncache_object(self, instance_id):
        """
        Uncache object, manual call from outer function
        :param instance_id: Model or instance.pk
        :return: None
        """
        if isinstance(instance_id, Model):
            instance_id = instance_id.pk
        pk_name = self.model._meta.pk.name
        cache_key = self._get_lookup_cache_key(**{pk_name: instance_id})
        cache.delete(cache_key, version=self.cache_version)
