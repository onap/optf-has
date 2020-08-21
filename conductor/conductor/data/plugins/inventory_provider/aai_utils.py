#
# -------------------------------------------------------------------------
#   Copyright (C) 2020 Wipro Limited.
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

query_params = {'service_instance': ["service-instance-id", "service-instance-name", "environment-context",
                                     "workload-context", "model-invariant-id", "model-version-id", "widget-model-id",
                                     "widget-model-version", "service-instance-location-id", "orchestration-status"]
                }


def convert_hyphen_to_under_score(hyphened_dict):
    converted_dict = dict()
    for key in hyphened_dict:
        if '-' in key:
            converted_dict[key.replace('-', '_')] = hyphened_dict[key]
        else:
            converted_dict[key] = hyphened_dict[key]
    if 'resource_version' in converted_dict:
        converted_dict.pop('resource_version')
    return converted_dict


def add_query_params(filtering_attributes):
    if not filtering_attributes:
        return ''
    url = '?'
    for key, value in filtering_attributes.items():
        url = url + key + "=" + value + "&"
    return url


def add_query_params_and_depth(filtering_attributes, depth):
    url_with_query_params = add_query_params(filtering_attributes)
    return url_with_query_params + "depth=" + depth if url_with_query_params else "?depth=" + depth


def get_first_level_and_second_level_filter(filtering_attributes, aai_node):
    second_level_filters = dict()
    valid_query_params = query_params.get(aai_node)
    for key in list(filtering_attributes):
        if key not in valid_query_params:
            second_level_filters[key] = filtering_attributes[key]
            del filtering_attributes[key]
    return second_level_filters


def get_inv_values_for_second_level_filter(second_level_filters, nssi_instance):
    inventory_attributes = dict()
    for key in list(second_level_filters):
        inventory_attributes[key] = nssi_instance.get(key)
    return inventory_attributes
