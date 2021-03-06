#
# -------------------------------------------------------------------------
#   Copyright (c) 2015-2017 AT&T Intellectual Property
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# -------------------------------------------------------------------------
#

import abc

from oslo_log import log
import six

from conductor.data.plugins import base

LOG = log.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class InventoryProviderBase(base.DataPlugin):
    """Base class for Inventory Provider plugins"""

    @abc.abstractmethod
    def name(self):
        """Return human-readable name."""
        pass

    @abc.abstractmethod
    def resolve_demands(self, demands):
        """Resolve demands into inventory candidate lists"""
        pass

    def invoke_method(self, arg):
        return None
