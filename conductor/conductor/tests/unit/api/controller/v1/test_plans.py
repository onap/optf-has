#
# -------------------------------------------------------------------------
#   Copyright (c) 2018 Intel Corporation Intellectual Property
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
"""Test case for PlansController"""

import copy
import json
import uuid
import base64

import mock
from conductor.api.controllers.v1 import plans
from conductor.tests.unit.api import base_api
from oslo_serialization import jsonutils


class TestPlansController(base_api.BaseApiTest):

    extra_environment = {
        'AUTH_TYPE': 'Basic',
        'HTTP_AUTHORIZATION': 'Basic {}'.format(base64.encodestring('admin:default').strip())}

    def test_index_options(self):
        actual_response = self.app.options('/v1/plans', expect_errors=True)
        self.assertEqual(204, actual_response.status_int)
        self.assertEqual("GET,POST", actual_response.headers['Allow'])

    @mock.patch.object(plans.LOG, 'error')
    @mock.patch.object(plans.LOG, 'debug')
    @mock.patch.object(plans.LOG, 'warning')
    @mock.patch.object(plans.LOG, 'info')
    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_get(self, rpc_mock, info_mock, warning_mock, debug_mock,
                       error_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = json.loads(open(req_json_file).read())
        plan_id = str(uuid.uuid4())
        params['id'] = plan_id
        rpc_mock.return_value = {'plans': [params]}
        actual_response = self.app.get('/v1/plans', extra_environ=self.extra_environment)
        print ("App is {}".format(self.app))

        self.assertEqual(200, actual_response.status_int)

    @mock.patch.object(plans.LOG, 'error')
    @mock.patch.object(plans.LOG, 'debug')
    @mock.patch.object(plans.LOG, 'warning')
    @mock.patch.object(plans.LOG, 'info')
    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_post_error(self, rpc_mock, info_mock, warning_mock,
                              debug_mock,
                              error_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = jsonutils.dumps(json.loads(open(req_json_file).read()))
        rpc_mock.return_value = {}
        response = self.app.post('/v1/plans', params=params,
                                 expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(500, response.status_int)

    @mock.patch.object(plans.LOG, 'error')
    @mock.patch.object(plans.LOG, 'debug')
    @mock.patch.object(plans.LOG, 'warning')
    @mock.patch.object(plans.LOG, 'info')
    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_post_success(self, rpc_mock, info_mock, warning_mock,
                                debug_mock,
                                error_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = json.loads(open(req_json_file).read())
        mock_params = copy.deepcopy(params)
        plan_id = str(uuid.uuid4())

        mock_params['id'] = plan_id
        rpc_mock.return_value = {'plan': mock_params}
        params = json.dumps(params)
        response = self.app.post('/v1/plans', params=params,
                                 expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(201, response.status_int)

    def test_index_httpmethod_notallowed(self):
        actual_response = self.app.put('/v1/plans', expect_errors=True)
        self.assertEqual(405, actual_response.status_int)
        actual_response = self.app.patch('/v1/plans', expect_errors=True)
        self.assertEqual(405, actual_response.status_int)


class TestPlansItemController(base_api.BaseApiTest):

    extra_environment = {
        'AUTH_TYPE': 'Basic',
        'HTTP_AUTHORIZATION': 'Basic {}'.format(base64.encodestring('admin:default').strip())}

    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_options(self, rpc_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = json.loads(open(req_json_file).read())
        plan_id = str(uuid.uuid4())
        params['id'] = plan_id
        rpc_mock.return_value = {'plans': [params]}
        url = '/v1/plans/' + plan_id
        print(url)
        actual_response = self.app.options(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(204, actual_response.status_int)
        self.assertEqual("GET,DELETE", actual_response.headers['Allow'])

    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_httpmethod_notallowed(self, rpc_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = json.loads(open(req_json_file).read())
        plan_id = str(uuid.uuid4())
        params['id'] = plan_id
        rpc_mock.return_value = {'plans': [params]}
        url = '/v1/plans/' + plan_id
        actual_response = self.app.put(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(405, actual_response.status_int)
        actual_response = self.app.patch(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(405, actual_response.status_int)
        actual_response = self.app.post(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(405, actual_response.status_int)

    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_get(self, rpc_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = json.loads(open(req_json_file).read())
        plan_id = str(uuid.uuid4())
        params['id'] = plan_id
        expected_response = {'plans': [params]}
        rpc_mock.return_value = {'plans': [params]}
        url = '/v1/plans/' + plan_id
        actual_response = self.app.get(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(200, actual_response.status_int)
        self.assertJsonEqual(expected_response,
                             json.loads(actual_response.body))

    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_get_non_exist(self, rpc_mock):
        rpc_mock.return_value = {'plans': []}
        plan_id = str(uuid.uuid4())
        url = '/v1/plans/' + plan_id
        actual_response = self.app.get(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(404, actual_response.status_int)

    @mock.patch('conductor.common.music.messaging.component.RPCClient.call')
    def test_index_delete(self, rpc_mock):
        req_json_file = './conductor/tests/unit/api/controller/v1/plans.json'
        params = json.loads(open(req_json_file).read())
        plan_id = str(uuid.uuid4())
        params['id'] = plan_id
        rpc_mock.return_value = {'plans': [params]}
        url = '/v1/plans/' + plan_id
        actual_response = self.app.delete(url=url, expect_errors=True, extra_environ=self.extra_environment)
        self.assertEqual(204, actual_response.status_int)
