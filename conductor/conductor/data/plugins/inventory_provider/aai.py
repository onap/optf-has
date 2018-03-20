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

import re
import time
import uuid

from conductor.common import rest
from conductor.data.plugins.inventory_provider import base
from conductor.data.plugins.inventory_provider import hpa_utils
from conductor.i18n import _LE, _LI
from oslo_config import cfg
from oslo_log import log

LOG = log.getLogger(__name__)

CONF = cfg.CONF

AAI_OPTS = [
    cfg.IntOpt('cache_refresh_interval',
               default=1440,
               help='Interval with which to refresh the local cache, '
                    'in minutes.'),
    cfg.IntOpt('complex_cache_refresh_interval',
               default=1440,
               help='Interval with which to refresh the local complex cache, '
                    'in minutes.'),
    cfg.StrOpt('table_prefix',
               default='aai',
               help='Data Store table prefix.'),
    cfg.StrOpt('server_url',
               default='https://controller:8443/aai',
               help='Base URL for A&AI, up to and not including '
                    'the version, and without a trailing slash.'),
    cfg.StrOpt('aai_rest_timeout',
               default=30,
               help='Timeout for A&AI Rest Call'),
    cfg.StrOpt('aai_retries',
               default=3,
               help='Number of retry for A&AI Rest Call'),
    cfg.StrOpt('server_url_version',
               default='v10',
               help='The version of A&AI in v# format.'),
    cfg.StrOpt('certificate_file',
               default='certificate.pem',
               help='SSL/TLS certificate file in pem format. '
                    'This certificate must be registered with the A&AI '
                    'endpoint.'),
    cfg.StrOpt('certificate_key_file',
               default='certificate_key.pem',
               help='Private Certificate Key file in pem format.'),
    cfg.StrOpt('certificate_authority_bundle_file',
               default='certificate_authority_bundle.pem',
               help='Certificate Authority Bundle file in pem format. '
                    'Must contain the appropriate trust chain for the '
                    'Certificate file.'),
]

CONF.register_opts(AAI_OPTS, group='aai')


class AAI(base.InventoryProviderBase):
    """Active and Available Inventory Provider"""

    def __init__(self):
        """Initializer"""

        # FIXME(jdandrea): Pass this in to init.
        self.conf = CONF

        self.base = self.conf.aai.server_url.rstrip('/')
        self.version = self.conf.aai.server_url_version.rstrip('/')
        self.cert = self.conf.aai.certificate_file
        self.key = self.conf.aai.certificate_key_file
        self.verify = self.conf.aai.certificate_authority_bundle_file
        self.cache_refresh_interval = self.conf.aai.cache_refresh_interval
        self.last_refresh_time = None
        self.complex_cache_refresh_interval = \
            self.conf.aai.complex_cache_refresh_interval
        self.complex_last_refresh_time = None
        self.timeout = self.conf.aai.aai_rest_timeout
        self.retries = self.conf.aai.aai_retries

        # Cache is initially empty
        self._aai_cache = {}
        self._aai_complex_cache = {}

    def initialize(self):

        """Perform any late initialization."""
        # Initialize the Python requests
        self._init_python_request()

        # Refresh the cache once for now
        self._refresh_cache()

        # TODO(jdandrea): Make this periodic, and without a True condition!
        # executor = futurist.ThreadPoolExecutor()
        # while True:
        #     fut = executor.submit(self.refresh_cache)
        #     fut.result()
        #
        #     # Now wait for the next time.
        #     # FIXME(jdandrea): Put inside refresh_cache()?
        #     refresh_interval = self.conf.aai.cache_refresh_interval
        #     time.sleep(refresh_interval)
        # executor.shutdown()

    def name(self):
        """Return human-readable name."""
        return "A&AI"

    def _get_version_from_string(self, string):
        """Extract version number from string"""
        return re.sub("[^0-9.]", "", string)

    def _aai_versioned_path(self, path):
        """Return a URL path with the A&AI version prepended"""
        return '/{}/{}'.format(self.version, path.lstrip('/'))

    def _request(self, method='get', path='/', data=None,
                 context=None, value=None):
        """Performs HTTP request."""
        headers = {
            'X-FromAppId': 'CONDUCTOR',
            'X-TransactionId': str(uuid.uuid4()),
        }
        kwargs = {
            "method": method,
            "path": path,
            "headers": headers,
            "data": data,
        }

        # TODO(jdandrea): Move timing/response logging into the rest helper?
        start_time = time.time()
        response = self.rest.request(**kwargs)
        elapsed = time.time() - start_time
        LOG.debug("Total time for A&AI request "
                  "({0:}: {1:}): {2:.3f} sec".format(context, value, elapsed))

        if response is None:
            LOG.error(_LE("No response from A&AI ({}: {})").
                      format(context, value))
        elif response.status_code != 200:
            LOG.error(_LE("A&AI request ({}: {}) returned HTTP "
                          "status {} {}, link: {}{}").
                      format(context, value,
                             response.status_code, response.reason,
                             self.base, path))
        return response

    def _init_python_request(self):

        kwargs = {
            "server_url": self.base,
            "retries": self.retries,
            "cert_file": self.cert,
            "cert_key_file": self.key,
            "ca_bundle_file": self.verify,
            "log_debug": self.conf.debug,
            "read_timeout": self.timeout,
        }
        self.rest = rest.REST(**kwargs)


    def _refresh_cache(self):
        """Refresh the A&AI cache."""
        if not self.last_refresh_time or \
            (time.time() - self.last_refresh_time) > \
                self.cache_refresh_interval * 60:
            # TODO(jdandrea): This is presently brute force.
            # It does not persist to Music. A general purpose ORM caching
            # object likely needs to be made, with a key (hopefully we
            # can use one that is not just a UUID), a value, and a
            # timestamp. The other alternative is to not use the ORM
            # layer and call the API directly, but that is
            # also trading one set of todos for another ...

            # Get all A&AI sites
            LOG.info(_LI("**** Refreshing A&AI cache *****"))
            path = self._aai_versioned_path(
                '/cloud-infrastructure/cloud-regions/?depth=0')
            response = self._request(
                path=path, context="cloud regions", value="all")
            if response is None:
                return
            regions = {}
            if response.status_code == 200:
                body = response.json()
                regions = body.get('cloud-region', {})
            if not regions:
                # Nothing to update the cache with
                LOG.error(_LE("A&AI returned no regions, link: {}{}").
                          format(self.base, path))
                return
            cache = {
                'cloud_region': {},
                'service': {},
            }
            for region in regions:
                cloud_region_id = region.get('cloud-region-id')

                LOG.debug("Working on region '{}' ".format(cloud_region_id))

                cloud_region_version = region.get('cloud-region-version')
                cloud_owner = region.get('cloud-owner')
                complex_name = region.get('complex-name')
                cloud_type = region.get('cloud-type')
                cloud_zone = region.get('cloud-zone')

                physical_location_list = self._get_aai_rel_link_data(data = region, related_to = 'complex', search_key = 'complex.physical-location-id')
                if len(physical_location_list) > 0:
                    physical_location_id = physical_location_list[0].get('d_value')

                if not (cloud_region_version and
                        cloud_region_id and complex_name):
                    continue
                rel_link_data_list = \
                    self._get_aai_rel_link_data(
                        data=region,
                        related_to='complex',
                        search_key='complex.physical-location-id')
                if len(rel_link_data_list) > 1:
                    LOG.error(_LE("Region {} has more than one complex").
                              format(cloud_region_id))
                    LOG.debug("Region {}: {}".format(cloud_region_id, region))
                    continue
                rel_link_data = rel_link_data_list[0]
                complex_id = rel_link_data.get("d_value")
                complex_link = rel_link_data.get("link")
                if complex_id and complex_link:
                    complex_info = self._get_complex(
                        complex_link=complex_link,
                        complex_id=complex_id)
                else:  # no complex information
                    LOG.error(_LE("Region {} does not reference a complex").
                              format(cloud_region_id))
                    continue
                if not complex_info:
                    LOG.error(_LE("Region {}, complex {} info not found, "
                                  "link {}").format(cloud_region_id,
                                                    complex_id, complex_link))
                    continue

                latitude = complex_info.get('latitude')
                longitude = complex_info.get('longitude')
                city = complex_info.get('city')
                state = complex_info.get('state')
                region = complex_info.get('region')
                country = complex_info.get('country')

                if not (latitude and longitude and city and country):
                    keys = ('latitude', 'longitude', 'city', 'country')
                    missing_keys = \
                        list(set(keys).difference(complex_info.keys()))
                    LOG.error(_LE("Complex {} is missing {}, link: {}").
                              format(complex_id, missing_keys, complex_link))
                    LOG.debug("Complex {}: {}".
                              format(complex_id, complex_info))
                    continue
                cache['cloud_region'][cloud_region_id] = {
                    'cloud_region_version': cloud_region_version,
                    'cloud_owner': cloud_owner,
                    'cloud_type': cloud_type,
                    'cloud_zone': cloud_zone,
                    'complex_name': complex_name,
                    'physical_location_id': physical_location_id,
                    'complex': {
                        'complex_id': complex_id,
                        'complex_name': complex_name,
                        'latitude': latitude,
                        'longitude': longitude,
                        'city': city,
                        'state': state,
                        'region': region,
                        'country': country,
                    }
                }
                LOG.debug("Candidate with cloud_region_id '{}' selected "
                          "as a potential candidate - ".format(cloud_region_id))
            LOG.debug("Done with region '{}' ".format(cloud_region_id))
            self._aai_cache = cache
            self.last_refresh_time = time.time()
            LOG.info(_LI("**** A&AI cache refresh complete *****"))

    @staticmethod
    def _get_aai_rel_link(data, related_to):
        """Given an A&AI data structure, return the related-to link"""
        rel_dict = data.get('relationship-list')
        if rel_dict:
            for key, rel_list in rel_dict.items():
                for rel in rel_list:
                    if related_to == rel.get('related-to'):
                        return rel.get('related-link')

    @staticmethod
    def _get_aai_rel_link_data(data, related_to, search_key=None,
                               match_dict=None):
        # some strings that we will encounter frequently
        rel_lst = "relationship-list"
        rkey = "relationship-key"
        rval = "relationship-value"
        rdata = "relationship-data"
        response = list()
        if match_dict:
            m_key = match_dict.get('key')
            m_value = match_dict.get('value')
        else:
            m_key = None
            m_value = None
        rel_dict = data.get(rel_lst)
        if rel_dict:  # check if data has relationship lists
            for key, rel_list in rel_dict.items():
                for rel in rel_list:
                    if rel.get("related-to") == related_to:
                        dval = None
                        matched = False
                        link = rel.get("related-link")
                        r_data = rel.get(rdata, [])
                        if search_key:
                            for rd in r_data:
                                if rd.get(rkey) == search_key:
                                    dval = rd.get(rval)
                                    if not match_dict:  # return first match
                                        response.append(
                                            {"link": link, "d_value": dval}
                                        )
                                        break  # go to next relation
                                if rd.get(rkey) == m_key \
                                        and rd.get(rval) == m_value:
                                    matched = True
                            if match_dict and matched:  # if matching required
                                response.append(
                                    {"link": link, "d_value": dval}
                                )
                                # matched, return search value corresponding
                                # to the matched r_data group
                        else:  # no search key; just return the link
                            response.append(
                                {"link": link, "d_value": dval}
                            )
        if len(response) == 0:
            response.append(
                {"link": None, "d_value": None}
            )
        return response

    def _get_complex(self, complex_link, complex_id=None):
        if not self.complex_last_refresh_time or \
           (time.time() - self.complex_last_refresh_time) > \
           self.complex_cache_refresh_interval * 60:
            self._aai_complex_cache.clear()
        if complex_id and complex_id in self._aai_complex_cache:
            return self._aai_complex_cache[complex_id]
        else:
            path = self._aai_versioned_path(
                self._get_aai_path_from_link(complex_link))
            response = self._request(
                path=path, context="complex", value=complex_id)
            if response is None:
                return
            if response.status_code == 200:
                complex_info = response.json()
                if 'complex' in complex_info:
                    complex_info = complex_info.get('complex')
                latitude = complex_info.get('latitude')
                longitude = complex_info.get('longitude')
                city = complex_info.get('city')
                # removed the state check for MoW orders - Countries in Europe do not always enter states
                # state = complex_info.get('state')
                # region = complex_info.get('region')
                country = complex_info.get('country')

                # removed the state check for MoW orders - Countries in Europe do not always enter states
                if not (latitude and longitude and city and country):
                    keys = ('latitude', 'longitude', 'city', 'country')
                    missing_keys = \
                        list(set(keys).difference(complex_info.keys()))
                    LOG.error(_LE("Complex {} is missing {}, link: {}").
                              format(complex_id, missing_keys, complex_link))
                    LOG.debug("Complex {}: {}".
                              format(complex_id, complex_info))
                    return

                if complex_id:  # cache only if complex_id is given
                    self._aai_complex_cache[complex_id] = response.json()
                    self.complex_last_refresh_time = time.time()

                return complex_info

    def _get_regions(self):
        self._refresh_cache()
        regions = self._aai_cache.get('cloud_region', {})
        return regions

    def _get_aai_path_from_link(self, link):
        path = link.split(self.version, 1)
        if not path or len(path) <= 1:
            # TODO(shankar): Treat this as a critical error?
            LOG.error(_LE("A&AI version {} not found in link {}").
                      format(self.version, link))
        else:
            return "{}".format(path[1])

    def check_candidate_role(self, host_id=None):

        vnf_name_uri = '/network/generic-vnfs/?vnf-name=' + host_id + '&depth=0'
        path = self._aai_versioned_path(vnf_name_uri)

        response = self._request('get', path=path, data=None,
                                 context="vnf name")

        if response is None or not response.ok:
            return None
        body = response.json()

        generic_vnf = body.get("generic-vnf", [])

        for vnf in generic_vnf:
            related_to = "service-instance"
            search_key = "customer.global-customer-id"
            match_key = "customer.global-customer-id"
            rl_data_list = self._get_aai_rel_link_data(
                data=vnf,
                related_to=related_to,
                search_key=search_key,
            )

            if len(rl_data_list) != 1:
                return None

            rl_data = rl_data_list[0]
            candidate_role_link = rl_data.get("link")

            if not candidate_role_link:
                LOG.error(_LE("Unable to get candidate role link for host id {} ").format(host_id))
                return None

            candidate_role_path = self._get_aai_path_from_link(candidate_role_link) + '/allotted-resources?depth=all'
            path = self._aai_versioned_path(candidate_role_path)

            response = self._request('get', path=path, data=None,
                                     context="candidate role")

            if response is None or not response.ok:
                return None
            body = response.json()

            response_items = body.get('allotted-resource')
            if len(response_items) > 0:
                role = response_items[0].get('role')
            return role

    def check_network_roles(self, network_role_id=None):
        # the network role query from A&AI is not using
        # the version number in the query
        network_role_uri = \
            '/network/l3-networks?network-role=' + network_role_id
        path = self._aai_versioned_path(network_role_uri)

        # This UUID is reserved by A&AI for a Conductor-specific named query.
        named_query_uid = "96e54642-c0e1-4aa2-af53-e37c623b8d01"

        data = {
            "query-parameters": {
                "named-query": {
                    "named-query-uuid": named_query_uid
                }
            },
            "instance-filters": {
                "instance-filter": [
                    {
                        "l3-network": {
                            "network-role": network_role_id
                        }
                    }
                ]
            }
        }
        region_ids = set()
        response = self._request('get', path=path, data=data,
                                 context="role", value=network_role_id)
        if response is None:
            return None
        body = response.json()

        response_items = body.get('l3-network', [])

        for item in response_items:
            cloud_region_instances = self._get_aai_rel_link_data(
                data=item,
                related_to='cloud-region',
                search_key='cloud-region.cloud-region-id'
            )

            if len(cloud_region_instances) > 0:
                for r_instance in cloud_region_instances:
                    region_id = r_instance.get('d_value')
                    if region_id is not None:
                        region_ids.add(region_id)

        # return region ids that fit the role
        return region_ids

    def resolve_host_location(self, host_name):
        path = self._aai_versioned_path('/query?format=id')
        data = {"start": ["network/pnfs/pnf/" + host_name,
                "cloud-infrastructure/pservers/pserver/" + host_name],
                "query": "query/ucpe-instance"
                }
        response = self._request('put', path=path, data=data,
                                 context="host name", value=host_name)
        if response is None or response.status_code != 200:
            return None
        body = response.json()
        results = body.get('results', [])
        complex_link = None
        for result in results:
            if "resource-type" in result and \
                    "resource-link" in result and \
                    result["resource-type"] == "complex":
                complex_link = result["resource-link"]
        if not complex_link:
            LOG.error(_LE("Unable to get a complex link for hostname {} "
                          " in response {}").format(host_name, response))
            return None
        complex_info = self._get_complex(
            complex_link=complex_link,
            complex_id=None
        )
        if complex_info:
            lat = complex_info.get('latitude')
            lon = complex_info.get('longitude')
            country = complex_info.get('country')
            if lat and lon:
                location = {"latitude": lat, "longitude": lon}
                location["country"] = country if country else None
                return location
            else:
                LOG.error(_LE("Unable to get a latitude and longitude "
                              "information for hostname {} from complex "
                              " link {}").format(host_name, complex_link))
                return None
        else:
            LOG.error(_LE("Unable to get a complex information for "
                          " hostname {} from complex "
                          " link {}").format(host_name, complex_link))
            return None

    def resolve_clli_location(self, clli_name):
        clli_uri = '/cloud-infrastructure/complexes/complex/' + clli_name
        path = self._aai_versioned_path(clli_uri)

        response = self._request('get', path=path, data=None,
                                 context="clli name", value=clli_name)
        if response is None or response.status_code != 200:
            return None

        body = response.json()

        if body:
            lat = body.get('latitude')
            lon = body.get('longitude')
            country = body.get('country')
            if lat and lon:
                location = {"latitude": lat, "longitude": lon}
                location["country"] = country if country else None
                return location
            else:
                LOG.error(_LE("Unable to get a latitude and longitude "
                              "information for CLLI code {} from complex").
                          format(clli_name))
                return None
        else:
            LOG.error(_LE("Unable to get a complex information for "
                          " clli {} from complex "
                          " link {}").format(clli_name, clli_uri))
            return None

    def get_inventory_group_pairs(self, service_description):
        pairs = list()
        path = self._aai_versioned_path(
            '/network/instance-groups/?description={}&depth=0'.format(
                service_description))
        response = self._request(path=path, context="inventory group",
                                 value=service_description)
        if response is None or response.status_code != 200:
            return
        body = response.json()
        if "instance-group" not in body:
            LOG.error(_LE("Unable to get instance groups from inventory "
                          " in response {}").format(response))
            return
        for instance_groups in body["instance-group"]:
            s_instances = self._get_aai_rel_link_data(
                data=instance_groups,
                related_to='service-instance',
                search_key='service-instance.service-instance-id'
            )
            if s_instances and len(s_instances) == 2:
                pair = list()
                for s_inst in s_instances:
                    pair.append(s_inst.get('d_value'))
                pairs.append(pair)
            else:
                LOG.error(_LE("Number of instance pairs not found to "
                              "be two: {}").format(instance_groups))
        return pairs

    def _log_multiple_item_error(self, name, service_type,
                                 related_to, search_key='',
                                 context=None, value=None):
        """Helper method to log multiple-item errors

        Used by resolve_demands
        """
        LOG.error(_LE("Demand {}, role {} has more than one {} ({})").
                  format(name, service_type, related_to, search_key))
        if context and value:
            LOG.debug("{} details: {}".format(context, value))

    def check_sriov_automation(self, aic_version, demand_name, candidate_name):

        """Check if specific candidate has SRIOV automation available or not

        Used by resolve_demands
        """

        if aic_version:
            LOG.debug(_LI("Demand {}, candidate {} has an AIC version "
                          "number {}").format(demand_name, candidate_name,
                                              aic_version)
                      )
            if aic_version == "3.6":
                return True
        return False

    def match_candidate_attribute(self, candidate, attribute_name,
                                  restricted_value, demand_name,
                                  inventory_type):
        """Check if specific candidate attribute matches the restricted value

        Used by resolve_demands
        """
        if restricted_value and \
           restricted_value is not '' and \
           candidate[attribute_name] != restricted_value:
            LOG.info(_LI("Demand: {} "
                         "Discarded {} candidate as "
                         "it doesn't match the "
                         "{} attribute "
                         "{} ").format(demand_name,
                                       inventory_type,
                                       attribute_name,
                                       restricted_value
                                       )
                     )
            return True
        return False

    def match_vserver_attribute(self, vserver_list):

        value = None
        for i in range(0, len(vserver_list)):
            if value and \
               value != vserver_list[i].get('d_value'):
                return False
            value = vserver_list[i].get('d_value')
        return True

    def match_inventory_attributes(self, template_attributes,
                                    inventory_attributes, candidate_id):

        for attribute_key, attribute_values in template_attributes.items():

            if attribute_key and (attribute_key == 'service-type' or
                                          attribute_key == 'equipment-role' or attribute_key == 'model-invariant-id' or
                                          attribute_key == 'model-version-id'):
                continue

            match_type = 'any'
            if type(attribute_values) is dict:
                if 'any' in attribute_values:
                    attribute_values = attribute_values['any']
                elif 'not' in attribute_values:
                    match_type = 'not'
                    attribute_values = attribute_values['not']

            if match_type == 'any':
                if attribute_key not in inventory_attributes or \
                   (len(attribute_values) > 0 and
                   inventory_attributes[attribute_key] not in attribute_values):
                    return False
            elif match_type == 'not':
                # drop the candidate when
                # 1). field exists in AAI and 2). value is not null or empty 3). value is one of those in the 'not' list
                # Remember, this means if the property is not returned at all from AAI, that still can be a candidate.
                if attribute_key in inventory_attributes and \
                    inventory_attributes[attribute_key] and \
                    inventory_attributes[attribute_key] in attribute_values:
                     return False

        return True

    def first_level_service_call(self, path, name, service_type):

        response = self._request(
            path=path, context="demand, GENERIC-VNF role",
            value="{}, {}".format(name, service_type))
        if response is None or response.status_code != 200:
            return list()  # move ahead with next requirement
        body = response.json()
        return body.get("generic-vnf", [])

    def assign_candidate_existing_placement(self, candidate, existing_placement):

        """Assign existing_placement and cost parameters to candidate

        Used by resolve_demands
        """
        candidate['existing_placement'] = 'false'
        if existing_placement:
            if existing_placement.get('candidate_id') == candidate['candidate_id']:
                candidate['cost'] = self.conf.data.existing_placement_cost
                candidate['existing_placement'] = 'true'

    def resolve_demands(self, demands):
        """Resolve demands into inventory candidate lists"""

        resolved_demands = {}
        for name, requirements in demands.items():
            resolved_demands[name] = []
            for requirement in requirements:
                inventory_type = requirement.get('inventory_type').lower()
                attributes = requirement.get('attributes')
                #TODO: may need to support multiple service_type and customer_id in the futrue

                #TODO: make it consistent for dash and underscore
                if attributes:
                    service_type = attributes.get('service-type')
                    equipment_role = attributes.get('equipment-role')
                    if equipment_role:
                        service_type = equipment_role
                    customer_id = attributes.get('customer-id')
                    global_customer_id = attributes.get('global-customer-id')
                    if global_customer_id:
                        customer_id = global_customer_id
                    model_invariant_id = attributes.get('model-invariant-id')
                    model_version_id = attributes.get('model-version-id')
                else:
                    service_type = requirement.get('service_type')
                    equipment_role = service_type
                    customer_id = requirement.get('customer_id')
                # region_id is OPTIONAL. This will restrict the initial
                # candidate set to come from the given region id
                restricted_region_id = requirement.get('region')
                restricted_complex_id = requirement.get('complex')

                # get required candidates from the demand
                required_candidates = requirement.get("required_candidates")

                # get existing_placement from the demand
                existing_placement = requirement.get("existing_placement")

                if required_candidates:
                    resolved_demands['required_candidates'] = \
                        required_candidates

                # get excluded candidate from the demand
                excluded_candidates = requirement.get("excluded_candidates")

                # service_resource_id is OPTIONAL and is
                # transparent to Conductor
                service_resource_id = requirement.get('service_resource_id') \
                    if requirement.get('service_resource_id') else ''
                # 21014aa2-526b-11e6-beb8-9e71128cae77 is a special
                # customer_id that is supposed to fetch all VVIG instances.
                # This should be a config parameter.
                # if service_type in ['VVIG', 'HNGATEWAY', 'HNPORTAL']:
                #     customer_id = '21014aa2-526b-11e6-beb8-9e71128cae77'

                # add all the candidates of cloud type
                if inventory_type == 'cloud':
                    # load region candidates from cache
                    regions = self._get_regions()

                    if not regions or len(regions) < 1:
                        LOG.debug("Region information is not "
                                  "available in cache")
                    for region_id, region in regions.items():
                        # Pick only candidates from the restricted_region

                        candidate = dict()
                        candidate['inventory_provider'] = 'aai'
                        candidate['service_resource_id'] = service_resource_id
                        candidate['inventory_type'] = 'cloud'
                        candidate['candidate_id'] = region_id
                        candidate['location_id'] = region_id
                        candidate['location_type'] = 'att_aic'
                        candidate['cost'] = self.conf.data.cloud_candidate_cost
                        candidate['cloud_region_version'] = \
                            self._get_version_from_string(
                                region['cloud_region_version'])
                        candidate['cloud_owner'] = \
                            region['cloud_owner']

                        # Added vim-id for short-term workaround
                        candidate['vim-id'] = \
                            region['cloud_owner'] + '_' + region_id

                        candidate['physical_location_id'] = \
                            region['complex']['complex_id']
                        candidate['complex_name'] = \
                            region['complex']['complex_name']
                        candidate['latitude'] = \
                            region['complex']['latitude']
                        candidate['longitude'] = \
                            region['complex']['longitude']
                        candidate['city'] = \
                            region['complex']['city']
                        candidate['state'] = \
                            region['complex']['state']
                        candidate['region'] = \
                            region['complex']['region']
                        candidate['country'] = \
                            region['complex']['country']

                        if self.check_sriov_automation(
                                candidate['cloud_region_version'], name,
                                candidate['candidate_id']):
                            candidate['sriov_automation'] = 'true'
                        else:
                            candidate['sriov_automation'] = 'false'

                        cloud_region_attr = dict()
                        cloud_region_attr['cloud-owner'] = region['cloud_owner']
                        cloud_region_attr['cloud-region-version'] = region['cloud_region_version']
                        cloud_region_attr['cloud-type'] = region['cloud_type']
                        cloud_region_attr['cloud-zone'] = region['cloud_zone']
                        cloud_region_attr['complex-name'] = region['complex_name']
                        cloud_region_attr['physical-location-id'] = region['physical_location_id']

                        if attributes and (not self.match_inventory_attributes(attributes, cloud_region_attr, candidate['candidate_id'])):
                            continue

                        if self.match_candidate_attribute(
                                candidate, "candidate_id",
                                restricted_region_id, name,
                                inventory_type) or \
                           self.match_candidate_attribute(
                               candidate, "physical_location_id",
                               restricted_complex_id, name,
                               inventory_type):
                            continue

                        self.assign_candidate_existing_placement(candidate, existing_placement)

                        # Pick only candidates not in the excluded list
                        # if excluded candidate list is provided
                        if excluded_candidates:
                            has_excluded_candidate = False
                            for excluded_candidate in excluded_candidates:
                                if excluded_candidate \
                                   and excluded_candidate.get('inventory_type') == \
                                   candidate.get('inventory_type') \
                                   and excluded_candidate.get('candidate_id') == \
                                   candidate.get('candidate_id'):
                                    has_excluded_candidate = True
                                    break

                            if has_excluded_candidate:
                                continue

                        # Pick only candidates in the required list
                        # if required candidate list is provided
                        if required_candidates:
                            has_required_candidate = False
                            for required_candidate in required_candidates:
                                if required_candidate \
                                   and required_candidate.get('inventory_type') \
                                   == candidate.get('inventory_type') \
                                   and required_candidate.get('candidate_id') \
                                   == candidate.get('candidate_id'):
                                    has_required_candidate = True
                                    break

                            if not has_required_candidate:
                                continue

                        # add candidate to demand candidates
                        resolved_demands[name].append(candidate)

                elif inventory_type == 'service' \
                        and customer_id:

                    # First level query to get the list of generic vnfs
                    #TODO: extract the common part from the two calls
                    vnf_by_model_invariant = list()
                    if attributes and model_invariant_id:
                        if model_version_id:
                            path = self._aai_versioned_path(
                                '/network/generic-vnfs/'
                                '?model-invariant-id={}&model-version-id={}&depth=0'.format(model_invariant_id, model_version_id))
                        else:
                            path = self._aai_versioned_path(
                                '/network/generic-vnfs/'
                                '?model-invariant-id={}&depth=0'.format(model_invariant_id))
                        vnf_by_model_invariant = self.first_level_service_call(path, name, service_type)

                    vnf_by_service_type = list()
                    if service_type or equipment_role:
                        path = self._aai_versioned_path(
                            '/network/generic-vnfs/'
                            '?prov-status=PROV&equipment-role={}&depth=0'.format(service_type))
                        vnf_by_service_type = self.first_level_service_call(path, name, service_type)

                    generic_vnf = vnf_by_model_invariant + vnf_by_service_type
                    vnf_dict = dict()

                    for vnf in generic_vnf:
                        # if this vnf already appears, skip it
                        vnf_id = vnf.get('vnf-id')
                        if vnf_id in vnf_dict:
                            continue

                        # add vnf (with vnf_id as key) to the dictionary
                        vnf_dict[vnf_id] = vnf

                        # create a default candidate
                        candidate = dict()
                        candidate['inventory_provider'] = 'aai'
                        candidate['service_resource_id'] = service_resource_id
                        candidate['inventory_type'] = 'service'
                        candidate['candidate_id'] = ''
                        candidate['location_id'] = ''
                        candidate['location_type'] = 'att_aic'
                        candidate['host_id'] = ''
                        candidate['cost'] = self.conf.data.service_candidate_cost
                        candidate['cloud_owner'] = ''
                        candidate['cloud_region_version'] = ''

                        # start populating the candidate
                        candidate['host_id'] = vnf.get("vnf-name")

                        related_to = "vserver"
                        search_key = "cloud-region.cloud-owner"
                        rl_data_list = self._get_aai_rel_link_data(
                            data=vnf, related_to=related_to,
                            search_key=search_key)

                        if len(rl_data_list) > 1:
                            if not self.match_vserver_attribute(rl_data_list):
                                self._log_multiple_item_error(
                                    name, service_type, related_to, search_key,
                                    "GENERIC-VNF", vnf)
                                continue
                        rl_data = rl_data_list[0]

                        vs_link_list = list()
                        for i in range(0, len(rl_data_list)):
                            vs_link_list.append(rl_data_list[i].get('link'))

                        candidate['cloud_owner'] = rl_data.get('d_value')

                        search_key = "cloud-region.cloud-region-id"

                        rl_data_list = self._get_aai_rel_link_data(
                            data=vnf,
                            related_to=related_to,
                            search_key=search_key
                        )
                        if len(rl_data_list) > 1:
                            if not self.match_vserver_attribute(rl_data_list):
                                self._log_multiple_item_error(
                                    name, service_type, related_to, search_key,
                                    "GENERIC-VNF", vnf)
                                continue
                        rl_data = rl_data_list[0]
                        cloud_region_id = rl_data.get('d_value')
                        candidate['location_id'] = cloud_region_id

                        # Added vim-id for short-term workaround
                        candidate['vim-id'] = \
                            candidate['cloud_owner'] + '_' + cloud_region_id

                        # get AIC version for service candidate
                        if cloud_region_id:
                            cloud_region_uri = '/cloud-infrastructure/cloud-regions' \
                                               '/?cloud-region-id=' \
                                               + cloud_region_id
                            path = self._aai_versioned_path(cloud_region_uri)

                            response = self._request('get',
                                                     path=path,
                                                     data=None)
                            if response is None or response.status_code != 200:
                                return None

                            body = response.json()
                            regions = body.get('cloud-region', [])

                            for region in regions:
                                if "cloud-region-version" in region:
                                    candidate['cloud_region_version'] = \
                                        self._get_version_from_string(
                                            region["cloud-region-version"])

                        if self.check_sriov_automation(
                                candidate['cloud_region_version'], name,
                                candidate['host_id']):
                            candidate['sriov_automation'] = 'true'
                        else:
                            candidate['sriov_automation'] = 'false'

                        related_to = "service-instance"
                        search_key = "customer.global-customer-id"
                        match_key = "customer.global-customer-id"
                        rl_data_list = self._get_aai_rel_link_data(
                            data=vnf,
                            related_to=related_to,
                            search_key=search_key,
                            match_dict={'key': match_key,
                                        'value': customer_id}
                        )
                        if len(rl_data_list) > 1:
                            if not self.match_vserver_attribute(rl_data_list):
                                self._log_multiple_item_error(
                                    name, service_type, related_to, search_key,
                                    "GENERIC-VNF", vnf)
                                continue
                        rl_data = rl_data_list[0]
                        vs_cust_id = rl_data.get('d_value')

                        search_key = "service-instance.service-instance-id"
                        match_key = "customer.global-customer-id"
                        rl_data_list = self._get_aai_rel_link_data(
                            data=vnf,
                            related_to=related_to,
                            search_key=search_key,
                            match_dict={'key': match_key,
                                        'value': customer_id}
                        )
                        if len(rl_data_list) > 1:
                            if not self.match_vserver_attribute(rl_data_list):
                                self._log_multiple_item_error(
                                    name, service_type, related_to, search_key,
                                    "GENERIC-VNF", vnf)
                                continue
                        rl_data = rl_data_list[0]
                        vs_service_instance_id = rl_data.get('d_value')

                        if vs_cust_id and vs_cust_id == customer_id:
                            candidate['candidate_id'] = \
                                vs_service_instance_id
                        else:  # vserver is for a different customer
                            continue

                        # Second level query to get the pserver from vserver
                        complex_list = list()

                        for vs_link in vs_link_list:

                            if not vs_link:
                                LOG.error(_LE("{} VSERVER link information not "
                                              "available from A&AI").format(name))
                                LOG.debug("Related link data: {}".format(rl_data))
                                continue  # move ahead with the next vnf

                            vs_path = self._get_aai_path_from_link(vs_link)
                            if not vs_path:
                                LOG.error(_LE("{} VSERVER path information not "
                                              "available from A&AI - {}").
                                          format(name, vs_path))
                                continue  # move ahead with the next vnf
                            path = self._aai_versioned_path(vs_path)
                            response = self._request(
                                path=path, context="demand, VSERVER",
                                value="{}, {}".format(name, vs_path))
                            if response is None or response.status_code != 200:
                                continue
                            body = response.json()

                            related_to = "pserver"
                            rl_data_list = self._get_aai_rel_link_data(
                                data=body,
                                related_to=related_to,
                                search_key=None
                            )
                            if len(rl_data_list) > 1:
                                self._log_multiple_item_error(
                                    name, service_type, related_to, "item",
                                    "VSERVER", body)
                                continue
                            rl_data = rl_data_list[0]
                            ps_link = rl_data.get('link')

                            # Third level query to get cloud region from pserver
                            if not ps_link:
                                LOG.error(_LE("{} pserver related link "
                                              "not found in A&AI: {}").
                                          format(name, rl_data))
                                continue
                            ps_path = self._get_aai_path_from_link(ps_link)
                            if not ps_path:
                                LOG.error(_LE("{} pserver path information "
                                              "not found in A&AI: {}").
                                          format(name, ps_link))
                                continue  # move ahead with the next vnf
                            path = self._aai_versioned_path(ps_path)
                            response = self._request(
                                path=path, context="PSERVER", value=ps_path)
                            if response is None or response.status_code != 200:
                                continue
                            body = response.json()

                            related_to = "complex"
                            search_key = "complex.physical-location-id"
                            rl_data_list = self._get_aai_rel_link_data(
                                data=body,
                                related_to=related_to,
                                search_key=search_key
                            )
                            if len(rl_data_list) > 1:
                                if not self.match_vserver_attribute(rl_data_list):
                                    self._log_multiple_item_error(
                                        name, service_type, related_to, search_key,
                                        "PSERVER", body)
                                    continue
                            rl_data = rl_data_list[0]
                            complex_list.append(rl_data)

                        if not complex_list or \
                            len(complex_list) < 1:
                            LOG.error("Complex information not "
                                          "available from A&AI")
                            continue

                        if len(complex_list) > 1:
                            if not self.match_vserver_attribute(complex_list):
                                self._log_multiple_item_error(
                                    name, service_type, related_to, search_key,
                                    "GENERIC-VNF", vnf)
                                continue

                        rl_data = complex_list[0]
                        complex_link = rl_data.get('link')
                        complex_id = rl_data.get('d_value')

                        # Final query for the complex information
                        if not (complex_link and complex_id):
                            LOG.debug("{} complex information not "
                                      "available from A&AI - {}".
                                      format(name, complex_link))
                            continue  # move ahead with the next vnf
                        else:
                            complex_info = self._get_complex(
                                complex_link=complex_link,
                                complex_id=complex_id
                            )
                            if not complex_info:
                                LOG.debug("{} complex information not "
                                          "available from A&AI - {}".
                                          format(name, complex_link))
                                continue  # move ahead with the next vnf
                            candidate['physical_location_id'] = \
                                complex_id
                            candidate['complex_name'] = \
                                complex_info.get('complex-name')
                            candidate['latitude'] = \
                                complex_info.get('latitude')
                            candidate['longitude'] = \
                                complex_info.get('longitude')
                            candidate['state'] = \
                                complex_info.get('state')
                            candidate['country'] = \
                                complex_info.get('country')
                            candidate['city'] = \
                                complex_info.get('city')
                            candidate['region'] = \
                                complex_info.get('region')

                        # add specifal parameters for comparsion
                        vnf['global-customer-id'] = customer_id
                        vnf['customer-id'] = customer_id
                        vnf['cloud-region-id'] = cloud_region_id
                        vnf['physical-location-id'] = complex_id

                        if attributes and not self.match_inventory_attributes(attributes, vnf, candidate['candidate_id']):
                            continue
                        self.assign_candidate_existing_placement(candidate, existing_placement)

                        # Pick only candidates not in the excluded list
                        # if excluded candidate list is provided
                        if excluded_candidates:
                            has_excluded_candidate = False
                            for excluded_candidate in excluded_candidates:
                                if excluded_candidate \
                                        and excluded_candidate.get('inventory_type') == \
                                        candidate.get('inventory_type') \
                                        and excluded_candidate.get('candidate_id') == \
                                        candidate.get('candidate_id'):
                                    has_excluded_candidate = True
                                    break

                            if has_excluded_candidate:
                                continue

                        # Pick only candidates in the required list
                        # if required candidate list is provided
                        if required_candidates:
                            has_required_candidate = False
                            for required_candidate in required_candidates:
                                if required_candidate \
                                        and required_candidate.get('inventory_type') \
                                        == candidate.get('inventory_type') \
                                        and required_candidate.get('candidate_id') \
                                        == candidate.get('candidate_id'):
                                    has_required_candidate = True
                                    break

                            if not has_required_candidate:
                                continue

                        # add the candidate to the demand
                        # Pick only candidates from the restricted_region
                        # or restricted_complex
                        if self.match_candidate_attribute(
                                candidate,
                                "location_id",
                                restricted_region_id,
                                name,
                                inventory_type) or \
                           self.match_candidate_attribute(
                               candidate,
                               "physical_location_id",
                               restricted_complex_id,
                               name,
                               inventory_type):
                            continue
                        else:
                            resolved_demands[name].append(candidate)
                else:
                    LOG.error("Unknown inventory_type "
                              " {}".format(inventory_type))

        return resolved_demands

    def match_hpa(self, candidate, features):
        """Match HPA features requirement with the candidate flavors """
        hpa_provider = hpa_utils.HpaMatchProvider(candidate, self.feature_json)
        flavor_map = hpa_provider.match_flavor()
        return flavor_map

