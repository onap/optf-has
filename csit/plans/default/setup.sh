#!/bin/bash
#
# Copyright 2016-2017 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
echo "# aaf-sms setup.sh script";
source ${WORKSPACE}/scripts/setup-sms.sh

#
# Script for setting up etcd3
#
echo "# etcd scripts calling";
source ${WORKSPACE}/scripts/etcd_script.sh

#
echo "# simulator scripts calling";
source ${WORKSPACE}/scripts/simulator_script.sh

# add here eventual scripts needed for optf/has
#
echo "# optf/has scripts calling";
source ${WORKSPACE}/scripts/has_script.sh

#
# add here below the start of all docker containers needed for optf/has CSIT testing
#
echo "# optf/has scripts docker containers spinoff";

#
# add here all the configuration steps eventually needed to be carried out for optf/has CSIT testing
#
echo "# optf/has configuration step";


#
# add here all ROBOT_VARIABLES settings
#
echo "# optf/has robot variables settings";
echo "conductor ip = ${COND_IP}"

ROBOT_VARIABLES="-v COND_HOSTNAME:http://${COND_IP} -v COND_PORT:8091"

echo ${ROBOT_VARIABLES}



