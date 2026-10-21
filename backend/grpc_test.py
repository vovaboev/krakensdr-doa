from concurrent import futures
import logging

import grpc
import adder_pb2
import adder_pb2_grpc

class Adder(adder_pb2_grpc.AdderServicer):
    def add(self, request, context):
        return adder_pb2.AdderResponse(c = request.a + request.b)


def serve():
    port = "5005"
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    adder_pb2_grpc.add_AdderServicer_to_server(Adder(), server)
    server.add_insecure_port("[::]:" + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()


logging.basicConfig(filename="log.txt", level=10)
serve()
