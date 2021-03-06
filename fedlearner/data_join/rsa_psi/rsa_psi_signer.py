# Copyright 2020 The FedLearner Authors. All Rights Reserved.
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

# coding: utf-8

import logging
import sys
from concurrent import futures

import grpc
from gmpy2 import powmod # pylint: disable=no-name-in-module

from fedlearner.common import common_pb2 as common_pb
from fedlearner.common import data_join_service_pb2 as dj_pb
from fedlearner.common import data_join_service_pb2_grpc as dj_grpc

class RsaPsiSignServer(dj_grpc.RsaPsiSignServiceServicer):
    def __init__(self, psi_sign_fn):
        super(RsaPsiSignServer, self).__init__()
        self._psi_sign_fn = psi_sign_fn

    def SignIds(self, request, context):
        try:
            return self._psi_sign_fn(request)
        except Exception: # pylint: disable=broad-except
            response = dj_pb.SignBlindIdsResponse()
            response.status.code = -1
            response.status.error_message = sys.exc_info()

class RsaPsiSigner(object):
    def __init__(self, rsa_prv_key, offload_processor_number):
        self._rsa_private_key = rsa_prv_key
        self._process_pool_executor = None
        if offload_processor_number > 0:
            self._process_pool_executor = \
                    futures.ProcessPoolExecutor(offload_processor_number)


    def _psi_sign_fn(self, request):
        d, n = self._rsa_private_key.d, self._rsa_private_key.n
        if self._process_pool_executor is not None:
            rids = [rid for rid in request.ids] # pylint: disable=unnecessary-comprehension
            sign_future = self._process_pool_executor.submit(
                    RsaPsiSigner._psi_sign_impl, rids, d, n
                )
            return dj_pb.SignIdsResponse(
                    status=common_pb.Status(code=0),
                    signed_ids=sign_future.result()
                )
        return dj_pb.SignIdsResponse(
                status=common_pb.Status(code=0),
                signed_ids=RsaPsiSigner._psi_sign_impl(request.ids, d, n)
            )

    @staticmethod
    def _psi_sign_impl(items, d, n):
        return [powmod(int(item), d, n).digits() for item in items]

    def start(self, listen_port):
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=100))
        dj_grpc.add_RsaPsiSignServiceServicer_to_server(
                RsaPsiSignServer(self._psi_sign_fn), self._server
            )
        self._server.add_insecure_port('[::]:%d' % listen_port)
        self._server.start()
        logging.info('RsaPsiSigner Server start on port[%d].', listen_port)

    def stop(self):
        self._server.stop(None)
        if self._process_pool_executor is not None:
            self._process_pool_executor.shutdown(True)
        logging.info('RsaPsiSigner Server stopped')

    def run(self, listen_port):
        self.start(listen_port)
        self._server.wait_for_termination()
        self.stop()
