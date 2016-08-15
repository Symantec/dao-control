# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012 Cloudscaling Group, Inc.
# Copyright 2016 Symantec.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
SQLAlchemy models.
"""
import copy
import datetime
import json
import six

from sqlalchemy import Column, Integer
from sqlalchemy import DateTime
from sqlalchemy.ext import mutable
from sqlalchemy.orm import object_mapper
from sqlalchemy.types import TypeDecorator, TEXT


MutableDict = mutable.MutableDict


class ModelBase(six.Iterator):
    """Base class for models."""
    __table_initialized__ = False

    def save(self, session):
        """Save this object."""
        with session.begin(subtransactions=True):
            session.add(self)
            session.flush()

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
        return hasattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    @property
    def _extra_keys(self):
        return []

    def __iter__(self):
        columns = list(dict(object_mapper(self).columns).keys())
        columns.extend(self._extra_keys)
        return ModelIterator(self, iter(columns))

    def update(self, values):
        """Make the model object behave like a dict."""
        for k, v in six.iteritems(values):
            setattr(self, k, v)

    def iteritems(self):
        """Make the model object behave like a dict.

        Includes attributes from joins.
        """
        local = dict(self)
        joined = dict([(k, v) for k, v in six.iteritems(self.__dict__)
                      if not k[0] == '_'])
        local.update(joined)
        return six.iteritems(local)


class ModelIterator(ModelBase, six.Iterator):

    def __init__(self, model, columns):
        self.model = model
        self.i = columns

    def __iter__(self):
        return self

    # In Python 3, __next__() has replaced next().
    def __next__(self):
        n = six.advance_iterator(self.i)
        return n, getattr(self.model, n)


class TimestampMixin(object):
    created_at = Column(DateTime, default=lambda: datetime.datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.datetime.utcnow())


class SoftDeleteMixin(object):
    deleted_at = Column(DateTime)
    deleted = Column(Integer, default=0)

    def soft_delete(self, session):
        """Mark this object as deleted."""
        self.deleted = self.id
        self.deleted_at = datetime.datetime.utcnow()
        self.save(session=session)


class JsonEncodedType(TypeDecorator):
    """Abstract base type serialized as json-encoded string in db."""
    type = None
    impl = TEXT

    def process_bind_param(self, value, dialect):
        if value is None:
            # Save default value according to current type to keep the
            # interface the consistent.
            value = self.type()
        elif not isinstance(value, self.type):
            raise TypeError("%s supposes to store %s objects, but %s given"
                            % (self.__class__.__name__,
                               self.type.__name__,
                               type(value).__name__))
        serialized_value = json.dumps(value)
        return serialized_value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class JSONEncodedDict(JsonEncodedType):
    """Represents dict serialized as json-encoded string in db."""
    type = dict


class JSONEncodedList(JsonEncodedType):
    """Represents list serialized as json-encoded string in db."""
    type = list
