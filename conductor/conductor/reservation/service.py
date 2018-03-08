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

import cotyledon
import time
import socket
from oslo_config import cfg
from oslo_log import log

from conductor.common.models import plan
from conductor.common.music import api
from conductor.common.music import messaging as music_messaging
from conductor.common.music.model import base
from conductor.i18n import _LE, _LI
from conductor import messaging
from conductor import service
from conductor.common.utils import conductor_logging_util as log_util


LOG = log.getLogger(__name__)

CONF = cfg.CONF

reservation_OPTS = [
    cfg.IntOpt('workers',
               default=1,
               min=1,
               help='Number of workers for reservation service. '
                    'Default value is 1.'),
    cfg.IntOpt('reserve_retries',
               default=3,
               help='Number of times reservation/release '
                    'should be attempted.'),
    cfg.IntOpt('timeout',
               default=600,
               min=1,
               help='Timeout for detecting a VM is down, and other VMs can pick the plan up and resereve. '
                    'Default value is 600 seconds. (integer value)'),
    cfg.BoolOpt('concurrent',
                default=False,
                help='Set to True when reservation will run in active-active '
                     'mode. When set to False, reservation will restart any '
                     'orphaned reserving requests at startup.'),
    cfg.IntOpt('max_reservation_counter',
               default=1,
               min=1)
]

CONF.register_opts(reservation_OPTS, group='reservation')

# Pull in service opts. We use them here.
OPTS = service.OPTS
CONF.register_opts(OPTS)


class ReservationServiceLauncher(object): # pragma: no cover
    """Launcher for the reservation service."""

    def __init__(self, conf):
        self.conf = conf

        # Set up Music access.
        self.music = api.API()
        self.music.keyspace_create(keyspace=conf.keyspace)

        # Dynamically create a plan class for the specified keyspace
        self.Plan = base.create_dynamic_model(
            keyspace=conf.keyspace, baseclass=plan.Plan, classname="Plan")


        if not self.Plan:
            raise

    def run(self):
        kwargs = {'plan_class': self.Plan}
        svcmgr = cotyledon.ServiceManager()
        svcmgr.add(ReservationService,
                   workers=self.conf.reservation.workers,
                   args=(self.conf,), kwargs=kwargs)
        svcmgr.run()


class ReservationService(cotyledon.Service): # pragma: no cover
    """reservation service."""

    # This will appear in 'ps xaf'
    name = "Conductor Reservation"

    def __init__(self, worker_id, conf, **kwargs):
        """Initializer"""
        LOG.debug("%s" % self.__class__.__name__)
        super(ReservationService, self).__init__(worker_id)
        self._init(conf, **kwargs)
        self.running = True

        self.reservation_owner_condition = {
            "reservation_owner": socket.gethostname()
        }
        self.solved_status_condition = {
            "status": self.Plan.SOLVED
        }
        self.reservating_status_condition = {
            "status": self.Plan.RESERVING
        }


    def _init(self, conf, **kwargs):
        """Set up the necessary ingredients."""
        self.conf = conf
        self.kwargs = kwargs

        self.Plan = kwargs.get('plan_class')

        # Set up the RPC service(s) we want to talk to.
        self.data_service = self.setup_rpc(conf, "data")

        # Set up Music access.
        self.music = api.API()

        # Number of retries for reservation/release
        self.reservation_retries = self.conf.reservation.reserve_retries

        if not self.conf.reservation.concurrent:
            self._reset_reserving_status()

    def _gracefully_stop(self):
        """Gracefully stop working on things"""
        pass

    def current_time_seconds(self):
        """Current time in milliseconds."""
        return int(round(time.time()))

    def millisec_to_sec(self, millisec):
        """Convert milliseconds to seconds"""
        return millisec/1000

    def _reset_reserving_status(self):
        """Reset plans being reserved so they can be reserved again.

        Use this only when the reservation service is not running concurrently.
        """
        plans = self.Plan.query.all()
        for the_plan in plans:
            if the_plan.status == self.Plan.RESERVING:
                the_plan.status = self.Plan.SOLVED
                # Use only in active-passive mode, so don't have to be atomic
                the_plan.update()

    def _restart(self):
        """Prepare to restart the service"""
        pass

    def setup_rpc(self, conf, topic):
        """Set up the RPC Client"""
        # TODO(jdandrea): Put this pattern inside music_messaging?
        transport = messaging.get_transport(conf=conf)
        target = music_messaging.Target(topic=topic)
        client = music_messaging.RPCClient(conf=conf,
                                           transport=transport,
                                           target=target)
        return client

    def try_reservation_call(self, method, candidate_list,
                             reservation_name, reservation_type,
                             controller, request):
        # Call data service for reservation
        # need to do this for self.reserve_retries times
        ctxt = {}
        args = {'method': method,
                'candidate_list': candidate_list,
                'reservation_name': reservation_name,
                'reservation_type': reservation_type,
                'controller': controller,
                'request': request
                }

        method_name = "call_reservation_operation"
        attempt_count = 1
        while attempt_count <= self.reservation_retries:
            is_success = self.data_service.call(ctxt=ctxt,
                                                method=method_name,
                                                args=args)
            LOG.debug("Attempt #{} calling method {} for candidate "
                      "{} - response: {}".format(attempt_count,
                                                 method,
                                                 candidate_list,
                                                 is_success))
            if is_success:
                return True
            attempt_count += 1
        return False

    def rollback_reservation(self, reservation_list):
        """Function to rollback(release) reservations"""
        # TODO(snarayanan): Need to test this once the API is ready
        for reservation in reservation_list:
            candidate_list = reservation['candidate_list']
            reservation_name = reservation['reservation_name']
            reservation_type = reservation['reservation_type']
            controller = reservation['controller']
            request = reservation['request']

            is_success = self.try_reservation_call(
                method="release",
                candidate_list=candidate_list,
                reservation_name=reservation_name,
                reservation_type=reservation_type,
                controller=controller,
                request=request
            )
            if not is_success:
                # rollback failed report error to SDNC
                message = _LE("Unable to release reservation "
                              "{}").format(reservation)
                LOG.error(message)
                return False
                # move to the next reserved candidate
        return True

    def run(self):
        """Run"""
        LOG.debug("%s" % self.__class__.__name__)
        # TODO(snarayanan): This is really meant to be a control loop
        # As long as self.running is true, we process another request.
        while self.running:

            # Delay time (Seconds) for MUSIC requests.
            time.sleep(self.conf.delay_time)

            # plans = Plan.query().all()
            # Find the first plan with a status of SOLVED.
            # Change its status to RESERVING.

            solution = None
            translation = None
            p = None
            # requests_to_reserve = dict()
            plans = self.Plan.query.all()
            found_solved_template = False

            for p in plans:
                if p.status == self.Plan.RESERVING and \
                (self.current_time_seconds() - self.millisec_to_sec(p.updated)) > self.conf.reservation.timeout:
                    p.status = self.Plan.SOLVED
                    p.update(condition=self.reservating_status_condition)
                    break
                elif p.status == self.Plan.SOLVED:
                    solution = p.solution
                    translation = p.translation
                    found_solved_template = True
                    break


            if found_solved_template and not solution:
                message = _LE("Plan {} status is solved, yet "
                              "the solution wasn't found").format(p.id)
                LOG.error(message)
                p.status = self.Plan.ERROR
                p.message = message
                p.update(condition=self.solved_status_condition)
                continue  # continue looping
            elif found_solved_template and p and p.reservation_counter >= self.conf.reservation.max_reservation_counter:
                message = _LE("Tried {} times. Plan {} is unable to reserve") \
                    .format(self.conf.reservation.max_reservation_counter, p.id)
                LOG.error(message)
                p.status = self.Plan.ERROR
                p.message = message
                p.update(condition=self.solved_status_condition)
                continue
            elif not solution:
                continue  # continue looping

            log_util.setLoggerFilter(LOG, self.conf.keyspace, p.id)

            # update status to reserving
            p.status = self.Plan.RESERVING

            p.reservation_counter += 1
            p.reservation_owner = socket.gethostname()
            _is_updated = p.update(condition=self.solved_status_condition)

            if 'FAILURE' in _is_updated:
                continue

            LOG.info(_LI("Plan {} with request id {} is reserving by machine {}. Tried to reserve it for {} times.").
                     format(p.id, p.name, p.reservation_owner, p.reservation_counter))

            # begin reservations
            # if plan needs reservation proceed with reservation
            # else set status to done.
            reservations = None
            _is_success = 'FAILURE | Could not acquire lock'

            if translation:
                conductor_solver = translation.get("conductor_solver")
                if conductor_solver:
                    reservations = conductor_solver.get("reservations")
                else:
                    LOG.error("no conductor_solver in "
                              "translation for Plan {}".format(p.id))

            if reservations:

                recommendations = solution.get("recommendations")
                reservation_list = list()

                for reservation, resource in reservations.get("demands",
                                                              {}).items():
                    candidates = list()
                    reservation_demand = resource.get("demand")
                    reservation_name = resource.get("name")
                    reservation_type = resource.get("type")

                    reservation_properties = resource.get("properties")
                    if reservation_properties:
                        controller = reservation_properties.get(
                            "controller")
                        request = reservation_properties.get("request")

                    for recommendation in recommendations:
                        for demand, r_resource in recommendation.items():
                            if demand == reservation_demand:
                                # get selected candidate from translation
                                selected_candidate_id = \
                                    r_resource.get("candidate")\
                                    .get("candidate_id")
                                demands = \
                                    translation.get("conductor_solver")\
                                    .get("demands")
                                for demand_name, d_resource in \
                                        demands.items():
                                    if demand_name == demand:
                                        for candidate in d_resource\
                                                .get("candidates"):
                                            if candidate\
                                                .get("candidate_id") ==\
                                                    selected_candidate_id:
                                                candidates\
                                                    .append(candidate)

                    is_success = self.try_reservation_call(
                        method="reserve",
                        candidate_list=candidates,
                        reservation_name=reservation_name,
                        reservation_type=reservation_type,
                        controller=controller,
                        request=request)

                    # if reservation succeeds continue with next candidate
                    if is_success:
                        curr_reservation = dict()
                        curr_reservation['candidate_list'] = candidates
                        curr_reservation['reservation_name'] = \
                            reservation_name
                        curr_reservation['reservation_type'] = \
                            reservation_type
                        curr_reservation['controller'] = controller
                        curr_reservation['request'] = request
                        reservation_list.append(curr_reservation)
                    else:
                        # begin roll back of all reserved resources on
                        # the first failed reservation
                        rollback_status = \
                            self.rollback_reservation(reservation_list)
                        # statuses
                        if rollback_status:
                            # released all reservations,
                            # move plan to translated
                            p.status = self.Plan.TRANSLATED
                            # TODO(larry): Should be replaced by the new api from MUSIC
                            while 'FAILURE | Could not acquire lock' in _is_success:
                                _is_success = p.update(condition=self.reservation_owner_condition)
                            del reservation_list[:]
                        else:
                            LOG.error("Reservation rollback failed")
                            p.status = self.Plan.ERROR
                            p.message = "Reservation release failed"
                            # TODO(larry): Should be replaced by the new api from MUSIC
                            while 'FAILURE | Could not acquire lock' in _is_success:
                                _is_success = p.update(condition=self.reservation_owner_condition)
                        break  # reservation failed

                    continue
                        # continue with reserving the next candidate

            # verify if all candidates have been reserved
            if p.status == self.Plan.RESERVING:
                # all reservations succeeded.
                LOG.info(_LI("Plan {} with request id {} Reservation complete").
                         format(p.id, p.name))
                LOG.debug("Plan {} Reservation complete".format(p.id))
                p.status = self.Plan.DONE

                while 'FAILURE | Could not acquire lock' in _is_success:
                    _is_success = p.update(condition=self.reservation_owner_condition)

            continue
            # done reserving continue to loop

    def terminate(self):
        """Terminate"""
        LOG.debug("%s" % self.__class__.__name__)
        self.running = False
        self._gracefully_stop()
        super(ReservationService, self).terminate()

    def reload(self):
        """Reload"""
        LOG.debug("%s" % self.__class__.__name__)
        self._restart()

